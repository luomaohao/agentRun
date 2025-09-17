import asyncio

import pytest

from workflow_engine.engine import ExecutionEngine
from workflow_engine.models import ExecutionStatus, StateMachineDefinition, StateTransition
from workflow_engine.parser import WorkflowParser


def test_execution_engine_runs_dag():
    async def runner():
        parser = WorkflowParser()
        workflow = parser.parse_dict(
            {
                "workflow": {
                    "id": "dag-workflow",
                    "name": "DAG",
                    "version": "1",
                    "type": "dag",
                    "nodes": [
                        {"id": "start", "type": "task"},
                        {"id": "finish", "type": "task"},
                    ],
                    "edges": [
                        {"from": "start", "to": "finish"},
                    ],
                }
            }
        )

        engine = ExecutionEngine()
        observed = []

        async def handler(node, context):
            observed.append(node.id)
            return node.id

        engine.register_node_handler("task", handler)
        execution_id = await engine.execute_workflow(workflow)
        await engine.wait_for_idle()

        events = list(engine.persistence.fetch_execution_events(execution_id))
        assert observed == ["start", "finish"]
        assert any(event["event"] == "node_completed" for event in events)
        await engine.scheduler.stop()

    asyncio.run(runner())


def test_execution_engine_retries_and_compensation():
    async def runner():
        parser = WorkflowParser()
        workflow = parser.parse_dict(
            {
                "workflow": {
                    "id": "retry-workflow",
                    "name": "Retry",
                    "version": "1",
                    "type": "dag",
                    "nodes": [
                        {
                            "id": "start",
                            "type": "task",
                            "config": {"retries": 1, "retry_delay": 0.0},
                        },
                    ],
                }
            }
        )

        engine = ExecutionEngine()
        attempts = {"count": 0}
        compensated = {"done": False}

        node = workflow.nodes["start"]

        def compensate(context, payload):
            compensated["done"] = True

        node.compensation = compensate

        async def failing(node, context):
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise RuntimeError("failure")
            return "ok"

        engine.register_node_handler("task", failing)
        execution_id = await engine.execute_workflow(workflow)
        await engine.wait_for_idle()

        assert attempts["count"] == 2
        events = list(engine.persistence.fetch_execution_events(execution_id))
        assert events[-1]["event"] == "node_completed"
        assert not compensated["done"]
        await engine.scheduler.stop()

    asyncio.run(runner())


def test_state_machine_execution():
    async def runner():
        parser = WorkflowParser()
        workflow = parser.parse_dict(
            {
                "workflow": {
                    "id": "sm-workflow",
                    "name": "SM",
                    "version": "1",
                    "type": "state_machine",
                    "nodes": [
                        {"id": "start", "type": "task"},
                        {"id": "approve", "type": "task"},
                        {"id": "reject", "type": "task"},
                    ],
                }
            }
        )

        engine = ExecutionEngine()

        definition = StateMachineDefinition(
            states={"start", "approve", "reject"},
            initial_state="start",
            final_states={"approve", "reject"},
            transitions=[
                StateTransition(
                    source="start",
                    target="approve",
                    condition=lambda ctx: ctx.variables.get("approved", False),
                ),
                StateTransition(
                    source="start",
                    target="reject",
                    condition=lambda ctx: not ctx.variables.get("approved", False),
                ),
            ],
        )

        engine.state_machine.register("sm-workflow", definition)

        async def handler(node, context):
            return node.id

        engine.register_node_handler("task", handler)
        execution_id = await engine.execute_workflow(workflow, {"approved": True})
        await engine.wait_for_idle()

        with engine.persistence._connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT status FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        assert row[0] == ExecutionStatus.COMPLETED.value
        await engine.scheduler.stop()

    asyncio.run(runner())
