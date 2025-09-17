"""
SQLAlchemy 数据库模型定义
"""
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, BigInteger, Float,
    DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Index,
    JSON, ARRAY, UUID
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql import func
from datetime import datetime
import uuid


Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class WorkflowDefinition(Base):
    """工作流定义模型"""
    __tablename__ = 'workflow_definitions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    version = Column(String(50), nullable=False)
    type = Column(String(50), nullable=False)
    definition = Column(JSON, nullable=False)
    description = Column(Text)
    tags = Column(ARRAY(String))
    is_active = Column(Boolean, default=True)
    metadata = Column(JSON, default={})
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 关系
    nodes = relationship("WorkflowNode", back_populates="workflow", cascade="all, delete-orphan")
    executions = relationship("WorkflowExecution", back_populates="workflow")
    
    # 约束
    __table_args__ = (
        UniqueConstraint('name', 'version', name='unique_workflow_name_version'),
        CheckConstraint("type IN ('dag', 'state_machine', 'hybrid')", name='check_workflow_type'),
        Index('idx_workflow_definitions_name', 'name'),
        Index('idx_workflow_definitions_active', 'is_active'),
    )


class WorkflowNode(Base):
    """工作流节点模型"""
    __tablename__ = 'workflow_nodes'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('workflow_definitions.id', ondelete='CASCADE'), nullable=False)
    node_id = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    node_name = Column(String(255))
    configuration = Column(JSON, nullable=False)
    dependencies = Column(ARRAY(String))
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    workflow = relationship("WorkflowDefinition", back_populates="nodes")
    
    # 约束
    __table_args__ = (
        UniqueConstraint('workflow_id', 'node_id', name='unique_workflow_node'),
        Index('idx_workflow_nodes_workflow_id', 'workflow_id'),
        Index('idx_workflow_nodes_type', 'node_type'),
    )


class WorkflowExecution(Base):
    """工作流执行实例模型"""
    __tablename__ = 'workflow_executions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('workflow_definitions.id'), nullable=False)
    parent_execution_id = Column(UUID(as_uuid=True), ForeignKey('workflow_executions.id'))
    status = Column(String(50), nullable=False)
    context = Column(JSON, default={})
    input_data = Column(JSON, default={})
    output_data = Column(JSON)
    error_info = Column(JSON)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    duration_ms = Column(BigInteger)
    triggered_by = Column(String(255))
    trigger_type = Column(String(50))
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 关系
    workflow = relationship("WorkflowDefinition", back_populates="executions")
    parent_execution = relationship("WorkflowExecution", remote_side=[id])
    node_executions = relationship("NodeExecution", back_populates="execution", cascade="all, delete-orphan")
    events = relationship("ExecutionEvent", back_populates="execution", cascade="all, delete-orphan")
    
    # 约束
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'suspended', 'completed', 'failed', 'cancelled', 'compensating')",
            name='check_execution_status'
        ),
        Index('idx_workflow_executions_workflow_id', 'workflow_id'),
        Index('idx_workflow_executions_status', 'status'),
        Index('idx_workflow_executions_created_at', 'created_at'),
        Index('idx_workflow_executions_trigger_type', 'trigger_type'),
    )


class NodeExecution(Base):
    """节点执行实例模型"""
    __tablename__ = 'node_executions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False)
    node_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    input_data = Column(JSON, default={})
    output_data = Column(JSON)
    error_info = Column(JSON)
    retry_count = Column(Integer, default=0)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    duration_ms = Column(BigInteger)
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 关系
    execution = relationship("WorkflowExecution", back_populates="node_executions")
    
    # 约束
    __table_args__ = (
        UniqueConstraint('execution_id', 'node_id', name='unique_execution_node'),
        CheckConstraint(
            "status IN ('waiting', 'ready', 'running', 'success', 'failed', 'skipped', 'retrying', 'cancelled')",
            name='check_node_status'
        ),
        Index('idx_node_executions_execution_id', 'execution_id'),
        Index('idx_node_executions_status', 'status'),
        Index('idx_node_executions_node_id', 'node_id'),
    )


