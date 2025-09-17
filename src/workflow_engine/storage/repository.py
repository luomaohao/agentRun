"""
存储仓库接口定义
"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime

from ..models.workflow import Workflow
from ..models.execution import WorkflowExecution, ExecutionStatus


class WorkflowRepository(ABC):
    """工作流存储仓库接口"""
    
    @abstractmethod
    async def save(self, workflow: Workflow) -> str:
        """保存工作流"""
        pass
    
    @abstractmethod
    async def get(self, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        pass
    
    @abstractmethod
    async def get_by_name(self, name: str, version: str = None) -> Optional[Workflow]:
        """根据名称和版本获取工作流"""
        pass
    
    @abstractmethod
    async def list(
        self,
        offset: int = 0,
        limit: int = 100,
        filters: Dict[str, Any] = None
    ) -> List[Workflow]:
        """列出工作流"""
        pass
    
    @abstractmethod
    async def update(self, workflow: Workflow) -> bool:
        """更新工作流"""
        pass
    
    @abstractmethod
    async def delete(self, workflow_id: str) -> bool:
        """删除工作流"""
        pass


class ExecutionRepository(ABC):
    """执行实例存储仓库接口"""
    
    @abstractmethod
    async def save(self, execution: WorkflowExecution) -> str:
        """保存执行实例"""
        pass
    
    @abstractmethod
    async def get(self, execution_id: str) -> Optional[WorkflowExecution]:
        """获取执行实例"""
        pass
    
    @abstractmethod
    async def list_by_workflow(
        self,
        workflow_id: str,
        status: ExecutionStatus = None,
        start_time: datetime = None,
        end_time: datetime = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[WorkflowExecution]:
        """根据工作流ID列出执行实例"""
        pass
    
    @abstractmethod
    async def list_by_status(
        self,
        status: ExecutionStatus,
        offset: int = 0,
        limit: int = 100
    ) -> List[WorkflowExecution]:
        """根据状态列出执行实例"""
        pass
    
    @abstractmethod
    async def update(self, execution: WorkflowExecution) -> bool:
        """更新执行实例"""
        pass
    
    @abstractmethod
    async def delete(self, execution_id: str) -> bool:
        """删除执行实例"""
        pass
    
    @abstractmethod
    async def cleanup_old_executions(self, days: int = 30) -> int:
        """清理旧的执行实例"""
        pass


# 内存实现（用于测试）
class InMemoryWorkflowRepository(WorkflowRepository):
    """内存工作流仓库实现"""
    
    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}
    
    async def save(self, workflow: Workflow) -> str:
        self.workflows[workflow.id] = workflow
        return workflow.id
    
    async def get(self, workflow_id: str) -> Optional[Workflow]:
        return self.workflows.get(workflow_id)
    
    async def get_by_name(self, name: str, version: str = None) -> Optional[Workflow]:
        for workflow in self.workflows.values():
            if workflow.name == name:
                if version is None or workflow.version == version:
                    return workflow
        return None
    
    async def list(
        self,
        offset: int = 0,
        limit: int = 100,
        filters: Dict[str, Any] = None
    ) -> List[Workflow]:
        workflows = list(self.workflows.values())
        return workflows[offset:offset + limit]
    
    async def update(self, workflow: Workflow) -> bool:
        if workflow.id in self.workflows:
            workflow.updated_at = datetime.utcnow()
            self.workflows[workflow.id] = workflow
            return True
        return False
    
    async def delete(self, workflow_id: str) -> bool:
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            return True
        return False


class InMemoryExecutionRepository(ExecutionRepository):
    """内存执行仓库实现"""
    
    def __init__(self):
        self.executions: Dict[str, WorkflowExecution] = {}
    
    async def save(self, execution: WorkflowExecution) -> str:
        self.executions[execution.id] = execution
        return execution.id
    
    async def get(self, execution_id: str) -> Optional[WorkflowExecution]:
        return self.executions.get(execution_id)
    
    async def list_by_workflow(
        self,
        workflow_id: str,
        status: ExecutionStatus = None,
        start_time: datetime = None,
        end_time: datetime = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[WorkflowExecution]:
        results = []
        for execution in self.executions.values():
            if execution.workflow_id == workflow_id:
                if status and execution.status != status:
                    continue
                if start_time and execution.created_at < start_time:
                    continue
                if end_time and execution.created_at > end_time:
                    continue
                results.append(execution)
        
        return results[offset:offset + limit]
    
    async def list_by_status(
        self,
        status: ExecutionStatus,
        offset: int = 0,
        limit: int = 100
    ) -> List[WorkflowExecution]:
        results = []
        for execution in self.executions.values():
            if execution.status == status:
                results.append(execution)
        
        return results[offset:offset + limit]
    
    async def update(self, execution: WorkflowExecution) -> bool:
        if execution.id in self.executions:
            execution.updated_at = datetime.utcnow()
            self.executions[execution.id] = execution
            return True
        return False
    
    async def delete(self, execution_id: str) -> bool:
        if execution_id in self.executions:
            del self.executions[execution_id]
            return True
        return False
    
    async def cleanup_old_executions(self, days: int = 30) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        to_delete = []
        
        for execution_id, execution in self.executions.items():
            if execution.created_at < cutoff_date and execution.is_terminal_state():
                to_delete.append(execution_id)
        
        for execution_id in to_delete:
            del self.executions[execution_id]
        
        return len(to_delete)
