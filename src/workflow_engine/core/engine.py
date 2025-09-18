"""
工作流执行引擎
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timedelta
from uuid import uuid4

from ..models.workflow import Workflow, Node, NodeType, Edge
from ..models.execution import (
    WorkflowExecution, NodeExecution, ExecutionContext,
    ExecutionStatus, NodeExecutionStatus, ExecutionEvent, ExecutionEventType
)
from ..exceptions import (
    WorkflowExecutionError, NodeExecutionError, WorkflowTimeoutError,
    WorkflowCancelledError, RetryExhaustedError, WorkflowValidationError
)
from .scheduler import TaskScheduler, ScheduledTask, ResourceManager
from .parser import WorkflowParser
from ..storage.repository import WorkflowRepository, ExecutionRepository
from ..integrations.event_bus import EventBus
from ..integrations.agent_runtime import AgentRuntime
from ..integrations.tool_registry import ToolRegistry
from .error_handler import ErrorHandler, ErrorContext, ErrorStrategy
from .compensation import CompensationManager, CompensationStrategy


logger = logging.getLogger(__name__)


class NodeExecutor:
    """节点执行器基类"""
    
    async def execute(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行节点"""
        raise NotImplementedError


class AgentNodeExecutor(NodeExecutor):
    """智能体节点执行器"""
    
    def __init__(self, agent_runtime: AgentRuntime):
        self.agent_runtime = agent_runtime
    
    async def execute(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行智能体节点"""
        agent_id = node.config.get('agent_id')
        if not agent_id:
            raise NodeExecutionError(node.id, "Agent ID not specified")
        
        # 准备智能体输入
        agent_input = {}
        for key, expr in node.inputs.items():
            value = await self._evaluate_expression(expr, context)
            agent_input[key] = value
        
        # 调用智能体
        result = await self.agent_runtime.invoke_agent(
            agent_id=agent_id,
            input_data=agent_input,
            context=context.metadata
        )
        
        return result
    
    async def _evaluate_expression(self, expr: str, context: ExecutionContext) -> Any:
        """评估表达式"""
        # 简单实现：支持 ${variable} 和 ${node.output.field} 格式
        if not expr.startswith('${') or not expr.endswith('}'):
            return expr
        
        path = expr[2:-1]  # 去掉 ${ 和 }
        parts = path.split('.')
        
        if len(parts) == 1:
            # 变量引用
            return context.get_variable(parts[0])
        elif len(parts) >= 2:
            # 节点输出引用
            node_output = context.get_node_output(parts[0])
            if node_output and len(parts) > 1:
                # 访问嵌套字段
                result = node_output
                for part in parts[1:]:
                    if isinstance(result, dict):
                        result = result.get(part)
                    else:
                        return None
                return result
        
        return None


class ToolNodeExecutor(NodeExecutor):
    """工具节点执行器"""
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
    
    async def execute(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行工具节点"""
        tool_id = node.config.get('tool_id')
        if not tool_id:
            raise NodeExecutionError(node.id, "Tool ID not specified")
        
        # 准备工具输入
        tool_input = {}
        for key, expr in node.inputs.items():
            value = await self._evaluate_expression(expr, context)
            tool_input[key] = value
        
        # 调用工具
        result = await self.tool_registry.invoke_tool(
            tool_id=tool_id,
            parameters=tool_input
        )
        
        return result
    
    async def _evaluate_expression(self, expr: str, context: ExecutionContext) -> Any:
        """评估表达式（同AgentNodeExecutor）"""
        # TODO: 抽取到公共类
        pass


class ControlNodeExecutor(NodeExecutor):
    """控制节点执行器"""
    
    async def execute(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行控制节点"""
        subtype = node.subtype
        
        if subtype == "switch":
            return await self._execute_switch(node, context)
        elif subtype == "parallel":
            return await self._execute_parallel(node, context)
        elif subtype == "loop":
            return await self._execute_loop(node, context)
        else:
            raise NodeExecutionError(node.id, f"Unknown control node subtype: {subtype}")
    
    async def _execute_switch(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行switch节点"""
        condition = node.config.get('condition', '')
        branches = node.config.get('branches', [])
        
        # 评估条件
        condition_value = await self._evaluate_expression(condition, context)
        
        # 选择分支
        selected_branch = None
        for branch in branches:
            if 'case' in branch and branch['case'] == condition_value:
                selected_branch = branch['target']
                break
            elif 'default' in branch:
                selected_branch = branch['default']
        
        return {"selected_branch": selected_branch}
    
    async def _execute_parallel(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行并行节点"""
        # 并行节点的实际执行由调度器处理
        # 这里只返回元数据
        return {
            "branches": node.config.get('branches', []),
            "wait_all": node.config.get('wait_all', True)
        }
    
    async def _execute_loop(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """执行循环节点"""
        # 循环逻辑需要特殊处理
        condition = node.config.get('condition', '')
        max_iterations = node.config.get('max_iterations', 100)
        
        return {
            "condition": condition,
            "max_iterations": max_iterations,
            "current_iteration": context.get_variable('loop_iteration', 0)
        }
    
    async def _evaluate_expression(self, expr: str, context: ExecutionContext) -> Any:
        """评估表达式"""
        # TODO: 实现表达式评估
        pass


class WorkflowEngine:
    """工作流执行引擎"""
    
    def __init__(
        self,
        workflow_repository: WorkflowRepository = None,
        execution_repository: ExecutionRepository = None,
        scheduler: TaskScheduler = None,
        event_bus: EventBus = None,
        agent_runtime: AgentRuntime = None,
        tool_registry: ToolRegistry = None,
        error_handler: ErrorHandler = None,
        compensation_manager: CompensationManager = None
    ):
        self.workflow_repository = workflow_repository or WorkflowRepository()
        self.execution_repository = execution_repository or ExecutionRepository()
        self.scheduler = scheduler or TaskScheduler()
        self.event_bus = event_bus or EventBus()
        self.agent_runtime = agent_runtime or AgentRuntime()
        self.tool_registry = tool_registry or ToolRegistry()
        self.error_handler = error_handler or ErrorHandler()
        self.compensation_manager = compensation_manager or CompensationManager()
        
        # 注册节点执行器
        self.node_executors: Dict[str, NodeExecutor] = {
            NodeType.AGENT.value: AgentNodeExecutor(self.agent_runtime),
            NodeType.TOOL.value: ToolNodeExecutor(self.tool_registry),
            NodeType.CONTROL.value: ControlNodeExecutor()
        }
        
        # 工作流解析器
        self.parser = WorkflowParser()
        
        # 执行状态缓存
        self._execution_cache: Dict[str, WorkflowExecution] = {}
        self._workflow_cache: Dict[str, Workflow] = {}
        
        # 注册调度器执行器
        self._register_scheduler_executors()
    
    def _register_scheduler_executors(self):
        """注册调度器执行器"""
        for node_type in NodeType:
            self.scheduler.register_executor(
                node_type.value,
                self._create_task_executor(node_type)
            )
    
    def _create_task_executor(self, node_type: NodeType) -> Callable:
        """创建任务执行器"""
        async def executor(task: ScheduledTask, node: Node):
            await self._execute_node_task(task, node)
        return executor
    
    async def create_workflow(self, workflow_def: Union[str, Dict[str, Any]]) -> str:
        """创建工作流"""
        # 解析工作流定义
        workflow = self.parser.parse(workflow_def)
        
        # 验证工作流
        errors = workflow.validate()
        if errors:
            raise WorkflowValidationError(f"Workflow validation failed: {errors}")
        
        # 优化工作流
        workflow = self.parser.optimize_workflow(workflow)
        
        # 保存工作流
        await self.workflow_repository.save(workflow)
        
        # 发布事件
        await self.event_bus.publish(
            "workflow.created",
            {"workflow_id": workflow.id, "name": workflow.name}
        )
        
        return workflow.id
    
    async def execute_workflow(
        self,
        workflow_id: str,
        context: Dict[str, Any] = None,
        async_mode: bool = True
    ) -> str:
        """执行工作流"""
        # 加载工作流定义
        workflow = await self._get_workflow(workflow_id)
        if not workflow:
            raise WorkflowExecutionError(f"Workflow not found: {workflow_id}")
        
        # 创建执行实例
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            workflow_version=workflow.version,
            context=ExecutionContext(
                workflow_id=workflow_id,
                execution_id=str(uuid4()),
                inputs=context or {}
            )
        )
        
        # 保存执行实例
        await self.execution_repository.save(execution)
        self._execution_cache[execution.id] = execution
        
        # 发布执行开始事件
        await self._publish_execution_event(
            execution.id,
            ExecutionEventType.WORKFLOW_STARTED
        )
        
        # 启动执行
        if async_mode:
            # 异步执行
            asyncio.create_task(self._run_workflow(workflow, execution))
            return execution.id
        else:
            # 同步执行
            await self._run_workflow(workflow, execution)
            return execution.id
    
    async def _run_workflow(self, workflow: Workflow, execution: WorkflowExecution):
        """运行工作流"""
        try:
            # 更新执行状态
            execution.start()
            await self.execution_repository.update(execution)
            
            # 调度工作流
            await self.scheduler.schedule_workflow(workflow, execution)
            
            # 等待执行完成
            await self._wait_for_completion(execution)
            
            # 更新最终状态
            if execution.status == ExecutionStatus.RUNNING:
                execution.complete()
                await self.execution_repository.update(execution)
                
                # 发布完成事件
                await self._publish_execution_event(
                    execution.id,
                    ExecutionEventType.WORKFLOW_COMPLETED
                )
            
        except Exception as e:
            logger.error(f"Workflow execution failed: {execution.id}", exc_info=True)
            
            # 更新失败状态
            execution.fail(str(e))
            await self.execution_repository.update(execution)
            
            # 发布失败事件
            await self._publish_execution_event(
                execution.id,
                ExecutionEventType.WORKFLOW_FAILED,
                {"error": str(e)}
            )
            
            raise
    
    async def _wait_for_completion(self, execution: WorkflowExecution):
        """等待执行完成"""
        while not execution.is_terminal_state():
            await asyncio.sleep(0.5)
            
            # 从缓存或存储更新状态
            if execution.id in self._execution_cache:
                execution = self._execution_cache[execution.id]
            else:
                execution = await self.execution_repository.get(execution.id)
    
    async def _execute_node_task(self, task: ScheduledTask, node: Node):
        """执行节点任务"""
        execution = await self._get_execution(task.execution_id)
        if not execution:
            raise NodeExecutionError(node.id, "Execution not found")
        
        # 创建或获取节点执行实例
        node_execution = execution.get_node_execution(node.id)
        if not node_execution:
            node_execution = execution.create_node_execution(node.id)
        
        try:
            # 开始执行
            node_execution.start()
            await self._publish_node_event(
                execution.id,
                node.id,
                ExecutionEventType.NODE_STARTED
            )
            
            # 准备输入数据
            input_data = await self._prepare_node_input(node, execution.context)
            node_execution.input_data = input_data
            
            # 执行节点
            executor = self.node_executors.get(node.type.value)
            if not executor:
                raise NodeExecutionError(node.id, f"No executor for type: {node.type}")
            
            # 设置超时
            timeout = node.timeout or 300  # 默认5分钟
            output_data = await asyncio.wait_for(
                executor.execute(node, execution.context),
                timeout=timeout
            )
            
            # 保存输出
            node_execution.complete(output_data)
            execution.context.set_node_output(node.id, output_data)
            
            # 发布完成事件
            await self._publish_node_event(
                execution.id,
                node.id,
                ExecutionEventType.NODE_COMPLETED
            )
            
        except asyncio.TimeoutError:
            error = WorkflowTimeoutError(f"Node {node.id} timeout after {timeout}s")
            await self._handle_node_error(node, node_execution, error, task)
            
        except Exception as e:
            await self._handle_node_error(node, node_execution, e, task)
        
        finally:
            # 更新执行状态
            await self.execution_repository.update(execution)
    
    async def _handle_node_error(
        self,
        node: Node,
        node_execution: NodeExecution,
        error: Exception,
        task: ScheduledTask
    ):
        """处理节点错误"""
        execution = await self._get_execution(task.execution_id)
        workflow = await self._get_workflow(execution.workflow_id)
        
        # 创建错误上下文
        error_context = ErrorContext(
            error=error,
            node=node,
            execution=execution,
            node_execution=node_execution,
            retry_count=task.retry_count
        )
        
        # 使用错误处理器处理错误
        strategy = await self.error_handler.handle_error(error_context, workflow)
        
        # 根据策略执行相应操作
        if strategy == ErrorStrategy.RETRY:
            # 重新调度节点
            task.retry_count += 1
            await self.scheduler.schedule_node(node, execution)
            
            # 发布重试事件
            await self._publish_node_event(
                task.execution_id,
                node.id,
                ExecutionEventType.NODE_RETRYING,
                {"retry_count": task.retry_count}
            )
            
        elif strategy == ErrorStrategy.COMPENSATE:
            # 创建并执行补偿计划
            compensation_context = await self.compensation_manager.create_compensation_plan(
                workflow,
                execution,
                node.id
            )
            
            # 异步执行补偿
            asyncio.create_task(
                self._execute_compensation(compensation_context, execution)
            )
            
            # 发布补偿事件
            await self._publish_execution_event(
                execution.id,
                ExecutionEventType.WORKFLOW_COMPENSATING,
                {"failed_node": node.id}
            )
            
        elif strategy == ErrorStrategy.SKIP:
            # 发布跳过事件
            await self._publish_node_event(
                task.execution_id,
                node.id,
                ExecutionEventType.NODE_SKIPPED,
                {"reason": str(error)}
            )
            
            # 继续执行下游节点
            await self._trigger_downstream_nodes(task.execution_id, node)
            
        else:  # FAIL 或其他
            # 发布失败事件
            await self._publish_node_event(
                task.execution_id,
                node.id,
                ExecutionEventType.NODE_FAILED,
                {"error": str(error)}
            )
            
            # 更新执行状态
            await self.execution_repository.update(execution)
    
    async def _execute_compensation(self, compensation_context, execution: WorkflowExecution):
        """执行补偿"""
        try:
            # 执行补偿
            success = await self.compensation_manager.execute_compensation(
                compensation_context,
                execution
            )
            
            if success:
                # 发布补偿完成事件
                await self._publish_execution_event(
                    execution.id,
                    ExecutionEventType.WORKFLOW_COMPENSATED,
                    {"compensation_status": "success"}
                )
            else:
                # 发布补偿失败事件
                await self._publish_execution_event(
                    execution.id,
                    ExecutionEventType.WORKFLOW_FAILED,
                    {"compensation_status": "failed"}
                )
            
            # 更新执行状态
            await self.execution_repository.update(execution)
            
        except Exception as e:
            logger.error(f"Compensation execution failed: {e}", exc_info=True)
    
    async def _prepare_node_input(self, node: Node, context: ExecutionContext) -> Dict[str, Any]:
        """准备节点输入数据"""
        input_data = {}
        
        # TODO: 实现输入数据准备逻辑
        # 包括表达式评估、数据映射等
        
        return input_data
    
    async def cancel_execution(self, execution_id: str):
        """取消执行"""
        execution = await self._get_execution(execution_id)
        if not execution:
            raise WorkflowExecutionError(f"Execution not found: {execution_id}")
        
        if execution.is_terminal_state():
            raise WorkflowExecutionError(f"Cannot cancel execution in state: {execution.status}")
        
        # 更新状态
        execution.cancel()
        await self.execution_repository.update(execution)
        
        # 发布取消事件
        await self._publish_execution_event(
            execution_id,
            ExecutionEventType.WORKFLOW_CANCELLED
        )
    
    async def suspend_execution(self, execution_id: str):
        """暂停执行"""
        execution = await self._get_execution(execution_id)
        if not execution:
            raise WorkflowExecutionError(f"Execution not found: {execution_id}")
        
        if execution.status != ExecutionStatus.RUNNING:
            raise WorkflowExecutionError(f"Can only suspend running execution")
        
        # 更新状态
        execution.suspend()
        await self.execution_repository.update(execution)
        
        # 发布暂停事件
        await self._publish_execution_event(
            execution_id,
            ExecutionEventType.WORKFLOW_SUSPENDED
        )
    
    async def resume_execution(self, execution_id: str):
        """恢复执行"""
        execution = await self._get_execution(execution_id)
        if not execution:
            raise WorkflowExecutionError(f"Execution not found: {execution_id}")
        
        if execution.status != ExecutionStatus.SUSPENDED:
            raise WorkflowExecutionError(f"Can only resume suspended execution")
        
        # 更新状态
        execution.resume()
        await self.execution_repository.update(execution)
        
        # 重新调度未完成的节点
        workflow = await self._get_workflow(execution.workflow_id)
        if workflow:
            # TODO: 实现恢复逻辑
            pass
        
        # 发布恢复事件
        await self._publish_execution_event(
            execution_id,
            ExecutionEventType.WORKFLOW_RESUMED
        )
    
    async def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """获取执行状态"""
        execution = await self._get_execution(execution_id)
        if not execution:
            raise WorkflowExecutionError(f"Execution not found: {execution_id}")
        
        return {
            "execution_id": execution.id,
            "workflow_id": execution.workflow_id,
            "status": execution.status.value,
            "start_time": execution.start_time.isoformat() if execution.start_time else None,
            "end_time": execution.end_time.isoformat() if execution.end_time else None,
            "duration": execution.duration,
            "node_executions": {
                node_id: {
                    "status": node_exec.status.value,
                    "start_time": node_exec.start_time.isoformat() if node_exec.start_time else None,
                    "duration": node_exec.duration,
                    "retry_count": node_exec.retry_count
                }
                for node_id, node_exec in execution.node_executions.items()
            }
        }
    
    async def _get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        if workflow_id in self._workflow_cache:
            return self._workflow_cache[workflow_id]
        
        workflow = await self.workflow_repository.get(workflow_id)
        if workflow:
            self._workflow_cache[workflow_id] = workflow
        
        return workflow
    
    async def _get_execution(self, execution_id: str) -> Optional[WorkflowExecution]:
        """获取执行实例"""
        if execution_id in self._execution_cache:
            return self._execution_cache[execution_id]
        
        execution = await self.execution_repository.get(execution_id)
        if execution:
            self._execution_cache[execution_id] = execution
        
        return execution
    
    async def _publish_execution_event(
        self,
        execution_id: str,
        event_type: ExecutionEventType,
        data: Dict[str, Any] = None
    ):
        """发布执行事件"""
        event = ExecutionEvent(
            execution_id=execution_id,
            event_type=event_type.value,
            data=data or {}
        )
        
        await self.event_bus.publish("workflow.execution.events", event)
    
    async def _publish_node_event(
        self,
        execution_id: str,
        node_id: str,
        event_type: ExecutionEventType,
        data: Dict[str, Any] = None
    ):
        """发布节点事件"""
        event = ExecutionEvent(
            execution_id=execution_id,
            node_id=node_id,
            event_type=event_type.value,
            data=data or {}
        )
        
        await self.event_bus.publish("workflow.node.events", event)
