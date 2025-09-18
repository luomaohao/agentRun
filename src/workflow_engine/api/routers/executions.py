"""
工作流执行 API 路由
"""
from fastapi import APIRouter, HTTPException, Depends, Query, status, WebSocket, WebSocketDisconnect
from typing import List, Optional, Dict, Any
import asyncio
import json
import logging

from ..models import (
    WorkflowExecuteRequest, ExecutionResponse, ExecutionDetailResponse,
    PaginatedResponse, SuccessResponse, ExecutionStatusEnum
)
from ..dependencies import get_workflow_engine, get_current_user, get_event_bus
from ...exceptions import WorkflowExecutionError
from ...models.execution import ExecutionStatus


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{workflow_id}/execute", response_model=ExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> ExecutionResponse:
    """执行工作流"""
    try:
        # 检查工作流是否存在
        workflow = await engine.workflow_repository.get(workflow_id)
        if not workflow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Workflow {workflow_id} not found"
                }
            )
        
        # 添加执行元数据
        context = request.context.copy()
        context["_metadata"] = {
            "triggered_by": current_user["id"],
            "trigger_type": "api",
            "priority": request.priority,
            **request.metadata
        }
        
        # 执行工作流
        execution_id = await engine.execute_workflow(
            workflow_id=workflow_id,
            context=context,
            async_mode=request.async_mode
        )
        
        # 获取执行信息
        execution = await engine.execution_repository.get(execution_id)
        
        return ExecutionResponse(
            execution_id=execution.id,
            workflow_id=execution.workflow_id,
            status=execution.status.value,
            start_time=execution.start_time,
            end_time=execution.end_time,
            duration_ms=int(execution.duration * 1000) if execution.duration else None,
            error_message=execution.error_message,
            created_at=execution.created_at
        )
        
    except HTTPException:
        raise
    except WorkflowExecutionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "execution_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to execute workflow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "execution_failed",
                "message": "Failed to execute workflow"
            }
        )


@router.get("/", response_model=PaginatedResponse)
async def list_executions(
    workflow_id: Optional[str] = Query(None, description="工作流ID"),
    status: Optional[ExecutionStatusEnum] = Query(None, description="执行状态"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> PaginatedResponse:
    """列出执行实例"""
    try:
        if workflow_id:
            # 按工作流ID列出
            executions = await engine.execution_repository.list_by_workflow(
                workflow_id=workflow_id,
                status=ExecutionStatus(status.value) if status else None,
                offset=offset,
                limit=limit
            )
        elif status:
            # 按状态列出
            executions = await engine.execution_repository.list_by_status(
                status=ExecutionStatus(status.value),
                offset=offset,
                limit=limit
            )
        else:
            # TODO: 实现全量列表
            executions = []
        
        # 转换为响应模型
        items = [
            ExecutionResponse(
                execution_id=e.id,
                workflow_id=e.workflow_id,
                status=e.status.value,
                start_time=e.start_time,
                end_time=e.end_time,
                duration_ms=int(e.duration * 1000) if e.duration else None,
                error_message=e.error_message,
                created_at=e.created_at
            )
            for e in executions
        ]
        
        # TODO: 获取总数
        total = len(executions) + offset
        
        return PaginatedResponse(
            total=total,
            offset=offset,
            limit=limit,
            items=items
        )
        
    except Exception as e:
        logger.error(f"Failed to list executions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "list_failed",
                "message": "Failed to list executions"
            }
        )


@router.get("/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> ExecutionDetailResponse:
    """获取执行详情"""
    try:
        execution = await engine.execution_repository.get(execution_id)
        
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Execution {execution_id} not found"
                }
            )
        
        # 构建节点执行信息
        node_executions = [
            {
                "node_id": ne.node_id,
                "status": ne.status.value,
                "start_time": ne.start_time,
                "end_time": ne.end_time,
                "duration_ms": int(ne.duration * 1000) if ne.duration else None,
                "retry_count": ne.retry_count,
                "error_info": ne.error_info
            }
            for ne in execution.node_executions.values()
        ]
        
        return ExecutionDetailResponse(
            execution_id=execution.id,
            workflow_id=execution.workflow_id,
            status=execution.status.value,
            start_time=execution.start_time,
            end_time=execution.end_time,
            duration_ms=int(execution.duration * 1000) if execution.duration else None,
            error_message=execution.error_message,
            created_at=execution.created_at,
            context=execution.context.variables,
            input_data=execution.context.inputs,
            output_data=execution.context.outputs,
            node_executions=node_executions,
            metadata=execution.metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "get_failed",
                "message": "Failed to get execution"
            }
        )


