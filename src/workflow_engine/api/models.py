"""
API 请求和响应模型
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum

from ..models.workflow import WorkflowType, NodeType
from ..models.execution import ExecutionStatus, NodeExecutionStatus


class WorkflowTypeEnum(str, Enum):
    """工作流类型枚举（API）"""
    DAG = "dag"
    STATE_MACHINE = "state_machine"
    HYBRID = "hybrid"


class NodeTypeEnum(str, Enum):
    """节点类型枚举（API）"""
    AGENT = "agent"
    TOOL = "tool"
    CONTROL = "control"
    AGGREGATION = "aggregation"
    SUB_WORKFLOW = "sub_workflow"


class ExecutionStatusEnum(str, Enum):
    """执行状态枚举（API）"""
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATING = "compensating"


# 工作流相关模型

class NodeDefinition(BaseModel):
    """节点定义"""
    id: str = Field(..., description="节点ID")
    name: str = Field(..., description="节点名称")
    type: NodeTypeEnum = Field(..., description="节点类型")
    subtype: Optional[str] = Field(None, description="节点子类型")
    config: Dict[str, Any] = Field(default_factory=dict, description="节点配置")
    inputs: Dict[str, str] = Field(default_factory=dict, description="输入映射")
    outputs: List[str] = Field(default_factory=list, description="输出字段")
    dependencies: List[str] = Field(default_factory=list, description="依赖节点ID")
    timeout: Optional[int] = Field(None, description="超时时间（秒）")
    retry_policy: Optional[Dict[str, Any]] = Field(None, description="重试策略")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class EdgeDefinition(BaseModel):
    """边定义"""
    source: str = Field(..., description="源节点ID")
    target: str = Field(..., description="目标节点ID")
    condition: Optional[str] = Field(None, description="条件表达式")
    data_mapping: Dict[str, str] = Field(default_factory=dict, description="数据映射")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    name: str = Field(..., description="工作流名称")
    version: str = Field("1.0.0", description="版本号")
    type: WorkflowTypeEnum = Field(WorkflowTypeEnum.DAG, description="工作流类型")
    description: Optional[str] = Field(None, description="描述")
    nodes: List[NodeDefinition] = Field(..., description="节点列表")
    edges: Optional[List[EdgeDefinition]] = Field(None, description="边列表")
    variables: Dict[str, Any] = Field(default_factory=dict, description="工作流变量")
    triggers: List[Dict[str, Any]] = Field(default_factory=list, description="触发器配置")
    error_handlers: List[Dict[str, Any]] = Field(default_factory=list, description="错误处理器")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class WorkflowUpdateRequest(BaseModel):
    """更新工作流请求"""
    description: Optional[str] = Field(None, description="描述")
    is_active: Optional[bool] = Field(None, description="是否激活")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")


class WorkflowResponse(BaseModel):
    """工作流响应"""
    id: str = Field(..., description="工作流ID")
    name: str = Field(..., description="工作流名称")
    version: str = Field(..., description="版本号")
    type: WorkflowTypeEnum = Field(..., description="工作流类型")
    description: Optional[str] = Field(None, description="描述")
    is_active: bool = Field(True, description="是否激活")
    node_count: int = Field(..., description="节点数量")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")
    
    model_config = ConfigDict(from_attributes=True)


class WorkflowDetailResponse(WorkflowResponse):
    """工作流详情响应"""
    nodes: List[NodeDefinition] = Field(..., description="节点列表")
    edges: List[EdgeDefinition] = Field(..., description="边列表")
    variables: Dict[str, Any] = Field(default_factory=dict, description="工作流变量")
    triggers: List[Dict[str, Any]] = Field(default_factory=list, description="触发器配置")
    error_handlers: List[Dict[str, Any]] = Field(default_factory=list, description="错误处理器")


# 执行相关模型

class WorkflowExecuteRequest(BaseModel):
    """执行工作流请求"""
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")
    async_mode: bool = Field(True, description="是否异步执行")
    priority: int = Field(0, description="优先级")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class NodeExecutionInfo(BaseModel):
    """节点执行信息"""
    node_id: str = Field(..., description="节点ID")
    status: str = Field(..., description="执行状态")
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    duration_ms: Optional[int] = Field(None, description="执行时长（毫秒）")
    retry_count: int = Field(0, description="重试次数")
    error_info: Optional[Dict[str, Any]] = Field(None, description="错误信息")
    
    model_config = ConfigDict(from_attributes=True)


class ExecutionResponse(BaseModel):
    """执行响应"""
    execution_id: str = Field(..., description="执行ID")
    workflow_id: str = Field(..., description="工作流ID")
    status: ExecutionStatusEnum = Field(..., description="执行状态")
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    duration_ms: Optional[int] = Field(None, description="执行时长（毫秒）")
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    
    model_config = ConfigDict(from_attributes=True)


class ExecutionDetailResponse(ExecutionResponse):
    """执行详情响应"""
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    output_data: Optional[Dict[str, Any]] = Field(None, description="输出数据")
    node_executions: List[NodeExecutionInfo] = Field(default_factory=list, description="节点执行信息")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


# 状态机相关模型

class StateTransitionRequest(BaseModel):
    """状态转换请求"""
    event: str = Field(..., description="事件名称")
    event_data: Dict[str, Any] = Field(default_factory=dict, description="事件数据")


class StateMachineInstanceResponse(BaseModel):
    """状态机实例响应"""
    instance_id: str = Field(..., description="实例ID")
    workflow_id: str = Field(..., description="工作流ID")
    current_state: str = Field(..., description="当前状态")
    is_final: bool = Field(..., description="是否终态")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


# 通用模型

class ErrorResponse(BaseModel):
    """错误响应"""
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误信息")
    details: Optional[Dict[str, Any]] = Field(None, description="错误详情")
    request_id: Optional[str] = Field(None, description="请求ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="时间戳")


class SuccessResponse(BaseModel):
    """成功响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field(..., description="消息")
    data: Optional[Dict[str, Any]] = Field(None, description="额外数据")


class PaginationParams(BaseModel):
    """分页参数"""
    offset: int = Field(0, ge=0, description="偏移量")
    limit: int = Field(20, ge=1, le=100, description="每页数量")


class PaginatedResponse(BaseModel):
    """分页响应"""
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")
    items: List[Any] = Field(..., description="数据项")


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="健康状态", examples=["healthy", "unhealthy"])
    version: str = Field(..., description="版本号")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="时间戳")
    checks: Dict[str, bool] = Field(default_factory=dict, description="各组件检查结果")


class MetricsResponse(BaseModel):
    """指标响应"""
    active_workflows: int = Field(..., description="活跃工作流数")
    total_executions: int = Field(..., description="总执行数")
    running_executions: int = Field(..., description="运行中执行数")
    failed_executions_24h: int = Field(..., description="24小时内失败数")
    avg_execution_time_ms: float = Field(..., description="平均执行时间（毫秒）")
    resource_usage: Dict[str, Any] = Field(default_factory=dict, description="资源使用情况")
