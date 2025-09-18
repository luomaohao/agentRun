"""
监控 API 路由
"""
from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import os

from ..models import HealthCheckResponse, MetricsResponse, PaginatedResponse
from ..dependencies import get_workflow_engine, get_current_user, get_scheduler
from ...models.execution import ExecutionStatus


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(
    engine = Depends(get_workflow_engine)
) -> HealthCheckResponse:
    """健康检查"""
    try:
        checks = {}
        
        # 检查数据库连接
        try:
            # 尝试获取一个工作流
            workflows = await engine.workflow_repository.list(limit=1)
            checks["database"] = True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            checks["database"] = False
        
        # 检查调度器
        scheduler = engine.scheduler
        checks["scheduler"] = scheduler._scheduler_task is not None and not scheduler._scheduler_task.done()
        
        # 检查事件总线
        checks["event_bus"] = True  # 简化实现
        
        # 检查智能体运行时
        try:
            agents = await engine.agent_runtime.list_agents()
            checks["agent_runtime"] = True
        except Exception:
            checks["agent_runtime"] = False
        
        # 检查工具注册表
        try:
            tools = await engine.tool_registry.list_tools()
            checks["tool_registry"] = True
        except Exception:
            checks["tool_registry"] = False
        
        # 总体健康状态
        all_healthy = all(checks.values())
        
        return HealthCheckResponse(
            status="healthy" if all_healthy else "unhealthy",
            version="1.0.0",
            timestamp=datetime.utcnow(),
            checks=checks
        )
        
    except Exception as e:
        logger.error(f"Health check error: {e}", exc_info=True)
        return HealthCheckResponse(
            status="unhealthy",
            version="1.0.0",
            timestamp=datetime.utcnow(),
            checks={"error": str(e)}
        )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    time_range: str = Query("24h", description="时间范围", regex="^\\d+[hdm]$"),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> MetricsResponse:
    """获取系统指标"""
    try:
        # 解析时间范围
        unit = time_range[-1]
        value = int(time_range[:-1])
        
        if unit == 'h':
            delta = timedelta(hours=value)
        elif unit == 'd':
            delta = timedelta(days=value)
        elif unit == 'm':
            delta = timedelta(minutes=value)
        else:
            delta = timedelta(hours=24)
        
        start_time = datetime.utcnow() - delta
        
        # 获取活跃工作流数
        workflows = await engine.workflow_repository.list(filters={"is_active": True})
        active_workflows = len(workflows)
        
        # 获取执行统计
        # TODO: 实现真实的统计查询
        total_executions = 1000  # 示例数据
        
        # 获取运行中的执行数
        running_executions_list = await engine.execution_repository.list_by_status(
            status=ExecutionStatus.RUNNING,
            limit=1000
        )
        running_executions = len(running_executions_list)
        
        # 获取失败执行数
        failed_executions_list = await engine.execution_repository.list_by_status(
            status=ExecutionStatus.FAILED,
            limit=1000
        )
        # 过滤24小时内的
        failed_executions_24h = sum(
            1 for e in failed_executions_list
            if e.created_at >= start_time
        )
        
        # 计算平均执行时间
        completed_executions = await engine.execution_repository.list_by_status(
            status=ExecutionStatus.COMPLETED,
            limit=100
        )
        
        if completed_executions:
            avg_duration = sum(
                e.duration for e in completed_executions if e.duration
            ) / len(completed_executions)
            avg_execution_time_ms = avg_duration * 1000
        else:
            avg_execution_time_ms = 0.0
        
        # 获取资源使用情况
        scheduler_stats = engine.scheduler.get_scheduler_stats()
        resource_usage = {
            "scheduler": scheduler_stats,
            "memory_mb": 0,  # TODO: 实现内存统计
            "cpu_percent": 0  # TODO: 实现CPU统计
        }
        
        return MetricsResponse(
            active_workflows=active_workflows,
            total_executions=total_executions,
            running_executions=running_executions,
            failed_executions_24h=failed_executions_24h,
            avg_execution_time_ms=avg_execution_time_ms,
            resource_usage=resource_usage
        )
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "metrics_error",
                "message": "Failed to get metrics"
            }
        )


@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query("INFO", description="日志级别"),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(100, ge=1, le=1000, description="每页数量"),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取系统日志"""
    try:
        # 检查权限
        if current_user["role"] not in ["admin", "operator"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": "Insufficient permissions to view logs"
                }
            )
        
        # TODO: 实现真实的日志查询
        # 这里返回示例数据
        logs = [
            {
                "timestamp": datetime.utcnow().isoformat(),
                "level": "INFO",
                "logger": "workflow_engine",
                "message": "Workflow execution started",
                "context": {
                    "workflow_id": "example-workflow",
                    "execution_id": "example-execution"
                }
            }
        ]
        
        return {
            "total": len(logs),
            "offset": offset,
            "limit": limit,
            "logs": logs
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get logs: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "logs_error",
                "message": "Failed to get logs"
            }
        )


@router.get("/traces/{execution_id}")
async def get_execution_trace(
    execution_id: str,
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """获取执行追踪信息"""
    try:
        # 获取执行信息
        execution = await engine.execution_repository.get(execution_id)
        
        if not execution:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "not_found",
                    "message": f"Execution {execution_id} not found"
                }
            )
        
        # 构建追踪信息
        trace = {
            "execution_id": execution_id,
            "workflow_id": execution.workflow_id,
            "start_time": execution.start_time.isoformat() if execution.start_time else None,
            "end_time": execution.end_time.isoformat() if execution.end_time else None,
            "duration_ms": int(execution.duration * 1000) if execution.duration else None,
            "status": execution.status.value,
            "spans": []
        }
        
        # 添加节点执行跨度
        for node_id, node_exec in execution.node_executions.items():
            span = {
                "span_id": node_exec.id,
                "node_id": node_id,
                "operation": f"node.execute.{node_id}",
                "start_time": node_exec.start_time.isoformat() if node_exec.start_time else None,
                "end_time": node_exec.end_time.isoformat() if node_exec.end_time else None,
                "duration_ms": int(node_exec.duration * 1000) if node_exec.duration else None,
                "status": node_exec.status.value,
                "attributes": {
                    "retry_count": node_exec.retry_count
                }
            }
            
            if node_exec.error_info:
                span["error"] = node_exec.error_info
            
            trace["spans"].append(span)
        
        # 按开始时间排序
        trace["spans"].sort(key=lambda x: x["start_time"] or "")
        
        return trace
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get execution trace: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "trace_error",
                "message": "Failed to get execution trace"
            }
        )


@router.post("/alerts/test")
async def test_alert(
    alert_type: str = Query(..., description="告警类型"),
    message: str = Query(..., description="告警消息"),
    engine = Depends(get_workflow_engine),
    current_user = Depends(get_current_user)
) -> Dict[str, Any]:
    """测试告警"""
    try:
        # 检查权限
        if current_user["role"] not in ["admin", "operator"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "forbidden",
                    "message": "Insufficient permissions to test alerts"
                }
            )
        
        # 发布告警事件
        await engine.event_bus.publish(
            "monitoring.alert",
            {
                "type": alert_type,
                "message": message,
                "timestamp": datetime.utcnow().isoformat(),
                "triggered_by": current_user["id"],
                "test": True
            }
        )
        
        return {
            "success": True,
            "message": "Test alert sent successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test alert: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "alert_error",
                "message": "Failed to test alert"
            }
        )
