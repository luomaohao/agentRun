"""
工作流管理 API 路由
"""
from fastapi import APIRouter, HTTPException, Depends, Query, status, UploadFile, File
from typing import List, Optional, Dict, Any
from uuid import uuid4
import yaml
import json
import logging

from ..models import (
    WorkflowCreateRequest, WorkflowUpdateRequest, WorkflowResponse,
    WorkflowDetailResponse, PaginationParams, PaginatedResponse,
    ErrorResponse, SuccessResponse
)
from ..dependencies import get_workflow_engine, get_current_user
from ...exceptions import WorkflowValidationError, WorkflowEngineError


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow: WorkflowCreateRequest,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> WorkflowResponse:
    """创建新的工作流"""
    try:
        # 构建工作流定义
        workflow_def = {
            "workflow": {
                "id": str(uuid4()),
                "name": workflow.name,
                "version": workflow.version,
                "type": workflow.type.value,
                "description": workflow.description,
                "nodes": [node.model_dump() for node in workflow.nodes],
                "edges": [edge.model_dump() for edge in (workflow.edges or [])],
                "variables": workflow.variables,
                "triggers": workflow.triggers,
                "error_handlers": workflow.error_handlers,
                "metadata": {
                    **workflow.metadata,
                    "created_by": current_user["id"]
                }
            }
        }
        
        # 创建工作流
        workflow_id = await engine.create_workflow(workflow_def)
        
        # 获取创建的工作流
        created_workflow = await engine.workflow_repository.get(workflow_id)
        
        return WorkflowResponse(
            id=created_workflow.id,
            name=created_workflow.name,
            version=created_workflow.version,
            type=created_workflow.type.value,
            description=created_workflow.description,
            is_active=True,
            node_count=len(created_workflow.nodes),
            created_at=created_workflow.created_at,
            updated_at=created_workflow.updated_at,
            metadata=created_workflow.metadata
        )
        
    except WorkflowValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "validation_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to create workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "creation_failed",
                "message": "Failed to create workflow"
            }
        )


@router.post("/upload", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def upload_workflow(
    file: UploadFile = File(...),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> WorkflowResponse:
    """上传工作流文件（YAML/JSON）"""
    try:
        # 读取文件内容
        content = await file.read()
        
        # 解析文件
        if file.filename.endswith(('.yaml', '.yml')):
            workflow_def = yaml.safe_load(content)
        elif file.filename.endswith('.json'):
            workflow_def = json.loads(content)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_file_type",
                    "message": "Only YAML and JSON files are supported"
                }
            )
        
        # 添加元数据
        if 'workflow' in workflow_def:
            workflow_def['workflow']['metadata'] = workflow_def['workflow'].get('metadata', {})
            workflow_def['workflow']['metadata']['created_by'] = current_user["id"]
            workflow_def['workflow']['metadata']['uploaded_filename'] = file.filename
        
        # 创建工作流
        workflow_id = await engine.create_workflow(workflow_def)
        
        # 获取创建的工作流
        created_workflow = await engine.workflow_repository.get(workflow_id)
        
        return WorkflowResponse(
            id=created_workflow.id,
            name=created_workflow.name,
            version=created_workflow.version,
            type=created_workflow.type.value,
            description=created_workflow.description,
            is_active=True,
            node_count=len(created_workflow.nodes),
            created_at=created_workflow.created_at,
            updated_at=created_workflow.updated_at,
            metadata=created_workflow.metadata
        )
        
    except Exception as e:
        logger.error(f"Failed to upload workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "upload_failed",
                "message": str(e)
            }
        )


