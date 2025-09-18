"""
智能体运行时异常定义
"""
from typing import Optional, Dict, Any


class AgentRuntimeError(Exception):
    """智能体运行时基础异常"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details
        }


class AgentNotFoundError(AgentRuntimeError):
    """智能体未找到异常"""
    
    def __init__(self, agent_id: str):
        super().__init__(
            f"Agent not found: {agent_id}",
            {"agent_id": agent_id}
        )


class AgentValidationError(AgentRuntimeError):
    """智能体验证异常"""
    
    def __init__(self, message: str, validation_errors: Optional[list] = None):
        super().__init__(
            message,
            {"validation_errors": validation_errors or []}
        )


class AgentExecutionError(AgentRuntimeError):
    """智能体执行异常"""
    
    def __init__(self, message: str, agent_id: str, cause: Optional[Exception] = None):
        details = {"agent_id": agent_id}
        if cause:
            details["cause"] = str(cause)
            details["cause_type"] = type(cause).__name__
        
        super().__init__(message, details)


class AgentTimeoutError(AgentRuntimeError):
    """智能体超时异常"""
    
    def __init__(self, agent_id: str, timeout_seconds: int):
        super().__init__(
            f"Agent {agent_id} execution timeout after {timeout_seconds} seconds",
            {"agent_id": agent_id, "timeout_seconds": timeout_seconds}
        )


class AgentRateLimitError(AgentRuntimeError):
    """智能体速率限制异常"""
    
    def __init__(self, agent_id: str, limit_type: str, retry_after: Optional[int] = None):
        details = {
            "agent_id": agent_id,
            "limit_type": limit_type
        }
        if retry_after:
            details["retry_after_seconds"] = retry_after
        
        super().__init__(
            f"Agent {agent_id} rate limit exceeded: {limit_type}",
            details
        )


class AgentAuthenticationError(AgentRuntimeError):
    """智能体认证异常"""
    
    def __init__(self, message: str, required_permissions: Optional[list] = None):
        super().__init__(
            message,
            {"required_permissions": required_permissions or []}
        )


class AgentConfigError(AgentRuntimeError):
    """智能体配置异常"""
    
    def __init__(self, message: str, config_field: Optional[str] = None):
        details = {}
        if config_field:
            details["config_field"] = config_field
        
        super().__init__(message, details)


class SchemaValidationError(AgentRuntimeError):
    """Schema验证异常"""
    
    def __init__(self, message: str, schema_type: str, validation_errors: list):
        super().__init__(
            message,
            {
                "schema_type": schema_type,
                "validation_errors": validation_errors
            }
        )
