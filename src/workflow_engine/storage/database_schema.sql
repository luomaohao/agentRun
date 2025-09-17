-- Agent Workflow Runtime Database Schema
-- PostgreSQL implementation

-- 创建扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- 用于文本搜索

-- 工作流定义表
CREATE TABLE workflow_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    type VARCHAR(50) NOT NULL CHECK (type IN ('dag', 'state_machine', 'hybrid')),
    definition JSONB NOT NULL,
    description TEXT,
    tags TEXT[],
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_workflow_name_version UNIQUE(name, version)
);

-- 工作流节点定义表（用于快速查询和索引）
CREATE TABLE workflow_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflow_definitions(id) ON DELETE CASCADE,
    node_id VARCHAR(255) NOT NULL,
    node_type VARCHAR(50) NOT NULL,
    node_name VARCHAR(255),
    configuration JSONB NOT NULL,
    dependencies TEXT[], -- 依赖的节点ID数组
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_workflow_node UNIQUE(workflow_id, node_id)
);

-- 工作流执行实例表
CREATE TABLE workflow_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflow_definitions(id),
    parent_execution_id UUID REFERENCES workflow_executions(id),
    status VARCHAR(50) NOT NULL CHECK (status IN ('pending', 'running', 'suspended', 'completed', 'failed', 'cancelled', 'compensating')),
    context JSONB DEFAULT '{}',
    input_data JSONB DEFAULT '{}',
    output_data JSONB,
    error_info JSONB,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_ms BIGINT,
    triggered_by VARCHAR(255),
    trigger_type VARCHAR(50), -- webhook, event, manual, scheduled
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 节点执行实例表
CREATE TABLE node_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    node_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN ('waiting', 'ready', 'running', 'success', 'failed', 'skipped', 'retrying', 'cancelled')),
    input_data JSONB DEFAULT '{}',
    output_data JSONB,
    error_info JSONB,
    retry_count INTEGER DEFAULT 0,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_ms BIGINT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_execution_node UNIQUE(execution_id, node_id)
);

-- 执行事件表（用于审计和追踪）
CREATE TABLE execution_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID NOT NULL REFERENCES workflow_executions(id) ON DELETE CASCADE,
    node_id VARCHAR(255),
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB DEFAULT '{}',
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- 状态机实例表
CREATE TABLE state_machine_instances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflow_definitions(id),
    instance_id VARCHAR(255) NOT NULL UNIQUE,
    current_state VARCHAR(255) NOT NULL,
    context JSONB DEFAULT '{}',
    history JSONB DEFAULT '[]', -- 状态转换历史
    is_final BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- 智能体配置表
CREATE TABLE agent_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    meta_prompt TEXT,
    model VARCHAR(100) DEFAULT 'gpt-4',
    temperature DECIMAL(3,2) DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 2000,
    input_schema JSONB,
    output_schema JSONB,
    tools TEXT[], -- 允许使用的工具ID列表
    permissions JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 工具定义表
CREATE TABLE tool_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tool_id VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    parameters_schema JSONB NOT NULL,
    response_schema JSONB,
    permissions TEXT[], -- 所需权限列表
    rate_limit INTEGER, -- 每分钟调用次数限制
    timeout_seconds INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT true,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 工具调用日志表
CREATE TABLE tool_invocation_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_id UUID REFERENCES workflow_executions(id) ON DELETE SET NULL,
    node_id VARCHAR(255),
    tool_id VARCHAR(255) NOT NULL,
    input_parameters JSONB,
    output_result JSONB,
    error_info JSONB,
    duration_ms BIGINT,
    status VARCHAR(50) CHECK (status IN ('success', 'failed', 'timeout')),
    invoked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- 调度任务表（用于定时任务）
CREATE TABLE scheduled_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflow_definitions(id),
    schedule_expression VARCHAR(255) NOT NULL, -- Cron表达式
    timezone VARCHAR(50) DEFAULT 'UTC',
    is_active BOOLEAN DEFAULT true,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    context JSONB DEFAULT '{}', -- 默认执行上下文
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 索引优化
CREATE INDEX idx_workflow_definitions_name ON workflow_definitions(name);
CREATE INDEX idx_workflow_definitions_tags ON workflow_definitions USING GIN(tags);
CREATE INDEX idx_workflow_definitions_active ON workflow_definitions(is_active);

CREATE INDEX idx_workflow_nodes_workflow_id ON workflow_nodes(workflow_id);
CREATE INDEX idx_workflow_nodes_type ON workflow_nodes(node_type);

