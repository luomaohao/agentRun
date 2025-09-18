"""
FastAPI 应用主文件
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import os
from typing import Dict, Any

from .routers import workflows, executions, state_machines, monitoring
from .middleware import RequestLoggingMiddleware, AuthenticationMiddleware
from ..core import WorkflowEngine, TaskScheduler
from ..storage.sqlalchemy_repository import DatabaseManager, SQLAlchemyWorkflowRepository, SQLAlchemyExecutionRepository
from ..integrations import EventBus, MockAgentRuntime, LocalToolRegistry, BuiltinTools


logger = logging.getLogger(__name__)


# 全局实例
app_state: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("Starting Workflow Engine API...")
    
    # 初始化数据库
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:password@localhost/workflow_db")
    db_manager = DatabaseManager(db_url)
    await db_manager.initialize()
    
    # 初始化仓库
    workflow_repo = SQLAlchemyWorkflowRepository(db_manager)
    execution_repo = SQLAlchemyExecutionRepository(db_manager)
    
    # 初始化核心组件
    scheduler = TaskScheduler()
    event_bus = EventBus()
    agent_runtime = MockAgentRuntime()
    tool_registry = LocalToolRegistry()
    
    # 注册内置工具
    await BuiltinTools.register_all(tool_registry)
    
    # 创建工作流引擎
    engine = WorkflowEngine(
        workflow_repository=workflow_repo,
        execution_repository=execution_repo,
        scheduler=scheduler,
        event_bus=event_bus,
        agent_runtime=agent_runtime,
        tool_registry=tool_registry
    )
    
    # 启动调度器
    await scheduler.start()
    
    # 保存到全局状态
    app_state.update({
        "db_manager": db_manager,
        "workflow_repo": workflow_repo,
        "execution_repo": execution_repo,
        "engine": engine,
        "scheduler": scheduler,
        "event_bus": event_bus
    })
    
    logger.info("Workflow Engine API started successfully")
    
    yield
    
    # 关闭时清理
    logger.info("Shutting down Workflow Engine API...")
    
    # 停止调度器
    await scheduler.stop()
    
    # 关闭数据库连接
    await db_manager.close()
    
    logger.info("Workflow Engine API shut down successfully")


# 创建FastAPI应用
app = FastAPI(
    title="Agent Workflow Runtime API",
    description="智能体工作流执行引擎 RESTful API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该配置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加中间件
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AuthenticationMiddleware)

# 注册路由
app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(executions.router, prefix="/api/v1/executions", tags=["executions"])
app.include_router(state_machines.router, prefix="/api/v1/state-machines", tags=["state-machines"])
app.include_router(monitoring.router, prefix="/api/v1/monitoring", tags=["monitoring"])


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "request_id": request.state.request_id if hasattr(request.state, "request_id") else None
        }
    )


# 根路径
@app.get("/", tags=["root"])
async def root():
    """API根路径"""
    return {
        "name": "Agent Workflow Runtime API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/monitoring/health"
    }


# 获取应用状态的辅助函数
def get_app_state() -> Dict[str, Any]:
    """获取应用状态"""
    return app_state
