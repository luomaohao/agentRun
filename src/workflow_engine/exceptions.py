"""
工作流引擎异常定义
"""


class WorkflowEngineError(Exception):
    """工作流引擎基础异常"""
    pass


class WorkflowParseError(WorkflowEngineError):
    """工作流解析异常"""
    pass


class WorkflowValidationError(WorkflowEngineError):
    """工作流验证异常"""
    pass


class WorkflowExecutionError(WorkflowEngineError):
    """工作流执行异常"""
    pass


class NodeExecutionError(WorkflowExecutionError):
    """节点执行异常"""
    def __init__(self, node_id: str, message: str, cause: Exception = None):
        self.node_id = node_id
        self.cause = cause
        super().__init__(f"Node '{node_id}' execution failed: {message}")


class WorkflowTimeoutError(WorkflowExecutionError):
    """工作流超时异常"""
    pass


class WorkflowCancelledError(WorkflowExecutionError):
    """工作流取消异常"""
    pass


class ResourceAllocationError(WorkflowEngineError):
    """资源分配异常"""
    pass


class SchedulingError(WorkflowEngineError):
    """调度异常"""
    pass


class StateTransitionError(WorkflowEngineError):
    """状态转换异常"""
    def __init__(self, current_state: str, target_state: str, message: str = None):
        self.current_state = current_state
        self.target_state = target_state
        msg = f"Invalid state transition from '{current_state}' to '{target_state}'"
        if message:
            msg += f": {message}"
        super().__init__(msg)


class DependencyError(WorkflowExecutionError):
    """依赖错误"""
    def __init__(self, node_id: str, dependency: str, message: str = None):
        self.node_id = node_id
        self.dependency = dependency
        msg = f"Node '{node_id}' dependency '{dependency}' error"
        if message:
            msg += f": {message}"
        super().__init__(msg)


class ConcurrencyLimitError(ResourceAllocationError):
    """并发限制错误"""
    pass


class RetryExhaustedError(NodeExecutionError):
    """重试耗尽错误"""
    def __init__(self, node_id: str, retry_count: int, last_error: Exception = None):
        self.retry_count = retry_count
        super().__init__(
            node_id,
            f"Retry exhausted after {retry_count} attempts",
            last_error
        )
