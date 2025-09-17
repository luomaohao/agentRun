"""
工具注册表集成
"""
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import inspect
import logging


logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    tool_id: str
    name: str
    description: str
    parameters_schema: Dict[str, Any]
    response_schema: Dict[str, Any]
    permissions: List[str] = field(default_factory=list)
    rate_limit: Optional[int] = None  # 每分钟调用次数限制
    timeout: int = 30  # 超时时间（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResponse:
    """工具响应"""
    result: Any
    duration_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ToolRegistry(ABC):
    """工具注册表接口"""
    
    @abstractmethod
    async def register_tool(self, tool_def: ToolDefinition, handler: Callable):
        """注册工具"""
        pass
    
    @abstractmethod
    async def unregister_tool(self, tool_id: str):
        """注销工具"""
        pass
    
    @abstractmethod
    async def get_tool(self, tool_id: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        pass
    
    @abstractmethod
    async def list_tools(self) -> List[ToolDefinition]:
        """列出所有工具"""
        pass
    
    @abstractmethod
    async def invoke_tool(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Any:
        """调用工具"""
        pass
    
    @abstractmethod
    async def validate_parameters(
        self,
        tool_id: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """验证参数"""
        pass


class LocalToolRegistry(ToolRegistry):
    """本地工具注册表实现"""
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.handlers: Dict[str, Callable] = {}
        self._rate_limiters: Dict[str, Any] = {}  # 简化的速率限制器
    
    async def register_tool(self, tool_def: ToolDefinition, handler: Callable):
        """注册工具"""
        if not callable(handler):
            raise ValueError(f"Handler for tool {tool_def.tool_id} must be callable")
        
        self.tools[tool_def.tool_id] = tool_def
        self.handlers[tool_def.tool_id] = handler
        
        logger.info(f"Registered tool: {tool_def.tool_id}")
    
    async def unregister_tool(self, tool_id: str):
        """注销工具"""
        if tool_id in self.tools:
            del self.tools[tool_id]
            del self.handlers[tool_id]
            logger.info(f"Unregistered tool: {tool_id}")
    
    async def get_tool(self, tool_id: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self.tools.get(tool_id)
    
    async def list_tools(self) -> List[ToolDefinition]:
        """列出所有工具"""
        return list(self.tools.values())
    
    async def invoke_tool(
        self,
        tool_id: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any] = None
    ) -> Any:
        """调用工具"""
        # 获取工具定义和处理器
        tool_def = self.tools.get(tool_id)
        handler = self.handlers.get(tool_id)
        
        if not tool_def or not handler:
            raise ValueError(f"Tool not found: {tool_id}")
        
        # 验证参数
        errors = await self.validate_parameters(tool_id, parameters)
        if errors:
            raise ValueError(f"Invalid parameters for tool {tool_id}: {errors}")
        
        # 检查权限（简化实现）
        # TODO: 实现基于上下文的权限检查
        
        # 检查速率限制
        # TODO: 实现速率限制
        
        # 调用工具
        import time
        start_time = time.time()
        
        try:
            if inspect.iscoroutinefunction(handler):
                result = await handler(parameters, context)
            else:
                result = handler(parameters, context)
            
            duration_ms = (time.time() - start_time) * 1000
            
            logger.info(f"Tool {tool_id} invoked successfully in {duration_ms:.2f}ms")
            
            return result
            
        except Exception as e:
            logger.error(f"Tool {tool_id} invocation failed: {e}", exc_info=True)
            raise
    
    async def validate_parameters(
        self,
        tool_id: str,
        parameters: Dict[str, Any]
    ) -> List[str]:
        """验证参数"""
        errors = []
        tool_def = self.tools.get(tool_id)
        
        if not tool_def:
            errors.append(f"Tool not found: {tool_id}")
            return errors
        
        schema = tool_def.parameters_schema
        if not schema:
            return errors
        
        # 简单的必填字段验证
        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})
        
        for field in required_fields:
            if field not in parameters:
                errors.append(f"Missing required parameter: {field}")
        
        # 类型验证
        for field, value in parameters.items():
            if field in properties:
                field_schema = properties[field]
                expected_type = field_schema.get("type")
                
                if expected_type:
                    if expected_type == "string" and not isinstance(value, str):
                        errors.append(f"Parameter {field} must be a string")
                    elif expected_type == "number" and not isinstance(value, (int, float)):
                        errors.append(f"Parameter {field} must be a number")
                    elif expected_type == "boolean" and not isinstance(value, bool):
                        errors.append(f"Parameter {field} must be a boolean")
                    elif expected_type == "array" and not isinstance(value, list):
                        errors.append(f"Parameter {field} must be an array")
                    elif expected_type == "object" and not isinstance(value, dict):
                        errors.append(f"Parameter {field} must be an object")
        
        return errors


# 预定义的工具集
class BuiltinTools:
    """内置工具集"""
    
    @staticmethod
    def create_http_tool() -> tuple[ToolDefinition, Callable]:
        """创建HTTP工具"""
        tool_def = ToolDefinition(
            tool_id="http_request",
            name="HTTP Request",
            description="Make HTTP requests",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                    "headers": {"type": "object"},
                    "body": {"type": "object"}
                },
                "required": ["url", "method"]
            },
            response_schema={
                "type": "object",
                "properties": {
                    "status_code": {"type": "number"},
                    "headers": {"type": "object"},
                    "body": {"type": "object"}
                }
            },
            timeout=30
        )
        
        async def handler(params: Dict[str, Any], context: Dict[str, Any] = None):
            # TODO: 实现HTTP请求逻辑
            return {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "body": {"message": "Mock response"}
            }
        
        return tool_def, handler
    
    @staticmethod
    def create_database_tool() -> tuple[ToolDefinition, Callable]:
        """创建数据库工具"""
        tool_def = ToolDefinition(
            tool_id="database_query",
            name="Database Query",
            description="Execute database queries",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "parameters": {"type": "array"},
                    "database": {"type": "string"}
                },
                "required": ["query"]
            },
            response_schema={
                "type": "object",
                "properties": {
                    "rows": {"type": "array"},
                    "row_count": {"type": "number"}
                }
            },
            permissions=["database:read"],
            timeout=60
        )
        
        async def handler(params: Dict[str, Any], context: Dict[str, Any] = None):
            # TODO: 实现数据库查询逻辑
            return {
                "rows": [],
                "row_count": 0
            }
        
        return tool_def, handler
    
    @staticmethod
    def create_email_tool() -> tuple[ToolDefinition, Callable]:
        """创建邮件工具"""
        tool_def = ToolDefinition(
            tool_id="send_email",
            name="Send Email",
            description="Send email notifications",
            parameters_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "attachments": {"type": "array"}
                },
                "required": ["to", "subject", "body"]
            },
            response_schema={
                "type": "object",
                "properties": {
                    "message_id": {"type": "string"},
                    "status": {"type": "string"}
                }
            },
            permissions=["email:send"],
            rate_limit=100
        )
        
        async def handler(params: Dict[str, Any], context: Dict[str, Any] = None):
            # TODO: 实现邮件发送逻辑
            return {
                "message_id": "mock-message-id",
                "status": "sent"
            }
        
        return tool_def, handler
    
    @staticmethod
    async def register_all(registry: ToolRegistry):
        """注册所有内置工具"""
        # HTTP工具
        http_tool, http_handler = BuiltinTools.create_http_tool()
        await registry.register_tool(http_tool, http_handler)
        
        # 数据库工具
        db_tool, db_handler = BuiltinTools.create_database_tool()
        await registry.register_tool(db_tool, db_handler)
        
        # 邮件工具
        email_tool, email_handler = BuiltinTools.create_email_tool()
        await registry.register_tool(email_tool, email_handler)
