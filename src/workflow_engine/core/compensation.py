"""
补偿管理器 - 实现 Saga 模式
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import deque

from ..models.workflow import Workflow, Node
from ..models.execution import WorkflowExecution, NodeExecution, ExecutionContext
from ..exceptions import WorkflowExecutionError


logger = logging.getLogger(__name__)


class CompensationStrategy(Enum):
    """补偿策略"""
    SEQUENTIAL = "sequential"       # 顺序补偿
    PARALLEL = "parallel"          # 并行补偿
    REVERSE = "reverse"            # 反向补偿（默认）
    CUSTOM = "custom"              # 自定义补偿


@dataclass
class CompensationRecord:
    """补偿记录"""
    node_id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"  # pending, executing, completed, failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class CompensationContext:
    """补偿上下文"""
    workflow_id: str
    execution_id: str
    failed_node_id: str
    strategy: CompensationStrategy = CompensationStrategy.REVERSE
    records: List[CompensationRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class CompensationManager:
    """补偿管理器"""
    
    def __init__(self):
        self.compensation_handlers: Dict[str, Callable] = {}
        self.compensation_contexts: Dict[str, CompensationContext] = {}
        self._register_default_handlers()
    
    def _register_default_handlers(self):
        """注册默认补偿处理器"""
        self.register_handler("rollback", self._rollback_handler)
        self.register_handler("undo", self._undo_handler)
        self.register_handler("notify", self._notify_handler)
        self.register_handler("cleanup", self._cleanup_handler)
    
    def register_handler(self, action_type: str, handler: Callable):
        """注册补偿处理器"""
        self.compensation_handlers[action_type] = handler
        logger.info(f"Registered compensation handler: {action_type}")
    
    async def create_compensation_plan(
        self,
        workflow: Workflow,
        execution: WorkflowExecution,
        failed_node_id: str,
        strategy: CompensationStrategy = CompensationStrategy.REVERSE
    ) -> CompensationContext:
        """创建补偿计划"""
        context = CompensationContext(
            workflow_id=workflow.id,
            execution_id=execution.id,
            failed_node_id=failed_node_id,
            strategy=strategy
        )
        
        # 获取需要补偿的节点列表
        nodes_to_compensate = self._get_nodes_to_compensate(
            workflow,
            execution,
            failed_node_id
        )
        
        # 根据策略排序节点
        if strategy == CompensationStrategy.REVERSE:
            nodes_to_compensate.reverse()
        
        # 创建补偿记录
        for node in nodes_to_compensate:
            compensation_config = node.metadata.get("compensation", {})
            if compensation_config:
                record = CompensationRecord(
                    node_id=node.id,
                    action=compensation_config.get("action", "rollback"),
                    params=compensation_config.get("params", {})
                )
                context.records.append(record)
        
        self.compensation_contexts[execution.id] = context
        
        logger.info(
            f"Created compensation plan for execution {execution.id} "
            f"with {len(context.records)} actions"
        )
        
        return context
    
    def _get_nodes_to_compensate(
        self,
        workflow: Workflow,
        execution: WorkflowExecution,
        failed_node_id: str
    ) -> List[Node]:
        """获取需要补偿的节点列表"""
        nodes_to_compensate = []
        
        # 获取所有成功执行的节点
        for node_id, node_execution in execution.node_executions.items():
            if node_execution.status.value == "success" and node_id != failed_node_id:
                node = workflow.get_node(node_id)
                if node and node.metadata.get("compensation"):
                    nodes_to_compensate.append(node)
        
        # 按执行顺序排序（基于开始时间）
        nodes_to_compensate.sort(
            key=lambda n: execution.node_executions[n.id].start_time or datetime.min
        )
        
        return nodes_to_compensate
    
    async def execute_compensation(
        self,
        context: CompensationContext,
        execution: WorkflowExecution
    ) -> bool:
        """执行补偿"""
        logger.info(f"Starting compensation for execution {context.execution_id}")
        
        success = True
        
        try:
            if context.strategy == CompensationStrategy.PARALLEL:
                success = await self._execute_parallel_compensation(context, execution)
            else:
                success = await self._execute_sequential_compensation(context, execution)
            
            if success:
                logger.info(f"Compensation completed successfully for execution {context.execution_id}")
            else:
                logger.error(f"Compensation failed for execution {context.execution_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Compensation error: {e}", exc_info=True)
            return False
    
    async def _execute_sequential_compensation(
        self,
        context: CompensationContext,
        execution: WorkflowExecution
    ) -> bool:
        """顺序执行补偿"""
        for record in context.records:
            try:
                record.status = "executing"
                logger.info(f"Executing compensation for node {record.node_id}: {record.action}")
                
                # 获取处理器
                handler = self.compensation_handlers.get(record.action)
                if not handler:
                    logger.warning(f"No handler for compensation action: {record.action}")
                    record.status = "failed"
                    record.error = f"No handler for action: {record.action}"
                    continue
                
                # 执行补偿
                result = await handler(record, execution)
                
                record.status = "completed"
                record.result = result
                
                logger.info(f"Compensation completed for node {record.node_id}")
                
            except Exception as e:
                logger.error(f"Compensation failed for node {record.node_id}: {e}")
                record.status = "failed"
                record.error = str(e)
                return False
        
        return True
    
    async def _execute_parallel_compensation(
        self,
        context: CompensationContext,
        execution: WorkflowExecution
    ) -> bool:
        """并行执行补偿"""
        tasks = []
        
        for record in context.records:
            task = self._execute_compensation_record(record, execution)
            tasks.append(task)
        
        # 并行执行所有补偿任务
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查结果
        success = True
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                context.records[i].status = "failed"
                context.records[i].error = str(result)
                success = False
            else:
                context.records[i].status = "completed"
                context.records[i].result = result
        
        return success
    
    async def _execute_compensation_record(
        self,
        record: CompensationRecord,
        execution: WorkflowExecution
    ) -> Dict[str, Any]:
        """执行单个补偿记录"""
        record.status = "executing"
        
        handler = self.compensation_handlers.get(record.action)
        if not handler:
            raise ValueError(f"No handler for compensation action: {record.action}")
        
        return await handler(record, execution)
    
    # 默认补偿处理器
    
    async def _rollback_handler(
        self,
        record: CompensationRecord,
        execution: WorkflowExecution
    ) -> Dict[str, Any]:
        """回滚处理器"""
        logger.info(f"Rolling back node {record.node_id}")
        
        # 获取节点执行信息
        node_execution = execution.node_executions.get(record.node_id)
        if not node_execution:
            return {"status": "skipped", "reason": "Node not executed"}
        
        # 执行回滚逻辑
        # TODO: 实现具体的回滚逻辑，如调用反向操作API
        
        return {
            "status": "rolled_back",
            "node_id": record.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _undo_handler(
        self,
        record: CompensationRecord,
        execution: WorkflowExecution
    ) -> Dict[str, Any]:
        """撤销处理器"""
        logger.info(f"Undoing operations for node {record.node_id}")
        
        # 获取节点的输出数据
        node_execution = execution.node_executions.get(record.node_id)
        if not node_execution or not node_execution.output_data:
            return {"status": "skipped", "reason": "No output to undo"}
        
        # 执行撤销逻辑
        # TODO: 实现具体的撤销逻辑
        
        return {
            "status": "undone",
            "node_id": record.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _notify_handler(
        self,
        record: CompensationRecord,
        execution: WorkflowExecution
    ) -> Dict[str, Any]:
        """通知处理器"""
        logger.info(f"Sending compensation notification for node {record.node_id}")
        
        # 发送通知
        # TODO: 实现通知逻辑，如发送邮件、消息等
        
        return {
            "status": "notified",
            "node_id": record.node_id,
            "notification_type": record.params.get("type", "email"),
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def _cleanup_handler(
        self,
        record: CompensationRecord,
        execution: WorkflowExecution
    ) -> Dict[str, Any]:
        """清理处理器"""
        logger.info(f"Cleaning up resources for node {record.node_id}")
        
        # 清理资源
        # TODO: 实现资源清理逻辑
        
        return {
            "status": "cleaned_up",
            "node_id": record.node_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def get_compensation_status(
        self,
        execution_id: str
    ) -> Optional[Dict[str, Any]]:
        """获取补偿状态"""
        context = self.compensation_contexts.get(execution_id)
        if not context:
            return None
        
        total_records = len(context.records)
        completed = sum(1 for r in context.records if r.status == "completed")
        failed = sum(1 for r in context.records if r.status == "failed")
        executing = sum(1 for r in context.records if r.status == "executing")
        pending = sum(1 for r in context.records if r.status == "pending")
        
        return {
            "execution_id": execution_id,
            "strategy": context.strategy.value,
            "total_actions": total_records,
            "completed": completed,
            "failed": failed,
            "executing": executing,
            "pending": pending,
            "created_at": context.created_at.isoformat(),
            "records": [
                {
                    "node_id": r.node_id,
                    "action": r.action,
                    "status": r.status,
                    "error": r.error
                }
                for r in context.records
            ]
        }


class SagaOrchestrator:
    """Saga 编排器"""
    
    def __init__(self, compensation_manager: CompensationManager):
        self.compensation_manager = compensation_manager
        self.saga_definitions: Dict[str, Dict[str, Any]] = {}
    
    def register_saga(
        self,
        saga_id: str,
        steps: List[Dict[str, Any]]
    ):
        """注册 Saga 定义"""
        self.saga_definitions[saga_id] = {
            "id": saga_id,
            "steps": steps,
            "created_at": datetime.utcnow()
        }
    
    async def execute_saga(
        self,
        saga_id: str,
        context: ExecutionContext
    ) -> Dict[str, Any]:
        """执行 Saga"""
        saga_def = self.saga_definitions.get(saga_id)
        if not saga_def:
            raise ValueError(f"Saga {saga_id} not found")
        
        completed_steps = []
        
        try:
            # 执行每个步骤
            for step in saga_def["steps"]:
                result = await self._execute_step(step, context)
                completed_steps.append({
                    "step": step,
                    "result": result
                })
            
            return {
                "status": "completed",
                "saga_id": saga_id,
                "completed_steps": len(completed_steps)
            }
            
        except Exception as e:
            logger.error(f"Saga {saga_id} failed at step {len(completed_steps)}: {e}")
            
            # 执行补偿
            await self._compensate_saga(completed_steps, context)
            
            raise WorkflowExecutionError(f"Saga {saga_id} failed: {e}")
    
    async def _execute_step(
        self,
        step: Dict[str, Any],
        context: ExecutionContext
    ) -> Any:
        """执行 Saga 步骤"""
        # TODO: 实现步骤执行逻辑
        pass
    
    async def _compensate_saga(
        self,
        completed_steps: List[Dict[str, Any]],
        context: ExecutionContext
    ):
        """补偿 Saga"""
        # 反向执行补偿
        for step_info in reversed(completed_steps):
            step = step_info["step"]
            if "compensation" in step:
                try:
                    await self._execute_compensation(
                        step["compensation"],
                        context
                    )
                except Exception as e:
                    logger.error(f"Compensation failed for step: {e}")
