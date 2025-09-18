"""
FastAPI 依赖注入
"""
from fastapi import Depends, HTTPException, status, Header
from typing import Dict, Any, Optional
import logging

from .app import get_app_state
from ..core import WorkflowEngine, TaskScheduler
from ..core.state_machine import StateMachineEngine
from ..integrations.event_bus import EventBus


logger = logging.getLogger(__name__)


def get_workflow_engine() -> WorkflowEngine:
    """获取工作流引擎实例"""
    app_state = get_app_state()
    engine = app_state.get("engine")
    
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Workflow engine not initialized"
            }
        )
    
    return engine


def get_scheduler() -> TaskScheduler:
    """获取调度器实例"""
    app_state = get_app_state()
    scheduler = app_state.get("scheduler")
    
    if not scheduler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Scheduler not initialized"
            }
        )
    
    return scheduler


def get_event_bus() -> EventBus:
    """获取事件总线实例"""
    app_state = get_app_state()
    event_bus = app_state.get("event_bus")
    
    if not event_bus:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "service_unavailable",
                "message": "Event bus not initialized"
            }
        )
    
    return event_bus


# 状态机引擎缓存
_state_machine_engine: Optional[StateMachineEngine] = None


def get_state_machine_engine(
    event_bus: EventBus = Depends(get_event_bus)
) -> StateMachineEngine:
    """获取状态机引擎实例"""
    global _state_machine_engine
    
    if not _state_machine_engine:
        _state_machine_engine = StateMachineEngine(event_bus)
    
    return _state_machine_engine


def get_current_user(
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """获取当前用户信息"""
    # 开发模式下返回默认用户
    import os
    if os.getenv("DISABLE_AUTH", "false").lower() == "true":
        return {
            "id": "dev-user",
            "username": "developer",
            "role": "admin",
            "permissions": ["*"]
        }
    
    # 从请求头获取用户信息（由中间件设置）
    # TODO: 实现真实的用户获取逻辑
    return {
        "id": "anonymous",
        "username": "anonymous",
        "role": "user",
        "permissions": ["read"]
    }


def require_permission(permission: str):
    """权限检查依赖"""
    def permission_checker(
        current_user: Dict[str, Any] = Depends(get_current_user)
    ) -> Dict[str, Any]:
        # 检查用户权限
        user_permissions = current_user.get("permissions", [])
        
        # 管理员拥有所有权限
        if current_user.get("role") == "admin" or "*" in user_permissions:
            return current_user
        
        # 检查特定权限
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": f"Permission '{permission}' required"
                }
            )
        
        return current_user
    
    return permission_checker


# 常用权限检查
require_admin = require_permission("admin")
require_write = require_permission("write")
require_execute = require_permission("execute")
