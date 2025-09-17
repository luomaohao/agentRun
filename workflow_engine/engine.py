"""Asynchronous execution engine coordinating workflows."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .errors import ExecutionFailed
from .models import (
    ExecutionContext,
    ExecutionPlan,
    ExecutionStatus,
    Node,
    ScheduledTask,
    Workflow,
    WorkflowType,
)
from .monitoring import EventLogger, MetricsRecorder, TracingManager
from .persistence import PersistenceLayer
from .scheduler import ExecutionPlanCache, TaskScheduler
from .state_machine import StateMachineService

LOGGER = logging.getLogger("workflow.engine")


class ExecutionEngine:
    """Coordinates workflow execution using the scheduler."""

    def __init__(
        self,
        persistence: Optional[PersistenceLayer] = None,
        scheduler: Optional[TaskScheduler] = None,
        state_machine_service: Optional[StateMachineService] = None,
        metrics: Optional[MetricsRecorder] = None,
        tracer: Optional[TracingManager] = None,
        event_logger: Optional[EventLogger] = None,
    ) -> None:
        self.persistence = persistence or PersistenceLayer()
        self.scheduler = scheduler or TaskScheduler()
        self.state_machine = state_machine_service or StateMachineService()
        self.metrics = metrics or MetricsRecorder()
        self.tracer = tracer or TracingManager()
        self.events = event_logger or EventLogger()
        self.plan_cache = ExecutionPlanCache()
        self._node_handlers: Dict[str, Callable[[Node, ExecutionContext], Awaitable[Any]]] = {}
        self._active_plans: Dict[str, ExecutionPlan] = {}

    def register_node_handler(
        self, node_type: str, handler: Callable[[Node, ExecutionContext], Awaitable[Any]]
    ) -> None:
        self._node_handlers[node_type] = handler

    async def execute_workflow(
        self, workflow: Workflow, context_variables: Optional[Dict[str, Any]] = None
    ) -> str:
        execution_id = uuid.uuid4().hex
        context = ExecutionContext(
            workflow_id=workflow.id,
            execution_id=execution_id,
            variables=context_variables or {},
            status=ExecutionStatus.PENDING,
        )
        self.persistence.save_workflow(workflow)
        self.persistence.create_execution(workflow, context)
        self.persistence.update_execution_status(context, ExecutionStatus.RUNNING)
        if workflow.type == WorkflowType.STATE_MACHINE:
            await self._execute_state_machine(workflow, context)
        else:
            plan = self._build_plan(workflow)
            self._active_plans[context.execution_id] = plan
            await self.scheduler.start(self._execute_task)
            await self._schedule_initial(plan, context)
        return execution_id

    async def wait_for_idle(self) -> None:
        await self.scheduler.wait_until_idle()

    def _build_plan(self, workflow: Workflow) -> ExecutionPlan:
        cached = self.plan_cache.get(self._plan_cache_key(workflow))
        if cached is None:
            cached = self._create_execution_plan(workflow)
            self.plan_cache.put(self._plan_cache_key(workflow), cached)
        plan = ExecutionPlan(workflow=workflow, start_nodes=list(cached.start_nodes))
        for node in plan.start_nodes:
            plan.mark_ready(node.id)
        return plan

    def _plan_cache_key(self, workflow: Workflow) -> str:
        return f"{workflow.id}:{workflow.version}:{workflow.type.value}"

    def _create_execution_plan(self, workflow: Workflow) -> ExecutionPlan:
        start_nodes = [node for node in workflow.nodes.values() if not workflow.upstream(node.id)]
        plan = ExecutionPlan(workflow=workflow, start_nodes=start_nodes)
        for node in start_nodes:
            plan.mark_ready(node.id)
        return plan

    async def _schedule_initial(self, plan: ExecutionPlan, context: ExecutionContext) -> None:
        tasks = [ScheduledTask(node=plan.workflow.nodes[node_id], context=context) for node_id in plan.ready]
        plan.ready.clear()
        await self.scheduler.schedule(tasks)

    async def _execute_task(self, scheduled: ScheduledTask) -> None:
        node = scheduled.node
        context = scheduled.context
        handler = self._node_handlers.get(node.type)
        if handler is None:
            raise ExecutionFailed(f"No handler registered for node type {node.type}")

        attempt = 0
        while True:
            attempt += 1
            start = time.time()
            try:
                with self.tracer.span(f"node.{node.type}.{node.id}", execution=context.execution_id):
                    result = await handler(node, context)
                duration = time.time() - start
                self.metrics.observe(
                    "node_duration_seconds",
                    duration,
                    labels={"node_id": node.id, "workflow_id": context.workflow_id},
                )
                context.record_result(node.id, result)
                self.persistence.record_event(
                    context.execution_id,
                    "node_completed",
                    node_id=node.id,
                    payload={"duration": duration},
                )
                break
            except Exception as exc:  # pragma: no cover - resilience path
                retry = context.increment_retry(node.id)
                self.events.log(
                    "node_failed",
                    node_id=node.id,
                    execution_id=context.execution_id,
                    attempt=str(retry),
                    error=str(exc),
                )
                if retry > node.retries:
                    if node.compensation:
                        node.compensation(context, {"error": str(exc)})
                        self.persistence.record_event(
                            context.execution_id,
                            "node_compensated",
                            node_id=node.id,
                            payload={"error": str(exc)},
                        )
                    raise ExecutionFailed(f"Node {node.id} failed after retries") from exc
                await asyncio.sleep(node.retry_delay or 0.01)

        if context.execution_id in self._active_plans:
            await self._on_node_complete(node, context)

    async def _on_node_complete(self, node: Node, context: ExecutionContext) -> None:
        plan = self._active_plans[context.execution_id]
        plan.mark_completed(node.id)
        workflow = plan.workflow
        downstream = workflow.downstream(node.id)
        ready_nodes = []
        for downstream_node in downstream:
            upstream_nodes = workflow.upstream(downstream_node.id)
            if all(u.id in plan.completed for u in upstream_nodes):
                ready_nodes.append(downstream_node)
                plan.mark_ready(downstream_node.id)
        if ready_nodes:
            tasks = [ScheduledTask(node=n, context=context) for n in ready_nodes]
            await self.scheduler.schedule_batch(tasks, batch_size=len(tasks))
        if not list(plan.outstanding()):
            self.persistence.update_execution_status(context, ExecutionStatus.COMPLETED)
            self.events.log("workflow_completed", execution_id=context.execution_id)
            self._active_plans.pop(context.execution_id, None)

    async def _execute_state_machine(self, workflow: Workflow, context: ExecutionContext) -> None:
        # Ensure definition exists; raises KeyError if missing which indicates
        # mis-configuration that should be surfaced to the caller.
        self.state_machine.get_definition(workflow.id)
        instance = self.state_machine.create_instance(workflow.id)
        while not instance.is_finished():
            state_node = workflow.nodes[instance.current_state]
            await self._execute_task(ScheduledTask(node=state_node, context=context))
            transition = self.state_machine.transition(instance, context)
            if transition is None:
                break
        if instance.is_finished():
            self.persistence.update_execution_status(context, ExecutionStatus.COMPLETED)
            self.events.log("workflow_completed", execution_id=context.execution_id)
        else:
            self.persistence.update_execution_status(context, ExecutionStatus.FAILED)
            self.events.log("workflow_failed", execution_id=context.execution_id)
