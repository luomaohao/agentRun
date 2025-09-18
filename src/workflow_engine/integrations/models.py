"""
智能体相关的数据模型定义
"""
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator
import uuid


class AgentStatus(Enum):
    """智能体状态枚举"""
    IDLE = "idle"
    PROCESSING = "processing"
    ERROR = "error"
    DISABLED = "disabled"
    MAINTENANCE = "maintenance"


class SchemaType(BaseModel):
    """JSON Schema类型定义"""
    type: str
    properties: Optional[Dict[str, Any]] = None
    required: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None
    additionalProperties: Optional[bool] = True
    
    class Config:
        extra = "allow"


@dataclass
class AgentConfig:
    """智能体配置 - 增强版"""
    agent_id: str
    name: str
    description: str
    meta_prompt: str
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 2000
    
    # Schema定义
    input_schema: Optional[Union[Dict[str, Any], SchemaType]] = None
    output_schema: Optional[Union[Dict[str, Any], SchemaType]] = None
    
    # 扩展属性
    version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # 能力定义
    tools: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    
    # 限制和配置
    timeout_seconds: int = 300
    max_retries: int = 3
    rate_limit: Optional[Dict[str, int]] = None  # e.g., {"requests_per_minute": 60}
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 认证和权限
    required_permissions: List[str] = field(default_factory=list)
    api_keys: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        """后初始化处理"""
        if not self.agent_id:
            self.agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        
        # 转换schema为Pydantic模型
        if isinstance(self.input_schema, dict) and not isinstance(self.input_schema, SchemaType):
            self.input_schema = SchemaType(**self.input_schema)
        if isinstance(self.output_schema, dict) and not isinstance(self.output_schema, SchemaType):
            self.output_schema = SchemaType(**self.output_schema)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "meta_prompt": self.meta_prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "input_schema": self.input_schema.dict() if isinstance(self.input_schema, SchemaType) else self.input_schema,
            "output_schema": self.output_schema.dict() if isinstance(self.output_schema, SchemaType) else self.output_schema,
            "version": self.version,
            "tags": self.tags,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "tools": self.tools,
            "capabilities": self.capabilities,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "rate_limit": self.rate_limit,
            "metadata": self.metadata,
            "required_permissions": self.required_permissions
        }


@dataclass
class AgentResponse:
    """智能体响应 - 增强版"""
    agent_id: str
    output: Dict[str, Any]
    status: str  # success, error, timeout, rate_limited
    duration_ms: float
    
    # 可选字段
    raw_response: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 资源使用统计
    token_usage: Optional[Dict[str, int]] = None  # {prompt_tokens, completion_tokens, total_tokens}
    api_calls: Optional[int] = None
    
    # 调试信息
    debug_info: Optional[Dict[str, Any]] = None
    context_used: Optional[Dict[str, Any]] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "agent_id": self.agent_id,
            "output": self.output,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat()
        }
        
        # 添加可选字段
        if self.raw_response:
            result["raw_response"] = self.raw_response
        if self.error:
            result["error"] = self.error
            result["error_type"] = self.error_type
        if self.token_usage:
            result["token_usage"] = self.token_usage
        if self.api_calls:
            result["api_calls"] = self.api_calls
        if self.debug_info:
            result["debug_info"] = self.debug_info
        if self.context_used:
            result["context_used"] = self.context_used
        if self.metadata:
            result["metadata"] = self.metadata
        
        return result
    
    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.status == "success"
    
    @property
    def is_error(self) -> bool:
        """是否错误"""
        return self.status == "error"


@dataclass
class BatchRequest:
    """批量请求"""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str = ""
    requests: List[Dict[str, Any]] = field(default_factory=list)
    context: Optional[Dict[str, Any]] = None
    parallel: bool = True
    timeout_seconds: Optional[int] = None
    
    def add_request(self, input_data: Dict[str, Any]):
        """添加请求"""
        self.requests.append(input_data)


@dataclass
class BatchResponse:
    """批量响应"""
    request_id: str
    responses: List[AgentResponse]
    total_duration_ms: float
    success_count: int = 0
    error_count: int = 0
    
    def __post_init__(self):
        """计算统计信息"""
        self.success_count = sum(1 for r in self.responses if r.is_success)
        self.error_count = sum(1 for r in self.responses if r.is_error)
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        total = len(self.responses)
        return self.success_count / total if total > 0 else 0.0


class AgentPermission(BaseModel):
    """智能体权限定义"""
    permission_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    description: str
    resource: str
    actions: List[str]
    
    class Config:
        schema_extra = {
            "example": {
                "name": "read_user_data",
                "description": "允许读取用户数据",
                "resource": "user_data",
                "actions": ["read", "list"]
            }
        }


class AgentSession(BaseModel):
    """智能体会话"""
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str
    user_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    context: Dict[str, Any] = Field(default_factory=dict)
    history: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    def add_interaction(self, input_data: Dict[str, Any], response: AgentResponse):
        """添加交互记录"""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "input": input_data,
            "output": response.output,
            "status": response.status,
            "duration_ms": response.duration_ms
        })
        self.updated_at = datetime.now()
