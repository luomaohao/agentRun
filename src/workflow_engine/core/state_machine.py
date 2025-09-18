"""
状态机服务实现
"""
import asyncio
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass, field
from uuid import uuid4
import logging

from ..models.workflow import StateMachineWorkflow, StateDefinition
from ..models.execution import (
    WorkflowExecution, ExecutionContext, ExecutionStatus,
    ExecutionEvent, ExecutionEventType
)
from ..exceptions import StateTransitionError, WorkflowExecutionError
from ..integrations.event_bus import EventBus


logger = logging.getLogger(__name__)


@dataclass
class StateTransition:
    """状态转换"""
    from_state: str
    to_state: str
    event: str
    condition: Optional[str] = None
    actions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StateMachineInstance:
    """状态机实例"""
    instance_id: str
    workflow_id: str
    current_state: str
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_history(self, event: str, from_state: str, to_state: str):
        """添加历史记录"""
        self.history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "from_state": from_state,
            "to_state": to_state
        })
        self.updated_at = datetime.utcnow()


class ActionExecutor:
    """动作执行器"""
    
    def __init__(self):
        self.action_handlers: Dict[str, Callable] = {}
    
    def register_action(self, action_type: str, handler: Callable):
        """注册动作处理器"""
        self.action_handlers[action_type] = handler
    
    async def execute_action(
        self,
        action: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Any:
        """执行动作"""
        action_type = action.get("type")
        if not action_type:
            raise ValueError("Action must have a type")
        
        handler = self.action_handlers.get(action_type)
        if not handler:
            raise ValueError(f"No handler for action type: {action_type}")
        
        params = action.get("params", {})
        
        if asyncio.iscoroutinefunction(handler):
            return await handler(params, context)
        else:
            return handler(params, context)


class ConditionEvaluator:
    """条件评估器"""
    
    async def evaluate(
        self,
        condition: str,
        context: Dict[str, Any]
    ) -> bool:
        """评估条件"""
        if not condition:
            return True
        
        # 简单的条件评估实现
        # 支持格式: "variable == value", "variable > value" 等
        try:
            # 替换变量
            for key, value in context.items():
                condition = condition.replace(f"${{{key}}}", str(value))
            
            # 评估表达式（注意：生产环境应使用更安全的方式）
            result = eval(condition, {"__builtins__": {}}, context)
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to evaluate condition '{condition}': {e}")
            return False


class StateMachineEngine:
    """状态机引擎"""
    
    def __init__(self, event_bus: EventBus = None):
        self.event_bus = event_bus or EventBus()
        self.workflows: Dict[str, StateMachineWorkflow] = {}
        self.instances: Dict[str, StateMachineInstance] = {}
        self.action_executor = ActionExecutor()
        self.condition_evaluator = ConditionEvaluator()
        
        # 注册默认动作
        self._register_default_actions()
    
    def _register_default_actions(self):
        """注册默认动作"""
        # 日志动作
        async def log_action(params: Dict[str, Any], context: Dict[str, Any]):
            message = params.get("message", "")
            level = params.get("level", "info")
            getattr(logger, level)(f"State machine action: {message}")
        
        self.action_executor.register_action("log", log_action)
        
        # 设置变量动作
        async def set_variable_action(params: Dict[str, Any], context: Dict[str, Any]):
            var_name = params.get("name")
            var_value = params.get("value")
            if var_name:
                context[var_name] = var_value
        
        self.action_executor.register_action("set_variable", set_variable_action)
        
        # 发布事件动作
        async def publish_event_action(params: Dict[str, Any], context: Dict[str, Any]):
            topic = params.get("topic")
            payload = params.get("payload", {})
            if topic:
                await self.event_bus.publish(topic, payload)
        
        self.action_executor.register_action("publish_event", publish_event_action)
    
    async def register_workflow(self, workflow: StateMachineWorkflow):
        """注册状态机工作流"""
        self.workflows[workflow.id] = workflow
        logger.info(f"Registered state machine workflow: {workflow.id}")
    
    async def create_instance(
        self,
        workflow_id: str,
        instance_id: str = None,
        initial_context: Dict[str, Any] = None
    ) -> StateMachineInstance:
        """创建状态机实例"""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            raise WorkflowExecutionError(f"Workflow not found: {workflow_id}")
        
        instance = StateMachineInstance(
            instance_id=instance_id or str(uuid4()),
            workflow_id=workflow_id,
            current_state=workflow.initial_state,
            context=initial_context or {}
        )
        
        self.instances[instance.instance_id] = instance
        
        # 执行初始状态的进入动作
        initial_state = self._get_state(workflow, workflow.initial_state)
        if initial_state and initial_state.on_enter:
            await self._execute_actions(initial_state.on_enter, instance.context)
        
        logger.info(f"Created state machine instance: {instance.instance_id}")
        return instance
    
    async def process_event(
        self,
        instance_id: str,
        event: str,
        event_data: Dict[str, Any] = None
    ) -> bool:
        """处理事件"""
        instance = self.instances.get(instance_id)
        if not instance:
            raise WorkflowExecutionError(f"Instance not found: {instance_id}")
        
        workflow = self.workflows.get(instance.workflow_id)
        if not workflow:
            raise WorkflowExecutionError(f"Workflow not found: {instance.workflow_id}")
        
        # 获取当前状态
        current_state = self._get_state(workflow, instance.current_state)
        if not current_state:
            raise StateTransitionError(
                instance.current_state,
                "unknown",
                f"Current state not found: {instance.current_state}"
            )
        
        # 更新上下文
        if event_data:
            instance.context.update(event_data)
        
        # 查找匹配的转换
        transition = await self._find_transition(
            current_state,
            event,
            instance.context
        )
        
        if not transition:
            logger.warning(
                f"No transition found for event '{event}' in state '{instance.current_state}'"
            )
            return False
        
        # 执行转换
        await self._execute_transition(
            instance,
            workflow,
            current_state,
            transition
        )
        
        return True
    
    async def _find_transition(
        self,
        state: StateDefinition,
        event: str,
        context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """查找匹配的转换"""
        for transition in state.transitions:
            if transition.get("event") == event:
                # 评估条件
                condition = transition.get("condition")
                if condition:
                    if not await self.condition_evaluator.evaluate(condition, context):
                        continue
                
                return transition
        
        return None
    
    async def _execute_transition(
        self,
        instance: StateMachineInstance,
        workflow: StateMachineWorkflow,
        current_state: StateDefinition,
        transition: Dict[str, Any]
    ):
        """执行状态转换"""
        target_state_name = transition.get("target")
        if not target_state_name:
            raise StateTransitionError(
                current_state.name,
                "unknown",
                "Transition has no target state"
            )
        
        target_state = self._get_state(workflow, target_state_name)
        if not target_state:
            raise StateTransitionError(
                current_state.name,
                target_state_name,
                f"Target state not found: {target_state_name}"
            )
        
        logger.info(
            f"Executing transition: {current_state.name} -> {target_state_name} "
            f"(event: {transition.get('event')})"
        )
        
        try:
            # 执行当前状态的退出动作
            if current_state.on_exit:
                await self._execute_actions(current_state.on_exit, instance.context)
            
            # 执行转换动作
            transition_actions = transition.get("actions", [])
            if transition_actions:
                await self._execute_actions(transition_actions, instance.context)
            
            # 更新状态
            old_state = instance.current_state
            instance.current_state = target_state_name
            instance.add_history(
                transition.get("event"),
                old_state,
                target_state_name
            )
            
            # 执行目标状态的进入动作
            if target_state.on_enter:
                await self._execute_actions(target_state.on_enter, instance.context)
            
            # 发布状态变更事件
            await self.event_bus.publish(
                "statemachine.state_changed",
                {
                    "instance_id": instance.instance_id,
                    "workflow_id": instance.workflow_id,
                    "from_state": old_state,
                    "to_state": target_state_name,
                    "event": transition.get("event")
                }
            )
            
            # 检查是否到达终态
            if target_state_name in workflow.final_states:
                await self._handle_final_state(instance)
            
        except Exception as e:
            logger.error(
                f"Failed to execute transition from {current_state.name} "
                f"to {target_state_name}: {e}",
                exc_info=True
            )
            raise
    
    async def _execute_actions(
        self,
        actions: List[Dict[str, Any]],
        context: Dict[str, Any]
    ):
        """执行动作列表"""
        for action in actions:
            try:
                await self.action_executor.execute_action(action, context)
            except Exception as e:
                logger.error(f"Failed to execute action {action}: {e}", exc_info=True)
                # 根据配置决定是否继续执行
                if action.get("required", True):
                    raise
    
    async def _handle_final_state(self, instance: StateMachineInstance):
        """处理终态"""
        logger.info(
            f"State machine instance {instance.instance_id} "
            f"reached final state: {instance.current_state}"
        )
        
        # 发布完成事件
        await self.event_bus.publish(
            "statemachine.completed",
            {
                "instance_id": instance.instance_id,
                "workflow_id": instance.workflow_id,
                "final_state": instance.current_state,
                "context": instance.context
            }
        )
    
    def _get_state(
        self,
        workflow: StateMachineWorkflow,
        state_name: str
    ) -> Optional[StateDefinition]:
        """获取状态定义"""
        for state in workflow.states:
            if state.name == state_name:
                return state
        return None
    
    async def get_instance(self, instance_id: str) -> Optional[StateMachineInstance]:
        """获取状态机实例"""
        return self.instances.get(instance_id)
    
    async def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """获取实例状态"""
        instance = self.instances.get(instance_id)
        if not instance:
            return None
        
        workflow = self.workflows.get(instance.workflow_id)
        is_final = False
        if workflow and instance.current_state in workflow.final_states:
            is_final = True
        
        return {
            "instance_id": instance.instance_id,
            "workflow_id": instance.workflow_id,
            "current_state": instance.current_state,
            "is_final": is_final,
            "context": instance.context,
            "history": instance.history,
            "created_at": instance.created_at.isoformat(),
            "updated_at": instance.updated_at.isoformat()
        }
    
    def register_action_handler(self, action_type: str, handler: Callable):
        """注册自定义动作处理器"""
        self.action_executor.register_action(action_type, handler)
