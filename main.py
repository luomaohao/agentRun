"""
Agent Workflow Runtime API 主入口
"""
import os
import logging
import uvicorn
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 导入应用
from src.workflow_engine.api import app


if __name__ == "__main__":
    # 获取配置
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "true").lower() == "true"
    workers = int(os.getenv("API_WORKERS", "1"))
    
    # 启动服务器
    if reload:
        # 开发模式
        uvicorn.run(
            "src.workflow_engine.api:app",
            host=host,
            port=port,
            reload=True,
            log_level="info"
        )
    else:
        # 生产模式
        uvicorn.run(
            app,
            host=host,
            port=port,
            workers=workers,
            log_level="info"
        )
