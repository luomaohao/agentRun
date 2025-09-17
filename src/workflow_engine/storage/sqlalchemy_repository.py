"""
SQLAlchemy 仓库实现
"""
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker, selectinload
from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.exc import IntegrityError
import json

from ..models.workflow import Workflow, Node, Edge, NodeType, WorkflowType
from ..models.execution import WorkflowExecution, NodeExecution, ExecutionStatus, NodeExecutionStatus
from .repository import WorkflowRepository, ExecutionRepository
from .sqlalchemy_models import (
    WorkflowDefinition as WorkflowDefinitionDB,
    WorkflowNode as WorkflowNodeDB,
    WorkflowExecution as WorkflowExecutionDB,
    NodeExecution as NodeExecutionDB,
    ExecutionEvent as ExecutionEventDB,
    Base
)


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine: Optional[AsyncEngine] = None
        self.async_session_maker = None
    
    async def initialize(self):
        """初始化数据库连接"""
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True
        )
        
        self.async_session_maker = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 创建表（开发环境）
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def close(self):
        """关闭数据库连接"""
        if self.engine:
            await self.engine.dispose()
    
    @asynccontextmanager
    async def get_session(self):
        """获取数据库会话"""
        async with self.async_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


class SQLAlchemyWorkflowRepository(WorkflowRepository):
    """SQLAlchemy 工作流仓库实现"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    async def save(self, workflow: Workflow) -> str:
        """保存工作流"""
        async with self.db.get_session() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(WorkflowDefinitionDB).where(
                    and_(
                        WorkflowDefinitionDB.name == workflow.name,
                        WorkflowDefinitionDB.version == workflow.version
                    )
                )
            )
            if existing.scalar_one_or_none():
                raise IntegrityError("Workflow with same name and version already exists")
            
            # 创建工作流定义
            workflow_db = WorkflowDefinitionDB(
                id=workflow.id,
                name=workflow.name,
                version=workflow.version,
                type=workflow.type.value,
                definition=self._workflow_to_dict(workflow),
                description=workflow.description,
                tags=workflow.metadata.get('tags', []),
                metadata=workflow.metadata
            )
            session.add(workflow_db)
            
            # 创建节点记录
            for node in workflow.nodes:
                node_db = WorkflowNodeDB(
                    workflow_id=workflow.id,
                    node_id=node.id,
                    node_type=node.type.value,
                    node_name=node.name,
                    configuration=node.config,
                    dependencies=node.dependencies,
                    metadata=node.metadata
                )
                session.add(node_db)
            
            await session.flush()
            return workflow.id
    
    async def get(self, workflow_id: str) -> Optional[Workflow]:
        """获取工作流"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(WorkflowDefinitionDB).where(WorkflowDefinitionDB.id == workflow_id)
            )
            workflow_db = result.scalar_one_or_none()
            
            if not workflow_db:
                return None
            
            return self._db_to_workflow(workflow_db)
    
    async def get_by_name(self, name: str, version: str = None) -> Optional[Workflow]:
        """根据名称和版本获取工作流"""
        async with self.db.get_session() as session:
            query = select(WorkflowDefinitionDB).where(WorkflowDefinitionDB.name == name)
            
            if version:
                query = query.where(WorkflowDefinitionDB.version == version)
            else:
                # 获取最新版本
                query = query.order_by(WorkflowDefinitionDB.created_at.desc())
            
            result = await session.execute(query)
            workflow_db = result.first()
            
            if not workflow_db:
                return None
            
            return self._db_to_workflow(workflow_db[0])
    
    async def list(
        self,
        offset: int = 0,
        limit: int = 100,
        filters: Dict[str, Any] = None
    ) -> List[Workflow]:
        """列出工作流"""
        async with self.db.get_session() as session:
            query = select(WorkflowDefinitionDB)
            
            if filters:
                if 'is_active' in filters:
                    query = query.where(WorkflowDefinitionDB.is_active == filters['is_active'])
                if 'type' in filters:
                    query = query.where(WorkflowDefinitionDB.type == filters['type'])
                if 'tags' in filters:
                    query = query.where(WorkflowDefinitionDB.tags.contains(filters['tags']))
            
            query = query.offset(offset).limit(limit)
            query = query.order_by(WorkflowDefinitionDB.created_at.desc())
            
            result = await session.execute(query)
            workflows_db = result.scalars().all()
            
            return [self._db_to_workflow(w) for w in workflows_db]
    
    async def update(self, workflow: Workflow) -> bool:
        """更新工作流"""
        async with self.db.get_session() as session:
            result = await session.execute(
                update(WorkflowDefinitionDB)
                .where(WorkflowDefinitionDB.id == workflow.id)
                .values(
                    definition=self._workflow_to_dict(workflow),
                    description=workflow.description,
                    metadata=workflow.metadata,
                    updated_at=datetime.utcnow()
                )
            )
            
            if result.rowcount == 0:
                return False
            
            # 更新节点（简化实现：删除后重建）
            await session.execute(
                delete(WorkflowNodeDB).where(WorkflowNodeDB.workflow_id == workflow.id)
            )
            
            for node in workflow.nodes:
                node_db = WorkflowNodeDB(
                    workflow_id=workflow.id,
                    node_id=node.id,
                    node_type=node.type.value,
                    node_name=node.name,
                    configuration=node.config,
                    dependencies=node.dependencies,
                    metadata=node.metadata
                )
                session.add(node_db)
            
            return True
    
    async def delete(self, workflow_id: str) -> bool:
        """删除工作流"""
        async with self.db.get_session() as session:
            result = await session.execute(
                delete(WorkflowDefinitionDB).where(WorkflowDefinitionDB.id == workflow_id)
            )
            return result.rowcount > 0
    
    def _workflow_to_dict(self, workflow: Workflow) -> Dict[str, Any]:
        """工作流对象转字典"""
        return {
            'id': workflow.id,
            'name': workflow.name,
            'version': workflow.version,
            'type': workflow.type.value,
            'description': workflow.description,
            'nodes': [
                {
                    'id': node.id,
                    'name': node.name,
                    'type': node.type.value,
                    'subtype': node.subtype,
                    'config': node.config,
                    'inputs': node.inputs,
                    'outputs': node.outputs,
                    'dependencies': node.dependencies,
                    'timeout': node.timeout,
                    'retry_policy': node.retry_policy,
                    'metadata': node.metadata
                }
                for node in workflow.nodes
            ],
            'edges': [
                {
                    'id': edge.id,
                    'source': edge.source,
                    'target': edge.target,
                    'condition': edge.condition,
                    'data_mapping': edge.data_mapping,
                    'metadata': edge.metadata
                }
                for edge in workflow.edges
            ],
            'variables': workflow.variables,
            'triggers': workflow.triggers,
            'error_handlers': workflow.error_handlers,
            'metadata': workflow.metadata
        }
    
    def _db_to_workflow(self, workflow_db: WorkflowDefinitionDB) -> Workflow:
        """数据库对象转工作流"""
        definition = workflow_db.definition
        
        # 从定义中重建工作流对象
        workflow = Workflow(
            id=str(workflow_db.id),
            name=workflow_db.name,
            version=workflow_db.version,
            type=WorkflowType(workflow_db.type),
            description=workflow_db.description,
            variables=definition.get('variables', {}),
            triggers=definition.get('triggers', []),
            error_handlers=definition.get('error_handlers', []),
            metadata=workflow_db.metadata or {},
            created_at=workflow_db.created_at,
            updated_at=workflow_db.updated_at
        )
        
        # 重建节点
        for node_data in definition.get('nodes', []):
            node = Node(
                id=node_data['id'],
                name=node_data['name'],
                type=NodeType(node_data['type']),
                subtype=node_data.get('subtype'),
                config=node_data.get('config', {}),
                inputs=node_data.get('inputs', {}),
                outputs=node_data.get('outputs', []),
                dependencies=node_data.get('dependencies', []),
                timeout=node_data.get('timeout'),
                retry_policy=node_data.get('retry_policy'),
                metadata=node_data.get('metadata', {})
            )
            workflow.nodes.append(node)
        
        # 重建边
        for edge_data in definition.get('edges', []):
            edge = Edge(
                id=edge_data.get('id'),
                source=edge_data['source'],
                target=edge_data['target'],
                condition=edge_data.get('condition'),
                data_mapping=edge_data.get('data_mapping', {}),
                metadata=edge_data.get('metadata', {})
            )
            workflow.edges.append(edge)
        
        return workflow


