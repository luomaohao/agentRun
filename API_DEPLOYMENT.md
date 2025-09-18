# API 部署指南

## 环境变量配置

创建 `.env` 文件并配置以下环境变量：

```bash
# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true
API_WORKERS=1

# Database Configuration
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/workflow_db

# Authentication
JWT_SECRET_KEY=your-secret-key-here
DISABLE_AUTH=true  # Set to false in production

# Event Bus
EVENT_BUS_TYPE=memory  # Options: memory, kafka, nats
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
NATS_SERVERS=nats://localhost:4222

# Model Configuration
OPENAI_API_KEY=your-openai-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4

# Storage
STORAGE_TYPE=postgresql  # Options: memory, postgresql, mongodb
REDIS_URL=redis://localhost:6379

# Monitoring
ENABLE_METRICS=true
METRICS_PORT=9090
JAEGER_ENDPOINT=http://localhost:14268/api/traces

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json  # Options: json, text

# Resource Limits
MAX_CONCURRENT_WORKFLOWS=100
MAX_CONCURRENT_NODES=50
MAX_WORKFLOW_DURATION=3600  # seconds

# Error Handling
DEFAULT_RETRY_COUNT=3
DEFAULT_RETRY_DELAY=1  # seconds
ENABLE_CIRCUIT_BREAKER=true
```

## 本地开发运行

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 设置数据库：
```bash
# 创建 PostgreSQL 数据库
createdb workflow_db

# 运行数据库迁移
psql -d workflow_db -f src/workflow_engine/storage/database_schema.sql
```

3. 启动 API 服务器：
```bash
python main.py
```

4. 访问 API 文档：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Docker 部署

### 使用 Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: workflow_db
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:password@postgres:5432/workflow_db
      REDIS_URL: redis://redis:6379
      DISABLE_AUTH: "false"
    depends_on:
      - postgres
      - redis
    volumes:
      - ./logs:/app/logs

volumes:
  postgres_data:
```

创建 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非 root 用户
RUN useradd -m -u 1000 workflow && chown -R workflow:workflow /app
USER workflow

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "main.py"]
```

运行：
```bash
docker-compose up -d
```

## 生产部署

### Kubernetes 部署

创建 `k8s-deployment.yaml`：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: workflow-api
  labels:
    app: workflow-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: workflow-api
  template:
    metadata:
      labels:
        app: workflow-api
    spec:
      containers:
      - name: api
        image: workflow-api:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: workflow-secrets
              key: database-url
        - name: JWT_SECRET_KEY
          valueFrom:
            secretKeyRef:
              name: workflow-secrets
              key: jwt-secret
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /api/v1/monitoring/health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /api/v1/monitoring/health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: workflow-api
spec:
  selector:
    app: workflow-api
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8000
  type: LoadBalancer
```

### 监控和日志

1. **Prometheus 监控**
   - 配置 Prometheus 抓取 `/metrics` 端点
   - 创建 Grafana 仪表板

2. **日志收集**
   - 使用 ELK Stack 或 Loki 收集日志
   - 配置结构化日志输出

3. **追踪**
   - 集成 Jaeger 或 Zipkin
   - 配置 OpenTelemetry

## API 使用示例

### 创建工作流

```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "example-workflow",
    "version": "1.0.0",
    "type": "dag",
    "nodes": [
      {
        "id": "node1",
        "name": "Start Node",
        "type": "agent",
        "config": {"agent_id": "assistant"}
      }
    ]
  }'
```

### 执行工作流

```bash
curl -X POST http://localhost:8000/api/v1/executions/{workflow_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "context": {
      "input": "test data"
    }
  }'
```

### 查看执行状态

```bash
curl http://localhost:8000/api/v1/executions/{execution_id}
```

## 安全配置

1. **认证**
   - 生产环境必须设置 `DISABLE_AUTH=false`
   - 使用强密码的 JWT 密钥
   - 定期轮换密钥

2. **网络安全**
   - 使用 HTTPS
   - 配置 CORS 白名单
   - 使用防火墙规则

3. **数据安全**
   - 加密敏感数据
   - 使用 SSL 连接数据库
   - 定期备份

## 性能优化

1. **数据库优化**
   - 创建适当的索引
   - 使用连接池
   - 定期清理旧数据

2. **缓存策略**
   - 使用 Redis 缓存热点数据
   - 缓存工作流定义
   - 缓存执行计划

3. **水平扩展**
   - 使用负载均衡器
   - 配置自动扩缩容
   - 使用消息队列解耦

## 故障排查

1. **查看日志**
```bash
docker-compose logs -f api
```

2. **检查健康状态**
```bash
curl http://localhost:8000/api/v1/monitoring/health
```

3. **性能分析**
   - 查看 `/api/v1/monitoring/metrics`
   - 分析慢查询日志
   - 使用 APM 工具