@router.get("/", response_model=PaginatedResponse)
async def list_workflows(
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    is_active: Optional[bool] = Query(None, description="是否激活"),
    type: Optional[str] = Query(None, description="工作流类型"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> PaginatedResponse:
    """列出工作流"""
    try:
        # 构建过滤条件
        filters = {}
        if is_active is not None:
            filters['is_active'] = is_active
        if type:
            filters['type'] = type
        
        # 获取工作流列表
        workflows = await engine.workflow_repository.list(
            offset=offset,
            limit=limit,
            filters=filters
        )
        
        # 转换为响应模型
        items = [
            WorkflowResponse(
                id=w.id,
                name=w.name,
                version=w.version,
                type=w.type.value,
                description=w.description,
                is_active=True,  # TODO: 从数据库获取
                node_count=len(w.nodes),
                created_at=w.created_at,
                updated_at=w.updated_at,
                metadata=w.metadata
            )
            for w in workflows
        ]
        
        # TODO: 获取总数
        total = len(workflows) + offset
        
        return PaginatedResponse(
            total=total,
            offset=offset,
            limit=limit,
            items=items
        )
        
    except Exception as e:
        logger.error(f"Failed to list workflows: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "list_failed",
                "message": "Failed to list workflows"
            }
        )


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
    workflow_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> WorkflowDetailResponse:
    """获取工作流详情"""
    try:
        workflow = await engine.workflow_repository.get(workflow_id)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        return WorkflowDetailResponse(
            id=workflow.id,
            name=workflow.name,
            version=workflow.version,
            type=workflow.type.value,
            description=workflow.description,
            is_active=True,
            node_count=len(workflow.nodes),
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            metadata=workflow.metadata,
            nodes=[
                {
                    "id": node.id,
                    "name": node.name,
                    "type": node.type.value,
                    "subtype": node.subtype,
                    "config": node.config,
                    "inputs": node.inputs,
                    "outputs": node.outputs,
                    "dependencies": node.dependencies,
                    "timeout": node.timeout,
                    "retry_policy": node.retry_policy,
                    "metadata": node.metadata
                }
                for node in workflow.nodes
            ],
            edges=[
                {
                    "source": edge.source,
                    "target": edge.target,
                    "condition": edge.condition,
                    "data_mapping": edge.data_mapping,
                    "metadata": edge.metadata
                }
                for edge in workflow.edges
            ],
            variables=workflow.variables,
            triggers=workflow.triggers,
            error_handlers=workflow.error_handlers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "get_failed",
                "message": "Failed to get workflow"
            }
        )


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    update: WorkflowUpdateRequest,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> WorkflowResponse:
    """更新工作流"""
    try:
        workflow = await engine.workflow_repository.get(workflow_id)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        # 更新字段
        if update.description is not None:
            workflow.description = update.description
        if update.metadata is not None:
            workflow.metadata.update(update.metadata)
        
        workflow.metadata["updated_by"] = current_user["id"]
        
        # 保存更新
        success = await engine.workflow_repository.update(workflow)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "update_failed",
                    "message": "Failed to update workflow"
                }
            )
        
        # 重新获取更新后的工作流
        updated_workflow = await engine.workflow_repository.get(workflow_id)
        
        return WorkflowResponse(
            id=updated_workflow.id,
            name=updated_workflow.name,
            version=updated_workflow.version,
            type=updated_workflow.type.value,
            description=updated_workflow.description,
            is_active=update.is_active if update.is_active is not None else True,
            node_count=len(updated_workflow.nodes),
            created_at=updated_workflow.created_at,
            updated_at=updated_workflow.updated_at,
            metadata=updated_workflow.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "update_failed",
                "message": "Failed to update workflow"
            }
        )


@router.delete("/{workflow_id}", response_model=SuccessResponse)
async def delete_workflow(
    workflow_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> SuccessResponse:
    """删除工作流"""
    try:
        # 检查权限
        if current_user["role"] != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": "Only admin users can delete workflows"
                }
            )
        
        success = await engine.workflow_repository.delete(workflow_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        return SuccessResponse(
            success=True,
            message=f"Workflow {workflow_id} deleted successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "delete_failed",
                "message": "Failed to delete workflow"
            }
        )


@router.post("/{workflow_id}/validate", response_model=SuccessResponse)
async def validate_workflow(
    workflow_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> SuccessResponse:
    """验证工作流"""
    try:
        workflow = await engine.workflow_repository.get(workflow_id)
        
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        # 验证工作流
        errors = workflow.validate()
        
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "validation_failed",
                    "message": "Workflow validation failed",
                    "errors": errors
                }
            )
        
        return SuccessResponse(
            success=True,
            message="Workflow is valid"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "validation_error",
                "message": "Failed to validate workflow"
            }
        )