class SQLAlchemyExecutionRepository(ExecutionRepository):
    """SQLAlchemy 执行仓库实现"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
    
    async def save(self, execution: WorkflowExecution) -> str:
        """保存执行实例"""
        async with self.db.get_session() as session:
            execution_db = WorkflowExecutionDB(
                id=execution.id,
                workflow_id=execution.workflow_id,
                parent_execution_id=execution.parent_execution_id,
                status=execution.status.value,
                context=self._context_to_dict(execution.context),
                input_data=execution.context.inputs,
                metadata=execution.metadata,
                created_at=execution.created_at
            )
            session.add(execution_db)
            
            await session.flush()
            return execution.id
    
    async def get(self, execution_id: str) -> Optional[WorkflowExecution]:
        """获取执行实例"""
        async with self.db.get_session() as session:
            result = await session.execute(
                select(WorkflowExecutionDB)
                .where(WorkflowExecutionDB.id == execution_id)
                .options(selectinload(WorkflowExecutionDB.node_executions))
            )
            execution_db = result.scalar_one_or_none()
            
            if not execution_db:
                return None
            
            return self._db_to_execution(execution_db)
    
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
        async with self.db.get_session() as session:
            query = select(WorkflowExecutionDB).where(
                WorkflowExecutionDB.workflow_id == workflow_id
            )
            
            if status:
                query = query.where(WorkflowExecutionDB.status == status.value)
            if start_time:
                query = query.where(WorkflowExecutionDB.created_at >= start_time)
            if end_time:
                query = query.where(WorkflowExecutionDB.created_at <= end_time)
            
            query = query.offset(offset).limit(limit)
            query = query.order_by(WorkflowExecutionDB.created_at.desc())
            
            result = await session.execute(query)
            executions_db = result.scalars().all()
            
            return [self._db_to_execution(e) for e in executions_db]
    
    async def list_by_status(
        self,
        status: ExecutionStatus,
        offset: int = 0,
        limit: int = 100
    ) -> List[WorkflowExecution]:
        """根据状态列出执行实例"""
        async with self.db.get_session() as session:
            query = select(WorkflowExecutionDB).where(
                WorkflowExecutionDB.status == status.value
            )
            
            query = query.offset(offset).limit(limit)
            query = query.order_by(WorkflowExecutionDB.created_at.desc())
            
            result = await session.execute(query)
            executions_db = result.scalars().all()
            
            return [self._db_to_execution(e) for e in executions_db]
    
    async def update(self, execution: WorkflowExecution) -> bool:
        """更新执行实例"""
        async with self.db.get_session() as session:
            # 更新主执行记录
            values = {
                'status': execution.status.value,
                'context': self._context_to_dict(execution.context),
                'error_message': execution.error_message,
                'updated_at': datetime.utcnow()
            }
            
            if execution.start_time:
                values['start_time'] = execution.start_time
            if execution.end_time:
                values['end_time'] = execution.end_time
            if execution.duration:
                values['duration_ms'] = int(execution.duration * 1000)
            
            result = await session.execute(
                update(WorkflowExecutionDB)
                .where(WorkflowExecutionDB.id == execution.id)
                .values(**values)
            )
            
            if result.rowcount == 0:
                return False
            
            # 更新节点执行记录
            for node_id, node_execution in execution.node_executions.items():
                existing = await session.execute(
                    select(NodeExecutionDB).where(
                        and_(
                            NodeExecutionDB.execution_id == execution.id,
                            NodeExecutionDB.node_id == node_id
                        )
                    )
                )
                node_db = existing.scalar_one_or_none()
                
                if node_db:
                    # 更新现有记录
                    node_values = {
                        'status': node_execution.status.value,
                        'input_data': node_execution.input_data,
                        'output_data': node_execution.output_data,
                        'error_info': node_execution.error_info,
                        'retry_count': node_execution.retry_count,
                        'updated_at': datetime.utcnow()
                    }
                    
                    if node_execution.start_time:
                        node_values['start_time'] = node_execution.start_time
                    if node_execution.end_time:
                        node_values['end_time'] = node_execution.end_time
                    if node_execution.duration:
                        node_values['duration_ms'] = int(node_execution.duration * 1000)
                    
                    await session.execute(
                        update(NodeExecutionDB)
                        .where(NodeExecutionDB.id == node_db.id)
                        .values(**node_values)
                    )
                else:
                    # 创建新记录
                    node_db = NodeExecutionDB(
                        id=node_execution.id,
                        execution_id=execution.id,
                        node_id=node_id,
                        status=node_execution.status.value,
                        input_data=node_execution.input_data,
                        output_data=node_execution.output_data,
                        error_info=node_execution.error_info,
                        retry_count=node_execution.retry_count,
                        start_time=node_execution.start_time,
                        end_time=node_execution.end_time,
                        duration_ms=int(node_execution.duration * 1000) if node_execution.duration else None,
                        metadata=node_execution.metadata
                    )
                    session.add(node_db)
            
            return True
    
    async def delete(self, execution_id: str) -> bool:
        """删除执行实例"""
        async with self.db.get_session() as session:
            result = await session.execute(
                delete(WorkflowExecutionDB).where(WorkflowExecutionDB.id == execution_id)
            )
            return result.rowcount > 0
    
    async def cleanup_old_executions(self, days: int = 30) -> int:
        """清理旧的执行实例"""
        async with self.db.get_session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            result = await session.execute(
                delete(WorkflowExecutionDB).where(
                    and_(
                        WorkflowExecutionDB.created_at < cutoff_date,
                        WorkflowExecutionDB.status.in_(['completed', 'failed', 'cancelled'])
                    )
                )
            )
            
            return result.rowcount
    
    def _context_to_dict(self, context: ExecutionContext) -> Dict[str, Any]:
        """执行上下文转字典"""
        return {
            'workflow_id': context.workflow_id,
            'execution_id': context.execution_id,
            'variables': context.variables,
            'inputs': context.inputs,
            'outputs': context.outputs,
            'metadata': context.metadata
        }
    
    def _db_to_execution(self, execution_db: WorkflowExecutionDB) -> WorkflowExecution:
        """数据库对象转执行实例"""
        context_data = execution_db.context or {}
        
        # 重建执行上下文
        context = ExecutionContext(
            workflow_id=context_data.get('workflow_id', str(execution_db.workflow_id)),
            execution_id=context_data.get('execution_id', str(execution_db.id)),
            variables=context_data.get('variables', {}),
            inputs=context_data.get('inputs', {}),
            outputs=context_data.get('outputs', {}),
            metadata=context_data.get('metadata', {})
        )
        
        # 重建执行实例
        execution = WorkflowExecution(
            id=str(execution_db.id),
            workflow_id=str(execution_db.workflow_id),
            workflow_version='',  # TODO: 从关联的工作流获取
            parent_execution_id=str(execution_db.parent_execution_id) if execution_db.parent_execution_id else None,
            status=ExecutionStatus(execution_db.status),
            context=context,
            start_time=execution_db.start_time,
            end_time=execution_db.end_time,
            duration=execution_db.duration_ms / 1000.0 if execution_db.duration_ms else None,
            error_message=execution_db.error_info.get('message') if execution_db.error_info else None,
            created_at=execution_db.created_at,
            updated_at=execution_db.updated_at,
            metadata=execution_db.metadata or {}
        )
        
        # 重建节点执行记录
        for node_db in execution_db.node_executions:
            node_execution = NodeExecution(
                id=str(node_db.id),
                execution_id=str(node_db.execution_id),
                node_id=node_db.node_id,
                status=NodeExecutionStatus(node_db.status),
                input_data=node_db.input_data or {},
                output_data=node_db.output_data or {},
                error_info=node_db.error_info,
                retry_count=node_db.retry_count,
                start_time=node_db.start_time,
                end_time=node_db.end_time,
                duration=node_db.duration_ms / 1000.0 if node_db.duration_ms else None,
                metadata=node_db.metadata or {}
            )
            execution.node_executions[node_db.node_id] = node_execution
        
        return execution