@router.post("/{execution_id}/cancel", response_model=SuccessResponse)
async def cancel_execution(
    execution_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> SuccessResponse:
    """取消执行"""
    try:
        await engine.cancel_execution(execution_id)
        
        return SuccessResponse(
            success=True,
            message=f"Execution {execution_id} cancelled successfully"
        )
        
    except WorkflowExecutionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "cancel_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to cancel execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "cancel_failed",
                "message": "Failed to cancel execution"
            }
        )


@router.post("/{execution_id}/suspend", response_model=SuccessResponse)
async def suspend_execution(
    execution_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> SuccessResponse:
    """暂停执行"""
    try:
        await engine.suspend_execution(execution_id)
        
        return SuccessResponse(
            success=True,
            message=f"Execution {execution_id} suspended successfully"
        )
        
    except WorkflowExecutionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "suspend_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to suspend execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "suspend_failed",
                "message": "Failed to suspend execution"
            }
        )


@router.post("/{execution_id}/resume", response_model=SuccessResponse)
async def resume_execution(
    execution_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> SuccessResponse:
    """恢复执行"""
    try:
        await engine.resume_execution(execution_id)
        
        return SuccessResponse(
            success=True,
            message=f"Execution {execution_id} resumed successfully"
        )
        
    except WorkflowExecutionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "resume_error",
                "message": str(e)
            }
        )
    except Exception as e:
        logger.error(f"Failed to resume execution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "resume_failed",
                "message": "Failed to resume execution"
            }
        )


@router.websocket("/{execution_id}/stream")
async def stream_execution(
    websocket: WebSocket,
    execution_id: str,
    engine = Depends(get_workflow_engine),
    event_bus = Depends(get_event_bus)
):
    """实时流式推送执行状态"""
    await websocket.accept()
    
    try:
        # 验证执行是否存在
        execution = await engine.execution_repository.get(execution_id)
        if not execution:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "error": "not_found",
                    "message": f"Execution {execution_id} not found"
                }
            })
            await websocket.close()
            return
        
        # 发送初始状态
        await websocket.send_json({
            "type": "initial_state",
            "data": {
                "execution_id": execution.id,
                "status": execution.status.value,
                "start_time": execution.start_time.isoformat() if execution.start_time else None
            }
        })
        
        # 订阅执行事件
        event_queue = asyncio.Queue()
        
        async def event_handler(event):
            if event.payload.get("execution_id") == execution_id:
                await event_queue.put(event)
        
        await event_bus.subscribe("workflow.execution.events", event_handler)
        await event_bus.subscribe("workflow.node.events", event_handler)
        
        # 推送事件
        try:
            while True:
                # 检查WebSocket消息
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                    # 处理客户端消息（如心跳）
                    if message == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    pass
                
                # 检查事件队列
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                    await websocket.send_json({
                        "type": "event",
                        "data": {
                            "event_type": event.topic,
                            "timestamp": event.timestamp.isoformat(),
                            "payload": event.payload
                        }
                    })
                    
                    # 检查是否为终止事件
                    if event.topic in ["workflow.execution.completed", 
                                     "workflow.execution.failed", 
                                     "workflow.execution.cancelled"]:
                        break
                        
                except asyncio.TimeoutError:
                    pass
                
        finally:
            await event_bus.unsubscribe("workflow.execution.events", event_handler)
            await event_bus.unsubscribe("workflow.node.events", event_handler)
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for execution {execution_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        await websocket.send_json({
            "type": "error",
            "data": {
                "error": "internal_error",
                "message": str(e)
            }
        })
    finally:
        await websocket.close()