CREATE INDEX idx_workflow_executions_workflow_id ON workflow_executions(workflow_id);
CREATE INDEX idx_workflow_executions_status ON workflow_executions(status);
CREATE INDEX idx_workflow_executions_created_at ON workflow_executions(created_at);
CREATE INDEX idx_workflow_executions_trigger_type ON workflow_executions(trigger_type);

CREATE INDEX idx_node_executions_execution_id ON node_executions(execution_id);
CREATE INDEX idx_node_executions_status ON node_executions(status);
CREATE INDEX idx_node_executions_node_id ON node_executions(node_id);

CREATE INDEX idx_execution_events_execution_id ON execution_events(execution_id);
CREATE INDEX idx_execution_events_event_type ON execution_events(event_type);
CREATE INDEX idx_execution_events_timestamp ON execution_events(timestamp);

CREATE INDEX idx_state_machine_instances_workflow_id ON state_machine_instances(workflow_id);
CREATE INDEX idx_state_machine_instances_current_state ON state_machine_instances(current_state);

CREATE INDEX idx_agent_configs_agent_id ON agent_configs(agent_id);
CREATE INDEX idx_agent_configs_active ON agent_configs(is_active);

CREATE INDEX idx_tool_definitions_tool_id ON tool_definitions(tool_id);
CREATE INDEX idx_tool_definitions_category ON tool_definitions(category);
CREATE INDEX idx_tool_definitions_active ON tool_definitions(is_active);

CREATE INDEX idx_tool_invocation_logs_execution_id ON tool_invocation_logs(execution_id);
CREATE INDEX idx_tool_invocation_logs_tool_id ON tool_invocation_logs(tool_id);
CREATE INDEX idx_tool_invocation_logs_invoked_at ON tool_invocation_logs(invoked_at);

-- 全文搜索索引
CREATE INDEX idx_workflow_definitions_search ON workflow_definitions USING GIN(to_tsvector('english', name || ' ' || COALESCE(description, '')));

-- 触发器：自动更新 updated_at 字段
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_workflow_definitions_updated_at BEFORE UPDATE ON workflow_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_workflow_executions_updated_at BEFORE UPDATE ON workflow_executions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_node_executions_updated_at BEFORE UPDATE ON node_executions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_state_machine_instances_updated_at BEFORE UPDATE ON state_machine_instances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agent_configs_updated_at BEFORE UPDATE ON agent_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tool_definitions_updated_at BEFORE UPDATE ON tool_definitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 视图：活跃工作流执行统计
CREATE VIEW active_execution_stats AS
SELECT 
    w.name as workflow_name,
    w.version as workflow_version,
    e.status,
    COUNT(*) as count,
    AVG(e.duration_ms) as avg_duration_ms,
    MAX(e.duration_ms) as max_duration_ms,
    MIN(e.duration_ms) as min_duration_ms
FROM workflow_executions e
JOIN workflow_definitions w ON e.workflow_id = w.id
WHERE e.created_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
GROUP BY w.name, w.version, e.status;

-- 视图：节点执行性能统计
CREATE VIEW node_execution_performance AS
SELECT 
    n.node_id,
    n.node_type,
    COUNT(*) as execution_count,
    AVG(ne.duration_ms) as avg_duration_ms,
    MAX(ne.duration_ms) as max_duration_ms,
    SUM(CASE WHEN ne.status = 'failed' THEN 1 ELSE 0 END) as failure_count,
    AVG(ne.retry_count) as avg_retry_count
FROM node_executions ne
JOIN workflow_nodes n ON ne.node_id = n.node_id
WHERE ne.created_at > CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY n.node_id, n.node_type;

-- 函数：清理旧的执行记录
CREATE OR REPLACE FUNCTION cleanup_old_executions(days_to_keep INTEGER DEFAULT 30)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM workflow_executions
    WHERE created_at < CURRENT_TIMESTAMP - (days_to_keep || ' days')::INTERVAL
    AND status IN ('completed', 'failed', 'cancelled');
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- 分区表示例（用于大规模部署）
-- 按月分区执行事件表
CREATE TABLE execution_events_partitioned (
    LIKE execution_events INCLUDING ALL
) PARTITION BY RANGE (timestamp);

-- 创建分区
CREATE TABLE execution_events_2024_01 PARTITION OF execution_events_partitioned
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');

CREATE TABLE execution_events_2024_02 PARTITION OF execution_events_partitioned
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');

-- 权限设置
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO workflow_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO workflow_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO workflow_app;
