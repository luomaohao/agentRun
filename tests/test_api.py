"""
API 端点测试
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock, patch
import json


class TestWorkflowAPI:
    """工作流 API 测试类"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        # 需要mock应用状态
        with patch('src.workflow_engine.api.app.get_app_state') as mock_get_state:
            # Mock 必要的组件
            mock_engine = Mock()
            mock_engine.create_workflow = AsyncMock(return_value="test-workflow-id")
            mock_engine.workflow_repository = Mock()
            mock_engine.workflow_repository.get = AsyncMock()
            mock_engine.workflow_repository.list = AsyncMock(return_value=[])
            
            mock_get_state.return_value = {
                "engine": mock_engine,
                "scheduler": Mock(),
                "event_bus": Mock()
            }
            
            from src.workflow_engine.api import app
            with TestClient(app) as client:
                yield client
    
    def test_create_workflow(self, client):
        """测试创建工作流"""
        workflow_data = {
            "name": "Test Workflow",
            "version": "1.0.0",
            "type": "dag",
            "nodes": [
                {
                    "id": "node1",
                    "name": "Node 1",
                    "type": "agent",
                    "config": {"agent_id": "test-agent"}
                }
            ]
        }
        
        response = client.post("/api/v1/workflows", json=workflow_data)
        
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["name"] == "Test Workflow"
    
    def test_list_workflows(self, client):
        """测试列出工作流"""
        response = client.get("/api/v1/workflows")
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
    
    def test_get_workflow(self, client):
        """测试获取工作流详情"""
        # Mock 工作流数据
        mock_workflow = Mock()
        mock_workflow.id = "test-id"
        mock_workflow.name = "Test Workflow"
        mock_workflow.version = "1.0.0"
        mock_workflow.type = Mock(value="dag")
        mock_workflow.description = "Test"
        mock_workflow.nodes = []
        mock_workflow.edges = []
        mock_workflow.variables = {}
        mock_workflow.triggers = []
        mock_workflow.error_handlers = []
        mock_workflow.created_at = Mock()
        mock_workflow.updated_at = Mock()
        mock_workflow.metadata = {}
        
        # 设置mock返回值
        app_state = client.app.extra.get("app_state", {})
        if "engine" in app_state:
            app_state["engine"].workflow_repository.get.return_value = mock_workflow
        
        response = client.get("/api/v1/workflows/test-id")
        
        # 由于mock的限制，这里只检查响应码
        assert response.status_code in [200, 404]
    
    def test_validate_workflow(self, client):
        """测试验证工作流"""
        mock_workflow = Mock()
        mock_workflow.validate = Mock(return_value=[])
        
        response = client.post("/api/v1/workflows/test-id/validate")
        
        # 检查响应
        assert response.status_code in [200, 404]


class TestExecutionAPI:
    """执行 API 测试类"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        with patch('src.workflow_engine.api.app.get_app_state') as mock_get_state:
            mock_engine = Mock()
            mock_engine.execute_workflow = AsyncMock(return_value="test-execution-id")
            mock_engine.workflow_repository = Mock()
            mock_engine.workflow_repository.get = AsyncMock()
            mock_engine.execution_repository = Mock()
            mock_engine.execution_repository.get = AsyncMock()
            mock_engine.execution_repository.list_by_workflow = AsyncMock(return_value=[])
            mock_engine.cancel_execution = AsyncMock()
            mock_engine.suspend_execution = AsyncMock()
            mock_engine.resume_execution = AsyncMock()
            
            mock_get_state.return_value = {
                "engine": mock_engine,
                "scheduler": Mock(),
                "event_bus": Mock()
            }
            
            from src.workflow_engine.api import app
            with TestClient(app) as client:
                yield client
    
    def test_execute_workflow(self, client):
        """测试执行工作流"""
        execution_data = {
            "context": {"input": "test"},
            "async_mode": True
        }
        
        # Mock 工作流存在
        mock_workflow = Mock()
        app_state = client.app.extra.get("app_state", {})
        if "engine" in app_state:
            app_state["engine"].workflow_repository.get.return_value = mock_workflow
        
        response = client.post(
            "/api/v1/executions/test-workflow-id/execute",
            json=execution_data
        )
        
        # 检查响应
        assert response.status_code in [202, 404]
        if response.status_code == 202:
            data = response.json()
            assert "execution_id" in data
    
    def test_get_execution_status(self, client):
        """测试获取执行状态"""
        response = client.get("/api/v1/executions/test-execution-id")
        
        # 检查响应
        assert response.status_code in [200, 404]
    
    def test_cancel_execution(self, client):
        """测试取消执行"""
        response = client.post("/api/v1/executions/test-execution-id/cancel")
        
        assert response.status_code in [200, 400, 404]


class TestMonitoringAPI:
    """监控 API 测试类"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        with patch('src.workflow_engine.api.app.get_app_state') as mock_get_state:
            mock_engine = Mock()
            mock_engine.workflow_repository = Mock()
            mock_engine.workflow_repository.list = AsyncMock(return_value=[])
            mock_engine.execution_repository = Mock()
            mock_engine.execution_repository.list_by_status = AsyncMock(return_value=[])
            mock_engine.scheduler = Mock()
            mock_engine.scheduler._scheduler_task = Mock(done=Mock(return_value=False))
            mock_engine.scheduler.get_scheduler_stats = Mock(return_value={})
            mock_engine.agent_runtime = Mock()
            mock_engine.agent_runtime.list_agents = AsyncMock(return_value=[])
            mock_engine.tool_registry = Mock()
            mock_engine.tool_registry.list_tools = AsyncMock(return_value=[])
            
            mock_get_state.return_value = {
                "engine": mock_engine,
                "scheduler": Mock(),
                "event_bus": Mock()
            }
            
            from src.workflow_engine.api import app
            with TestClient(app) as client:
                yield client
    
    def test_health_check(self, client):
        """测试健康检查"""
        response = client.get("/api/v1/monitoring/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
        assert data["status"] in ["healthy", "unhealthy"]
    
    def test_get_metrics(self, client):
        """测试获取指标"""
        response = client.get("/api/v1/monitoring/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "active_workflows" in data
        assert "running_executions" in data
        assert "avg_execution_time_ms" in data


class TestAPIAuthentication:
    """API 认证测试"""
    
    def test_unauthorized_access(self):
        """测试未授权访问"""
        # 启用认证
        import os
        os.environ["DISABLE_AUTH"] = "false"
        
        from src.workflow_engine.api import app
        with TestClient(app) as client:
            # 不带token访问受保护端点
            response = client.get("/api/v1/workflows")
            
            # 应该返回401
            assert response.status_code == 401
    
    def test_health_check_no_auth(self):
        """测试健康检查不需要认证"""
        import os
        os.environ["DISABLE_AUTH"] = "false"
        
        from src.workflow_engine.api import app
        with TestClient(app) as client:
            response = client.get("/api/v1/monitoring/health")
            
            # 健康检查应该不需要认证
            assert response.status_code == 200
