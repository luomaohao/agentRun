"""
API 中间件
"""
import time
import uuid
import logging
from typing import Callable
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import jwt
from datetime import datetime, timedelta
import os


logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 生成请求ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 记录请求信息
        logger.info(
            f"Request started: {request.method} {request.url.path} "
            f"[request_id={request_id}]"
        )
        
        # 处理请求
        response = await call_next(request)
        
        # 计算处理时间
        duration = time.time() - start_time
        
        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(duration)
        
        # 记录响应信息
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"[request_id={request_id}] "
            f"[status={response.status_code}] "
            f"[duration={duration:.3f}s]"
        )
        
        return response


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """认证中间件"""
    
    # 不需要认证的路径
    EXCLUDE_PATHS = [
        "/",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/v1/monitoring/health",
        "/api/v1/auth/login"
    ]
    
    def __init__(self, app):
        super().__init__(app)
        self.secret_key = os.getenv("JWT_SECRET_KEY", "your-secret-key-here")
        self.algorithm = "HS256"
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 检查是否需要认证
        if request.url.path in self.EXCLUDE_PATHS:
            return await call_next(request)
        
        # 开发模式下跳过认证
        if os.getenv("DISABLE_AUTH", "false").lower() == "true":
            request.state.user = {"id": "dev-user", "role": "admin"}
            return await call_next(request)
        
        # 获取token
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "unauthorized",
                    "message": "Missing or invalid authorization header"
                }
            )
        
        token = authorization.split(" ")[1]
        
        try:
            # 验证token
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # 检查过期时间
            exp = payload.get("exp")
            if exp and datetime.fromtimestamp(exp) < datetime.utcnow():
                raise jwt.ExpiredSignatureError()
            
            # 设置用户信息
            request.state.user = {
                "id": payload.get("sub"),
                "role": payload.get("role", "user"),
                "permissions": payload.get("permissions", [])
            }
            
            return await call_next(request)
            
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "token_expired",
                    "message": "Token has expired"
                }
            )
        except jwt.InvalidTokenError:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "error": "invalid_token",
                    "message": "Invalid token"
                }
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "authentication_error",
                    "message": "Authentication failed"
                }
            )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""
    
    def __init__(self, app, rate: int = 60, window: int = 60):
        super().__init__(app)
        self.rate = rate  # 每个时间窗口的请求数
        self.window = window  # 时间窗口（秒）
        self.requests = {}  # 存储请求记录
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 获取客户端标识
        client_id = self._get_client_id(request)
        current_time = time.time()
        
        # 清理过期记录
        self._cleanup_old_requests(client_id, current_time)
        
        # 检查速率限制
        if client_id not in self.requests:
            self.requests[client_id] = []
        
        request_times = self.requests[client_id]
        
        if len(request_times) >= self.rate:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Maximum {self.rate} requests per {self.window} seconds.",
                    "retry_after": self.window
                }
            )
        
        # 记录请求
        request_times.append(current_time)
        
        # 处理请求
        response = await call_next(request)
        
        # 添加速率限制头
        response.headers["X-RateLimit-Limit"] = str(self.rate)
        response.headers["X-RateLimit-Remaining"] = str(self.rate - len(request_times))
        response.headers["X-RateLimit-Reset"] = str(int(current_time + self.window))
        
        return response
    
    def _get_client_id(self, request: Request) -> str:
        """获取客户端标识"""
        # 优先使用用户ID
        if hasattr(request.state, "user") and request.state.user:
            return f"user:{request.state.user['id']}"
        
        # 使用IP地址
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        
        return f"ip:{ip}"
    
    def _cleanup_old_requests(self, client_id: str, current_time: float):
        """清理过期的请求记录"""
        if client_id in self.requests:
            cutoff_time = current_time - self.window
            self.requests[client_id] = [
                t for t in self.requests[client_id] if t > cutoff_time
            ]
            
            # 如果没有请求记录，删除客户端记录
            if not self.requests[client_id]:
                del self.requests[client_id]
