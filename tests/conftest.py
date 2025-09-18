"""
Pytest 配置和公共 fixtures
"""
import pytest
import asyncio
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.workflow_engine.core import WorkflowEngine, TaskScheduler
from src.workflow_engine.storage.repository import InMemoryWorkflowRepository, InMemoryExecutionRepository
from src.workflow_engine.storage.sqlalchemy_repository import DatabaseManager
from src.workflow_engine.integrations import EventBus, MockAgentRuntime, LocalToolRegistry
from src.workflow_engine.core.error_handler import ErrorHandler
from src.workflow_engine.core.compensation import CompensationManager


# 配置 pytest-asyncio
pytest_plugins = ('pytest_asyncio',)


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def memory_workflow_engine() -> AsyncGenerator[WorkflowEngine, None]:
    """创建使用内存存储的工作流引擎"""
    # 创建组件
    workflow_repo = InMemoryWorkflowRepository()
    execution_repo = InMemoryExecutionRepository()
    scheduler = TaskScheduler()
    event_bus = EventBus()
    agent_runtime = MockAgentRuntime()
    tool_registry = LocalToolRegistry()
    error_handler = ErrorHandler()
    compensation_manager = CompensationManager()
    
    # 创建引擎
    engine = WorkflowEngine(
        workflow_repository=workflow_repo,
        execution_repository=execution_repo,
        scheduler=scheduler,
        event_bus=event_bus,
        agent_runtime=agent_runtime,
        tool_registry=tool_registry,
        error_handler=error_handler,
        compensation_manager=compensation_manager
    )
    
    # 启动调度器
    await scheduler.start()
    
    yield engine
    
    # 清理
    await scheduler.stop()


@pytest.fixture
def sample_dag_workflow() -> dict:
    """示例 DAG 工作流"""
    return {
        "workflow": {
            "id": "test-dag-workflow",
            "name": "Test DAG Workflow",
            "version": "1.0.0",
            "type": "dag",
            "nodes": [
                {
                    "id": "start",
                    "name": "Start Node",
                    "type": "agent",
                    "config": {"agent_id": "intent-classifier"},
                    "inputs": {"message": "${input.message}"},
                    "outputs": ["intent", "confidence"]
                },
                {
                    "id": "process",
                    "name": "Process Node",
                    "type": "agent",
                    "config": {"agent_id": "complaint-specialist"},
                    "dependencies": ["start"],
                    "inputs": {"intent": "${start.intent}"},
                    "outputs": ["response"]
                }
            ],
            "edges": [
                {"source": "start", "target": "process"}
            ]
        }
    }


@pytest.fixture
def sample_state_machine_workflow() -> dict:
    """示例状态机工作流"""
    return {
        "workflow": {
            "id": "test-state-machine",
            "name": "Test State Machine",
            "version": "1.0.0",
            "type": "state_machine",
            "initial_state": "idle",
            "final_states": ["completed", "failed"],
            "states": [
                {
                    "name": "idle",
                    "transitions": [
                        {
                            "event": "start",
                            "target": "processing"
                        }
                    ]
                },
                {
                    "name": "processing",
                    "transitions": [
                        {
                            "event": "complete",
                            "target": "completed"
                        },
                        {
                            "event": "error",
                            "target": "failed"
                        }
                    ]
                },
                {
                    "name": "completed",
                    "type": "final"
                },
                {
                    "name": "failed",
                    "type": "final"
                }
            ]
        }
    }


@pytest.fixture
def sample_workflow_with_error_handling() -> dict:
    """带错误处理的示例工作流"""
    return {
        "workflow": {
            "id": "test-error-handling",
            "name": "Test Error Handling",
            "version": "1.0.0",
            "type": "dag",
            "nodes": [
                {
                    "id": "may-fail",
                    "name": "May Fail Node",
                    "type": "tool",
                    "config": {"tool_id": "unstable-tool"},
                    "retry_policy": {
                        "max_retries": 3,
                        "retry_delay": 0.1,
                        "backoff_factor": 2
                    }
                }
            ],
            "error_handlers": [
                {
                    "node_pattern": "may-fail",
                    "error_type": "execution_error",
                    "action": {
                        "type": "retry"
                    }
                }
            ]
        }
    }


@pytest.fixture
async def test_database() -> AsyncGenerator[DatabaseManager, None]:
    """创建测试数据库"""
    # 使用 SQLite 内存数据库进行测试
    db_manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await db_manager.initialize()
    
    yield db_manager
    
    await db_manager.close()


@pytest.fixture
def mock_agent_runtime() -> MockAgentRuntime:
    """创建模拟智能体运行时"""
    return MockAgentRuntime()


@pytest.fixture
def event_bus() -> EventBus:
    """创建事件总线"""
    return EventBus()


@pytest.fixture
async def api_client():
    """创建 API 测试客户端"""
    from fastapi.testclient import TestClient
    from src.workflow_engine.api import app
    
    with TestClient(app) as client:
        yield client
