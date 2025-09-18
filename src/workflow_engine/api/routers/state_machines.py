"""
状态机 API 路由
"""
from fastapi import APIRouter, HTTPException, Depends, Query, status
from typing import List, Optional, Dict, Any
import logging

from ..models import (
    StateTransitionRequest, StateMachineInstanceResponse,
    PaginatedResponse, SuccessResponse
)
from ..dependencies import get_workflow_engine, get_current_user, get_state_machine_engine
from ...core.state_machine import StateMachineEngine
from ...exceptions import WorkflowExecutionError, StateTransitionError


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{workflow_id}/instances", response_model=StateMachineInstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_state_machine_instance(
    workflow_id: str,
    initial_context: Dict[str, Any] = {},
    engine = Depends(get_workflow_engine),
    state_machine_engine = Depends(get_state_machine_engine),
    current_user = Depends(get_current_user)
) -> StateMachineInstanceResponse:
    """创建状态机实例"""
    try:
        # 检查工作流是否存在且是状态机类型
        workflow = await engine.workflow_repository.get(workflow_id)
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        if workflow.type.value != "state_machine":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "invalid_type",
                    "message": "Workflow is not a state machine"
                }
            )
        
        # 注册工作流到状态机引擎
        await state_machine_engine.register_workflow(workflow)
        
        # 添加元数据
        context = initial_context.copy()
        context["_metadata"] = {
            "created_by": current_user["id"]
        }
        
        # 创建实例
        instance = await state_machine_engine.create_instance(
            workflow_id=workflow_id,
            initial_context=context
        )
        
        return StateMachineInstanceResponse(
            instance_id=instance.instance_id,
            workflow_id=instance.workflow_id,
            current_state=instance.current_state,
            is_final=False,
            context=instance.context,
            created_at=instance.created_at,
            updated_at=instance.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create state machine instance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "creation_failed",
                "message": "Failed to create state machine instance"
            }
        )


@router.get("/instances/{instance_id}", response_model=StateMachineInstanceResponse)
async def get_state_machine_instance(
    instance_id: str,
    state_machine_engine = Depends(get_state_machine_engine),
    current_user = Depends(get_current_user)
) -> StateMachineInstanceResponse:
    """获取状态机实例详情"""
    try:
        instance = await state_machine_engine.get_instance(instance_id)
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"State machine instance {instance_id} not found"
                }
            )
        
        # 检查是否到达终态
        status = await state_machine_engine.get_instance_status(instance_id)
        
        return StateMachineInstanceResponse(
            instance_id=instance.instance_id,
            workflow_id=instance.workflow_id,
            current_state=instance.current_state,
            is_final=status["is_final"],
            context=instance.context,
            created_at=instance.created_at,
            updated_at=instance.updated_at
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get state machine instance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "get_failed",
                "message": "Failed to get state machine instance"
            }
        )


@router.post("/instances/{instance_id}/transition", response_model=StateMachineInstanceResponse)
async def trigger_state_transition(
    instance_id: str,
    request: StateTransitionRequest,
    state_machine_engine = Depends(get_state_machine_engine),
    current_user = Depends(get_current_user)
) -> StateMachineInstanceResponse:
    """触发状态转换"""
    try:
        # 添加触发者信息
        event_data = request.event_data.copy()
        event_data["_triggered_by"] = current_user["id"]
        
        # 处理事件
        success = await state_machine_engine.process_event(
            instance_id=instance_id,
            event=request.event,
            event_data=event_data
        )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "transition_failed",
                    "message": f"No valid transition for event '{request.event}' in current state"
                }
            )
        
        # 获取更新后的实例
        instance = await state_machine_engine.get_instance(instance_id)
        status = await state_machine_engine.get_instance_status(instance_id)
        
        return StateMachineInstanceResponse(
            instance_id=instance.instance_id,
            workflow_id=instance.workflow_id,
            current_state=instance.current_state,
            is_final=status["is_final"],
            context=instance.context,
            created_at=instance.created_at,
            updated_at=instance.updated_at
        )
        
    except HTTPException:
        raise
    except StateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "transition_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to trigger state transition: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "transition_failed",
                "message": "Failed to trigger state transition"
            }
        )


@router.get("/instances/{instance_id}/history")
async def get_state_machine_history(
    instance_id: str,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    state_machine_engine = Depends(get_state_machine_engine),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取状态机历史记录"""
    try:
        instance = await state_machine_engine.get_instance(instance_id)
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"State machine instance {instance_id} not found"
                }
            )
        
        # 获取历史记录
        history = instance.history[offset:offset + limit]
        
        return {
            "instance_id": instance_id,
            "total": len(instance.history),
            "offset": offset,
            "limit": limit,
            "history": history
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get state machine history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "get_failed",
                "message": "Failed to get state machine history"
            }
        )


@router.get("/instances/{instance_id}/available-events")
async def get_available_events(
    instance_id: str,
    state_machine_engine = Depends(get_state_machine_engine),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取当前状态可用的事件"""
    try:
        instance = await state_machine_engine.get_instance(instance_id)
        
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"State machine instance {instance_id} not found"
                }
            )
        
        # 获取工作流定义
        workflow = await engine.workflow_repository.get(instance.workflow_id)
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {instance.workflow_id} not found"
                }
            )
        
        # 查找当前状态的可用事件
        available_events = []
        
        # 这里需要从工作流定义中提取状态信息
        # 简化实现：返回示例数据
        # TODO: 实现真实的事件提取逻辑
        
        return {
            "instance_id": instance_id,
            "current_state": instance.current_state,
            "available_events": available_events,
            "is_final": await state_machine_engine.get_instance_status(instance_id).get("is_final", False)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get available events: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "get_failed",
                "message": "Failed to get available events"
            }
        )
