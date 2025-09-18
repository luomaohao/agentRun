# 快速开始指南

## 🚀 5分钟快速上手

### 1. 环境准备

```bash
# 克隆项目（如果还没有）
git clone <your-repository>
cd agentRun

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 2. 使用 Docker Compose 快速启动

```bash
# 启动所有服务（PostgreSQL + Redis + API）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f api
```

### 3. 访问 API 文档

打开浏览器访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 4. 创建第一个工作流

#### 使用 API（推荐）

```bash
# 创建简单的 DAG 工作流
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Hello World Workflow",
    "version": "1.0.0",
    "type": "dag",
    "nodes": [
      {
        "id": "greet",
        "name": "Greeting Node",
        "type": "agent",
        "config": {
          "agent_id": "intent-classifier"
        },
        "inputs": {
          "message": "${input.message}"
        }
      }
    ]
  }'

# 响应示例：
# {
#   "id": "550e8400-e29b-41d4-a716-446655440000",
#   "name": "Hello World Workflow",
#   ...
# }
```

#### 使用 Python SDK

```python
import asyncio
from src.workflow_engine import WorkflowEngine

async def main():
    # 初始化引擎
    engine = await setup_workflow_engine()
    
    # 定义工作流
    workflow_def = {
        "workflow": {
            "name": "Python Example",
            "type": "dag",
            "nodes": [
                {
                    "id": "start",
                    "type": "agent",
                    "config": {"agent_id": "assistant"},
                    "inputs": {"prompt": "${input.prompt}"}
                }
            ]
        }
    }
    
    # 创建工作流
    workflow_id = await engine.create_workflow(workflow_def)
    print(f"Created workflow: {workflow_id}")
    
    # 执行工作流
    execution_id = await engine.execute_workflow(
        workflow_id,
        {"input": {"prompt": "Hello, AI!"}}
    )
    print(f"Started execution: {execution_id}")

asyncio.run(main())
```

### 5. 执行工作流

```bash
# 使用之前创建的工作流ID
WORKFLOW_ID="550e8400-e29b-41d4-a716-446655440000"

# 执行工作流
curl -X POST http://localhost:8000/api/v1/executions/$WORKFLOW_ID/execute \
  -H "Content-Type: application/json" \
  -d '{
    "context": {
      "input": {
        "message": "Hello, World!"
      }
    }
  }'

# 响应示例：
# {
#   "execution_id": "650e8400-e29b-41d4-a716-446655440001",
#   "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
#   "status": "running"
# }
```

### 6. 查看执行状态

```bash
EXECUTION_ID="650e8400-e29b-41d4-a716-446655440001"

# 获取执行详情
curl http://localhost:8000/api/v1/executions/$EXECUTION_ID

# 使用 WebSocket 实时监听（可选）
wscat -c ws://localhost:8000/api/v1/executions/$EXECUTION_ID/stream
```

## 🎯 常见使用场景

### 1. 客服机器人工作流

```yaml
# examples/customer_support_workflow.yaml
workflow:
  name: 客服机器人
  type: dag
  nodes:
    - id: intent-recognition
      type: agent
      agent: intent-classifier
      
    - id: route-decision
      type: control
      subtype: switch
      dependencies: [intent-recognition]
      
    - id: handle-complaint
      type: agent
      agent: complaint-specialist
      dependencies: [route-decision]
```

### 2. 数据处理管道

```python
workflow_def = {
    "workflow": {
        "name": "ETL Pipeline",
        "type": "dag",
        "nodes": [
            {
                "id": "extract",
                "type": "tool",
                "tool": "database_query",
                "config": {"query": "SELECT * FROM users"}
            },
            {
                "id": "transform",
                "type": "agent",
                "agent": "data-transformer",
                "dependencies": ["extract"]
            },
            {
                "id": "load",
                "type": "tool",
                "tool": "database_insert",
                "dependencies": ["transform"]
            }
        ]
    }
}
```

### 3. 订单处理状态机

```yaml
# examples/order_state_machine.yaml
workflow:
  name: 订单处理
  type: state_machine
  initial_state: created
  states:
    - name: created
      transitions:
        - event: pay
          target: paid
    - name: paid
      transitions:
        - event: ship
          target: shipped
    - name: shipped
      transitions:
        - event: deliver
          target: completed
```

## 🛠️ 开发模式

### 本地开发（不使用 Docker）

```bash
# 1. 启动 PostgreSQL
pg_ctl start

# 2. 创建数据库
createdb workflow_db

# 3. 初始化 Schema
psql -d workflow_db -f src/workflow_engine/storage/database_schema.sql

# 4. 设置环境变量
export DATABASE_URL="postgresql://localhost/workflow_db"
export DISABLE_AUTH="true"

# 5. 启动 API 服务器
python main.py
```

### 使用 Makefile

```bash
# 安装依赖
make install

# 启动开发环境
make quickstart

# 运行开发服务器
make dev

# 运行测试
make test

# 代码格式化
make format
```

## 📚 下一步

1. **探索示例**：查看 `examples/` 目录中的完整示例
2. **阅读文档**：
   - [架构设计](ARCHITECTURE.md)
   - [API 文档](http://localhost:8000/docs)
   - [部署指南](API_DEPLOYMENT.md)
3. **自定义扩展**：
   - 添加自定义智能体
   - 注册新的工具
   - 实现自定义节点类型

## 🆘 常见问题

### Q: 数据库连接失败？
```bash
# 检查 PostgreSQL 是否运行
docker-compose ps

# 查看数据库日志
docker-compose logs postgres
```

### Q: API 启动失败？
```bash
# 检查端口占用
lsof -i :8000

# 查看详细日志
docker-compose logs -f api
```

### Q: 如何重置数据库？
```bash
# 停止服务
docker-compose down

# 删除数据卷
docker volume rm agentrun_postgres_data

# 重新启动
docker-compose up -d
```

## 🎉 恭喜！

您已经成功启动了 Agent Workflow Runtime！现在可以：

- 创建复杂的工作流
- 集成自己的智能体
- 构建生产级应用

有问题？查看[完整文档](README.md)或提交 Issue。