class ExecutionEvent(Base):
    """执行事件模型"""
    __tablename__ = 'execution_events'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False)
    node_id = Column(String(255))
    event_type = Column(String(100), nullable=False)
    event_data = Column(JSON, default={})
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    metadata = Column(JSON, default={})
    
    # 关系
    execution = relationship("WorkflowExecution", back_populates="events")
    
    # 约束
    __table_args__ = (
        Index('idx_execution_events_execution_id', 'execution_id'),
        Index('idx_execution_events_event_type', 'event_type'),
        Index('idx_execution_events_timestamp', 'timestamp'),
    )


class StateMachineInstance(Base):
    """状态机实例模型"""
    __tablename__ = 'state_machine_instances'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('workflow_definitions.id'), nullable=False)
    instance_id = Column(String(255), nullable=False, unique=True)
    current_state = Column(String(255), nullable=False)
    context = Column(JSON, default={})
    history = Column(JSON, default=[])
    is_final = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    metadata = Column(JSON, default={})
    
    # 关系
    workflow = relationship("WorkflowDefinition")
    
    # 约束
    __table_args__ = (
        Index('idx_state_machine_instances_workflow_id', 'workflow_id'),
        Index('idx_state_machine_instances_current_state', 'current_state'),
    )


class AgentConfig(Base):
    """智能体配置模型"""
    __tablename__ = 'agent_configs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    meta_prompt = Column(Text)
    model = Column(String(100), default='gpt-4')
    temperature = Column(Float, default=0.7)
    max_tokens = Column(Integer, default=2000)
    input_schema = Column(JSON)
    output_schema = Column(JSON)
    tools = Column(ARRAY(String))
    permissions = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 约束
    __table_args__ = (
        Index('idx_agent_configs_agent_id', 'agent_id'),
        Index('idx_agent_configs_active', 'is_active'),
    )


class ToolDefinition(Base):
    """工具定义模型"""
    __tablename__ = 'tool_definitions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool_id = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    parameters_schema = Column(JSON, nullable=False)
    response_schema = Column(JSON)
    permissions = Column(ARRAY(String))
    rate_limit = Column(Integer)
    timeout_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 约束
    __table_args__ = (
        Index('idx_tool_definitions_tool_id', 'tool_id'),
        Index('idx_tool_definitions_category', 'category'),
        Index('idx_tool_definitions_active', 'is_active'),
    )


class ToolInvocationLog(Base):
    """工具调用日志模型"""
    __tablename__ = 'tool_invocation_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey('workflow_executions.id', ondelete='SET NULL'))
    node_id = Column(String(255))
    tool_id = Column(String(255), nullable=False)
    input_parameters = Column(JSON)
    output_result = Column(JSON)
    error_info = Column(JSON)
    duration_ms = Column(BigInteger)
    status = Column(String(50))
    invoked_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata = Column(JSON, default={})
    
    # 关系
    execution = relationship("WorkflowExecution")
    
    # 约束
    __table_args__ = (
        CheckConstraint("status IN ('success', 'failed', 'timeout')", name='check_tool_status'),
        Index('idx_tool_invocation_logs_execution_id', 'execution_id'),
        Index('idx_tool_invocation_logs_tool_id', 'tool_id'),
        Index('idx_tool_invocation_logs_invoked_at', 'invoked_at'),
    )


class ScheduledTask(Base):
    """调度任务模型"""
    __tablename__ = 'scheduled_tasks'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey('workflow_definitions.id'), nullable=False)
    schedule_expression = Column(String(255), nullable=False)
    timezone = Column(String(50), default='UTC')
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    context = Column(JSON, default={})
    metadata = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # 关系
    workflow = relationship("WorkflowDefinition")
    
    # 约束
    __table_args__ = (
        Index('idx_scheduled_tasks_workflow_id', 'workflow_id'),
        Index('idx_scheduled_tasks_active', 'is_active'),
        Index('idx_scheduled_tasks_next_run', 'next_run_at'),
    )
