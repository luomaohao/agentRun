# Agent Workflow Runtime

一个强大、灵活的智能体工作流执行引擎，支持 DAG（有向无环图）和状态机两种工作流模式，为复杂的智能体协作场景提供可靠的执行基础。

## 特性

- 🔄 **双模式支持**：同时支持 DAG 和状态机工作流
- 🤖 **智能体集成**：原生支持多智能体协作
- 🛠️ **工具调用**：灵活的工具注册和调用机制
- ⚡ **并行执行**：智能调度，最大化并行执行效率
- 🔁 **错误恢复**：完善的重试、补偿和降级策略
- 📊 **可观测性**：全链路追踪和监控
- 🔌 **可扩展**：模块化设计，易于扩展

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 基本使用

```python
import asyncio
from src.workflow_engine import WorkflowEngine

async def main():
    # 创建工作流引擎
    engine = await setup_workflow_engine()
    
    # 创建工作流
    workflow_id = await engine.create_workflow("examples/customer_support_workflow.yaml")
    
    # 执行工作流
    execution_id = await engine.execute_workflow(workflow_id, {
        "trigger": {
            "message": "我需要帮助",
            "user_id": "user123"
        }
    })
    
    # 获取执行状态
    status = await engine.get_execution_status(execution_id)
    print(status)

asyncio.run(main())
```

## 工作流定义

### DAG 工作流

DAG 工作流适用于有明确依赖关系的任务编排：

```yaml
workflow:
  id: my-dag-workflow
  type: dag
  nodes:
    - id: node1
      type: agent
      agent: my-agent
      inputs:
        data: "${input.data}"
    
    - id: node2
      type: tool
      tool: http_request
      dependencies: [node1]
      inputs:
        url: "${node1.output.url}"
```

### 状态机工作流

状态机工作流适用于复杂的状态转换场景：

```yaml
workflow:
  id: my-state-machine
  type: state_machine
  initial_state: start
  states:
    - name: start
      transitions:
        - event: begin
          target: processing
    
    - name: processing
      on_enter:
        - type: log
          params:
            message: "开始处理"
      transitions:
        - event: complete
          target: done
```

## 核心概念

### 节点类型

- **Agent 节点**：调用智能体执行任务
- **Tool 节点**：调用外部工具或函数
- **Control 节点**：控制流程（条件判断、并行、循环）
- **Aggregation 节点**：聚合多个节点的输出

### 执行模式

- **异步执行**：默认模式，立即返回执行ID
- **同步执行**：等待工作流完成后返回结果

### 错误处理

- **重试策略**：支持指数退避的自动重试
- **补偿机制**：失败时执行补偿操作
- **降级处理**：失败时切换到备用方案

## 高级特性

### 并行执行

```yaml
- id: parallel-tasks
  type: control
  subtype: parallel
  branches: [task1, task2, task3]
  wait_all: true
```

### 条件分支

```yaml
- id: decision
  type: control
  subtype: switch
  condition: "${score}"
  branches:
    - case: high
      target: premium-handler
    - case: low
      target: basic-handler
    - default: standard-handler
```

### 子工作流

```yaml
- id: sub-workflow
  type: sub_workflow
  workflow_id: another-workflow
  inputs:
    data: "${current.data}"
```

## API 参考

### 工作流管理

- `POST /workflows` - 创建工作流
- `GET /workflows/{id}` - 获取工作流定义
- `PUT /workflows/{id}` - 更新工作流
- `DELETE /workflows/{id}` - 删除工作流

### 执行管理

- `POST /workflows/{id}/execute` - 执行工作流
- `GET /executions/{id}` - 获取执行状态
- `POST /executions/{id}/cancel` - 取消执行
- `POST /executions/{id}/suspend` - 暂停执行
- `POST /executions/{id}/resume` - 恢复执行

## 配置

### 资源限制

```python
resource_quota = ResourceQuota(
    max_concurrent_tasks=100,
    max_tasks_per_type={"agent": 50, "tool": 30},
    max_tasks_per_agent={"gpt-4": 10}
)
```

### 速率限制

```python
scheduler.set_rate_limiter("openai", rate=60, interval=timedelta(minutes=1))
```

## 监控与调试

### 日志配置

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### 事件订阅

```python
async def event_handler(event):
    print(f"Event: {event.topic} - {event.payload}")

await engine.event_bus.subscribe("workflow.execution.events", event_handler)
```

## 示例

查看 `examples/` 目录获取更多示例：

- `customer_support_workflow.yaml` - 客服工作流示例
- `order_state_machine.yaml` - 订单状态机示例
- `usage_example.py` - 使用示例代码

## 架构设计

详细的架构设计请参考：
- [架构文档](ARCHITECTURE.md)
- [工作流引擎设计](WORKFLOW_ENGINE_DESIGN.md)

## 项目结构

```
agentRun/
├── src/
│   └── workflow_engine/
│       ├── core/
│       │   ├── engine.py          # 工作流执行引擎
│       │   ├── scheduler.py       # 任务调度器
│       │   ├── parser.py          # 工作流解析器
│       │   └── state_machine.py   # 状态机引擎
│       ├── models/
│       │   ├── workflow.py        # 工作流模型
│       │   └── execution.py       # 执行模型
│       ├── storage/
│       │   └── repository.py      # 存储接口
│       ├── integrations/
│       │   ├── agent_runtime.py   # 智能体运行时
│       │   ├── tool_registry.py   # 工具注册表
│       │   └── event_bus.py       # 事件总线
│       └── exceptions.py          # 异常定义
├── examples/
│   ├── customer_support_workflow.yaml
│   ├── order_state_machine.yaml
│   └── usage_example.py
├── tests/
├── ARCHITECTURE.md
├── WORKFLOW_ENGINE_DESIGN.md
└── README.md
```

## 开发计划

- [ ] 数据库持久化层
- [ ] RESTful API 实现
- [ ] 性能优化（执行计划缓存）
- [ ] 监控集成（Prometheus/Grafana）
- [ ] 单元测试和集成测试
- [ ] Docker 容器化部署
- [ ] Kubernetes Operator

## 贡献指南

欢迎提交 Pull Request 和 Issue！

## 许可证

MIT License