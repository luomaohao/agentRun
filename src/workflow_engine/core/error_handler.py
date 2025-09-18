"""
错误处理与恢复机制
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable, Type
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import traceback

from ..models.workflow import Node, Workflow
from ..models.execution import WorkflowExecution, NodeExecution, NodeExecutionStatus
from ..exceptions import (
    NodeExecutionError, WorkflowTimeoutError, RetryExhaustedError,
    WorkflowExecutionError
)


logger = logging.getLogger(__name__)


class ErrorStrategy(Enum):
    """错误处理策略"""
    RETRY = "retry"              # 重试
    COMPENSATE = "compensate"    # 补偿
    SKIP = "skip"               # 跳过
    FAIL = "fail"               # 失败
    FALLBACK = "fallback"       # 降级
    ESCALATE = "escalate"       # 升级


class RetryStrategy(Enum):
    """重试策略"""
    FIXED_DELAY = "fixed_delay"           # 固定延迟
    EXPONENTIAL_BACKOFF = "exponential"   # 指数退避
    LINEAR_BACKOFF = "linear"             # 线性退避
    CUSTOM = "custom"                     # 自定义


@dataclass
class RetryPolicy:
    """重试策略"""
    max_retries: int = 3
    initial_delay: float = 1.0  # 秒
    max_delay: float = 60.0     # 秒
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    backoff_factor: float = 2.0
    jitter: bool = True         # 添加随机抖动
    retry_on: List[Type[Exception]] = field(default_factory=lambda: [Exception])
    exclude: List[Type[Exception]] = field(default_factory=list)


@dataclass
class CompensationAction:
    """补偿动作"""
    action_type: str            # 动作类型
    target: str                 # 目标（节点ID或服务）
    params: Dict[str, Any] = field(default_factory=dict)
    timeout: int = 300          # 超时时间（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorContext:
    """错误上下文"""
    error: Exception
    node: Node
    execution: WorkflowExecution
    node_execution: NodeExecution
    retry_count: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    traceback: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.traceback and self.error:
            self.traceback = traceback.format_exc()


class ErrorHandler:
    """错误处理器"""
    
    def __init__(self):
        self.error_strategies: Dict[str, Callable] = {}
        self.compensation_handlers: Dict[str, Callable] = {}
        self._register_default_strategies()
    
    def _register_default_strategies(self):
        """注册默认策略"""
        self.error_strategies[ErrorStrategy.RETRY.value] = self._handle_retry
        self.error_strategies[ErrorStrategy.COMPENSATE.value] = self._handle_compensate
        self.error_strategies[ErrorStrategy.SKIP.value] = self._handle_skip
        self.error_strategies[ErrorStrategy.FAIL.value] = self._handle_fail
        self.error_strategies[ErrorStrategy.FALLBACK.value] = self._handle_fallback
        self.error_strategies[ErrorStrategy.ESCALATE.value] = self._handle_escalate
    
    async def handle_error(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ) -> ErrorStrategy:
        """处理错误"""
        node = error_context.node
        error = error_context.error
        
        # 记录错误
        logger.error(
            f"Node {node.id} execution failed: {error}",
            exc_info=True,
            extra={
                "node_id": node.id,
                "execution_id": error_context.execution.id,
                "retry_count": error_context.retry_count
            }
        )
        
        # 确定错误处理策略
        strategy = self._determine_strategy(error_context, workflow)
        
        # 执行对应策略
        handler = self.error_strategies.get(strategy.value)
        if handler:
            await handler(error_context, workflow)
        else:
            logger.warning(f"No handler for strategy: {strategy}")
            await self._handle_fail(error_context, workflow)
        
        return strategy
    
    def _determine_strategy(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ) -> ErrorStrategy:
        """确定错误处理策略"""
        node = error_context.node
        error = error_context.error
        
        # 检查节点级别的重试策略
        if node.retry_policy and error_context.retry_count < node.retry_policy.get("max_retries", 0):
            # 检查是否应该重试此类错误
            if self._should_retry(error, node.retry_policy):
                return ErrorStrategy.RETRY
        
        # 检查工作流级别的错误处理器
        for handler in workflow.error_handlers:
            if self._matches_error_handler(handler, error_context):
                action = handler.get("action", {})
                strategy_type = action.get("type", "fail")
                
                try:
                    return ErrorStrategy(strategy_type)
                except ValueError:
                    logger.warning(f"Unknown strategy type: {strategy_type}")
        
        # 特定错误类型的默认策略
        if isinstance(error, WorkflowTimeoutError):
            return ErrorStrategy.FAIL
        elif isinstance(error, RetryExhaustedError):
            return ErrorStrategy.COMPENSATE
        
        # 默认策略
        return ErrorStrategy.FAIL
    
    def _should_retry(self, error: Exception, retry_policy: Dict[str, Any]) -> bool:
        """判断是否应该重试"""
        # 检查排除列表
        exclude_errors = retry_policy.get("exclude_errors", [])
        for exclude_type in exclude_errors:
            if isinstance(error, eval(exclude_type)):  # 简化实现
                return False
        
        # 检查包含列表
        retry_on = retry_policy.get("retry_on", [])
        if retry_on:
            for retry_type in retry_on:
                if isinstance(error, eval(retry_type)):
                    return True
            return False
        
        # 默认重试所有错误
        return True
    
    def _matches_error_handler(
        self,
        handler: Dict[str, Any],
        error_context: ErrorContext
    ) -> bool:
        """检查错误处理器是否匹配"""
        # 检查节点模式
        node_pattern = handler.get("node_pattern", ".*")
        if node_pattern != ".*":
            import re
            if not re.match(node_pattern, error_context.node.id):
                return False
        
        # 检查错误类型
        error_type = handler.get("error_type")
        if error_type:
            if error_type == "timeout" and isinstance(error_context.error, WorkflowTimeoutError):
                return True
            elif error_type == "execution_error" and isinstance(error_context.error, NodeExecutionError):
                return True
            elif error_type == type(error_context.error).__name__:
                return True
            else:
                return False
        
        return True
    
    async def _handle_retry(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理重试"""
        node = error_context.node
        retry_policy = node.retry_policy or {}
        
        # 计算重试延迟
        delay = self._calculate_retry_delay(
            error_context.retry_count,
            retry_policy
        )
        
        logger.info(
            f"Retrying node {node.id} after {delay}s "
            f"(attempt {error_context.retry_count + 1})"
        )
        
        # 更新节点执行状态
        error_context.node_execution.status = NodeExecutionStatus.RETRYING
        error_context.node_execution.retry_count = error_context.retry_count + 1
        
        # 等待延迟
        if delay > 0:
            await asyncio.sleep(delay)
    
    def _calculate_retry_delay(
        self,
        retry_count: int,
        retry_policy: Dict[str, Any]
    ) -> float:
        """计算重试延迟"""
        initial_delay = retry_policy.get("retry_delay", 1.0)
        max_delay = retry_policy.get("max_delay", 60.0)
        backoff_factor = retry_policy.get("backoff_factor", 2.0)
        strategy = retry_policy.get("strategy", "exponential")
        
        if strategy == "fixed":
            delay = initial_delay
        elif strategy == "linear":
            delay = initial_delay * (retry_count + 1)
        else:  # exponential
            delay = initial_delay * (backoff_factor ** retry_count)
        
        # 限制最大延迟
        delay = min(delay, max_delay)
        
        # 添加抖动
        if retry_policy.get("jitter", True):
            import random
            jitter = random.uniform(0, delay * 0.1)
            delay += jitter
        
        return delay
    
    async def _handle_compensate(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理补偿"""
        logger.info(f"Starting compensation for node {error_context.node.id}")
        
        # 查找补偿动作
        compensation_actions = self._find_compensation_actions(
            error_context,
            workflow
        )
        
        # 执行补偿动作
        for action in compensation_actions:
            try:
                await self._execute_compensation_action(action, error_context)
            except Exception as e:
                logger.error(
                    f"Compensation action failed: {e}",
                    exc_info=True
                )
        
        # 更新执行状态
        error_context.execution.status = ExecutionStatus.COMPENSATING
    
    def _find_compensation_actions(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ) -> List[CompensationAction]:
        """查找补偿动作"""
        actions = []
        
        # 从节点配置查找
        node_compensation = error_context.node.metadata.get("compensation", {})
        if node_compensation:
            action = CompensationAction(
                action_type=node_compensation.get("type", "rollback"),
                target=node_compensation.get("target", error_context.node.id),
                params=node_compensation.get("params", {}),
                timeout=node_compensation.get("timeout", 300)
            )
            actions.append(action)
        
        # 从工作流错误处理器查找
        for handler in workflow.error_handlers:
            if self._matches_error_handler(handler, error_context):
                action_config = handler.get("action", {})
                if action_config.get("type") == "compensate":
                    compensation = action_config.get("compensation", {})
                    if compensation:
                        action = CompensationAction(
                            action_type=compensation.get("type", "rollback"),
                            target=compensation.get("target", ""),
                            params=compensation.get("params", {}),
                            timeout=compensation.get("timeout", 300)
                        )
                        actions.append(action)
        
        return actions
    
    async def _execute_compensation_action(
        self,
        action: CompensationAction,
        error_context: ErrorContext
    ):
        """执行补偿动作"""
        handler = self.compensation_handlers.get(action.action_type)
        
        if handler:
            await handler(action, error_context)
        else:
            logger.warning(f"No handler for compensation action: {action.action_type}")
    
    async def _handle_skip(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理跳过"""
        logger.info(f"Skipping failed node {error_context.node.id}")
        
        # 更新节点状态
        error_context.node_execution.status = NodeExecutionStatus.SKIPPED
        error_context.node_execution.error_info = {
            "skipped": True,
            "reason": str(error_context.error)
        }
    
    async def _handle_fail(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理失败"""
        logger.error(f"Node {error_context.node.id} failed permanently")
        
        # 更新节点状态
        error_context.node_execution.fail(error_context.error)
        
        # 标记工作流失败
        error_context.execution.fail(
            f"Node {error_context.node.id} failed: {str(error_context.error)}"
        )
    
    async def _handle_fallback(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理降级"""
        logger.info(f"Falling back for node {error_context.node.id}")
        
        # 查找降级目标
        fallback_target = None
        for handler in workflow.error_handlers:
            if self._matches_error_handler(handler, error_context):
                action = handler.get("action", {})
                if action.get("type") == "fallback":
                    fallback_target = action.get("target")
                    break
        
        if fallback_target:
            # TODO: 实现降级到备用节点的逻辑
            logger.info(f"Falling back to node: {fallback_target}")
        else:
            # 没有降级目标，转为失败处理
            await self._handle_fail(error_context, workflow)
    
    async def _handle_escalate(
        self,
        error_context: ErrorContext,
        workflow: Workflow
    ):
        """处理升级"""
        logger.warning(f"Escalating error for node {error_context.node.id}")
        
        # TODO: 实现错误升级逻辑（如通知管理员、触发告警等）
        
        # 暂时转为失败处理
        await self._handle_fail(error_context, workflow)
    
    def register_compensation_handler(
        self,
        action_type: str,
        handler: Callable
    ):
        """注册补偿处理器"""
        self.compensation_handlers[action_type] = handler


class CircuitBreaker:
    """熔断器"""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Type[Exception] = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # closed, open, half-open
    
    async def call(self, func: Callable, *args, **kwargs):
        """通过熔断器调用函数"""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half-open"
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """检查是否应该尝试重置"""
        if self.last_failure_time:
            time_since_failure = (datetime.utcnow() - self.last_failure_time).seconds
            return time_since_failure >= self.recovery_timeout
        return False
    
    def _on_success(self):
        """成功调用"""
        self.failure_count = 0
        self.state = "closed"
    
    def _on_failure(self):
        """失败调用"""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
