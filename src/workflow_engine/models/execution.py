"""
工作流执行模型
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
from uuid import uuid4


class ExecutionStatus(Enum):
    """工作流执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPENSATING = "compensating"


class NodeExecutionStatus(Enum):
    """节点执行状态"""
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class ExecutionContext:
    """执行上下文"""
    workflow_id: str
    execution_id: str
    variables: Dict[str, Any] = field(default_factory=dict)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_context: Optional['ExecutionContext'] = None
    
    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取变量值"""
        if key in self.variables:
            return self.variables[key]
        elif self.parent_context:
            return self.parent_context.get_variable(key, default)
        return default
    
    def set_variable(self, key: str, value: Any):
        """设置变量值"""
        self.variables[key] = value
    
    def get_node_output(self, node_id: str) -> Optional[Any]:
        """获取节点输出"""
        return self.outputs.get(node_id)
    
    def set_node_output(self, node_id: str, output: Any):
        """设置节点输出"""
        self.outputs[node_id] = output


@dataclass
class NodeExecution:
    """节点执行实例"""
    id: str = field(default_factory=lambda: str(uuid4()))
    execution_id: str = ""
    node_id: str = ""
    status: NodeExecutionStatus = NodeExecutionStatus.WAITING
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error_info: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def start(self):
        """开始执行"""
        self.status = NodeExecutionStatus.RUNNING
        self.start_time = datetime.utcnow()
    
    def complete(self, output: Dict[str, Any]):
        """完成执行"""
        self.status = NodeExecutionStatus.SUCCESS
        self.output_data = output
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()
    
    def fail(self, error: Exception):
        """执行失败"""
        self.status = NodeExecutionStatus.FAILED
        self.error_info = {
            "type": type(error).__name__,
            "message": str(error),
            "timestamp": datetime.utcnow().isoformat()
        }
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()


@dataclass
class WorkflowExecution:
    """工作流执行实例"""
    id: str = field(default_factory=lambda: str(uuid4()))
    workflow_id: str = ""
    workflow_version: str = ""
    parent_execution_id: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    context: ExecutionContext = field(default_factory=ExecutionContext)
    node_executions: Dict[str, NodeExecution] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def start(self):
        """开始执行"""
        self.status = ExecutionStatus.RUNNING
        self.start_time = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def complete(self):
        """完成执行"""
        self.status = ExecutionStatus.COMPLETED
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()
        self.updated_at = datetime.utcnow()
    
    def fail(self, error_message: str):
        """执行失败"""
        self.status = ExecutionStatus.FAILED
        self.error_message = error_message
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()
        self.updated_at = datetime.utcnow()
    
    def suspend(self):
        """暂停执行"""
        self.status = ExecutionStatus.SUSPENDED
        self.updated_at = datetime.utcnow()
    
    def resume(self):
        """恢复执行"""
        self.status = ExecutionStatus.RUNNING
        self.updated_at = datetime.utcnow()
    
    def cancel(self):
        """取消执行"""
        self.status = ExecutionStatus.CANCELLED
        self.end_time = datetime.utcnow()
        if self.start_time:
            self.duration = (self.end_time - self.start_time).total_seconds()
        self.updated_at = datetime.utcnow()
    
    def get_node_execution(self, node_id: str) -> Optional[NodeExecution]:
        """获取节点执行实例"""
        return self.node_executions.get(node_id)
    
    def create_node_execution(self, node_id: str) -> NodeExecution:
        """创建节点执行实例"""
        node_execution = NodeExecution(
            execution_id=self.id,
            node_id=node_id
        )
        self.node_executions[node_id] = node_execution
        return node_execution
    
    def is_terminal_state(self) -> bool:
        """是否为终止状态"""
        return self.status in [
            ExecutionStatus.COMPLETED,
            ExecutionStatus.FAILED,
            ExecutionStatus.CANCELLED
        ]
    
    def can_execute_node(self, node_id: str, dependencies: List[str]) -> bool:
        """检查节点是否可以执行"""
        # 检查所有依赖节点是否执行成功
        for dep_id in dependencies:
            dep_execution = self.get_node_execution(dep_id)
            if not dep_execution or dep_execution.status != NodeExecutionStatus.SUCCESS:
                return False
        
        # 检查节点自身状态
        node_execution = self.get_node_execution(node_id)
        if node_execution and node_execution.status in [
            NodeExecutionStatus.RUNNING,
            NodeExecutionStatus.SUCCESS,
            NodeExecutionStatus.CANCELLED
        ]:
            return False
        
        return True


@dataclass
class ExecutionEvent:
    """执行事件"""
    id: str = field(default_factory=lambda: str(uuid4()))
    execution_id: str = ""
    node_id: Optional[str] = None
    event_type: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)
    
    
class ExecutionEventType(Enum):
    """执行事件类型"""
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_SUSPENDED = "workflow_suspended"
    WORKFLOW_RESUMED = "workflow_resumed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    NODE_RETRYING = "node_retrying"
    NODE_SKIPPED = "node_skipped"
