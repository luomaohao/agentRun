"""
智能体运行时集成 - 负责管理和调度智能体
"""
from typing import Dict, Any, Optional, List, Union, Type
from abc import ABC, abstractmethod
import logging
import asyncio
from datetime import datetime
from collections import defaultdict
import json

from .models import (
    AgentConfig, AgentResponse, AgentStatus,
    BatchRequest, BatchResponse, AgentSession
)
from .agent import Agent, LLMAgent, RuleBasedAgent
from .exceptions import (
    AgentNotFoundError, AgentExecutionError,
    AgentTimeoutError, AgentRateLimitError,
    AgentAuthenticationError, AgentConfigError
)
from .validators import SchemaValidator


logger = logging.getLogger(__name__)


class AgentRuntime(ABC):
    """智能体运行时接口 - 负责管理和调度智能体"""
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.configs: Dict[str, AgentConfig] = {}
        self.sessions: Dict[str, AgentSession] = {}
        self.rate_limiters: Dict[str, Any] = {}
        self.validator = SchemaValidator()
        self._initialize()
    
    def _initialize(self):
        """初始化运行时"""
        logger.info("Initializing agent runtime")
    
    @abstractmethod
    async def create_agent(self, config: AgentConfig) -> Agent:
        """创建智能体实例"""
        pass
    
    async def register_agent(self, config: AgentConfig) -> str:
        """注册智能体"""
        try:
            # 验证配置
            self._validate_config(config)
            
            # 创建智能体实例
            agent = await self.create_agent(config)
            
            # 存储
            self.agents[config.agent_id] = agent
            self.configs[config.agent_id] = config
            
            logger.info(f"Registered agent: {config.agent_id}")
            return config.agent_id
            
        except Exception as e:
            logger.error(f"Failed to register agent {config.agent_id}: {str(e)}")
            raise AgentConfigError(f"Agent registration failed: {str(e)}")
    
    async def update_agent_config(
        self, 
        agent_id: str, 
        config_updates: Dict[str, Any]
    ) -> AgentConfig:
        """更新智能体配置"""
        if agent_id not in self.configs:
            raise AgentNotFoundError(agent_id)
        
        # 获取现有配置
        current_config = self.configs[agent_id]
        
        # 更新配置
        for key, value in config_updates.items():
            if hasattr(current_config, key):
                setattr(current_config, key, value)
        
        current_config.updated_at = datetime.now()
        
        # 重新创建智能体实例
        agent = await self.create_agent(current_config)
        self.agents[agent_id] = agent
        
        logger.info(f"Updated agent config: {agent_id}")
        return current_config
    
    async def delete_agent(self, agent_id: str):
        """删除智能体"""
        if agent_id not in self.agents:
            raise AgentNotFoundError(agent_id)
        
        del self.agents[agent_id]
        del self.configs[agent_id]
        
        # 清理相关会话
        sessions_to_remove = [
            sid for sid, session in self.sessions.items() 
            if session.agent_id == agent_id
        ]
        for sid in sessions_to_remove:
            del self.sessions[sid]
        
        logger.info(f"Deleted agent: {agent_id}")
    
    async def invoke_agent(
        self,
        agent_id: str,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> AgentResponse:
        """调用智能体"""
        # 获取智能体
        agent = self.agents.get(agent_id)
        if not agent:
            raise AgentNotFoundError(agent_id)
        
        # 检查是否启用
        config = self.configs[agent_id]
        if not config.enabled:
            raise AgentExecutionError("Agent is disabled", agent_id)
        
        # 检查速率限制
        if await self._check_rate_limit(agent_id):
            raise AgentRateLimitError(agent_id, "requests_per_minute")
        
        # 获取或创建会话
        session = self._get_or_create_session(session_id, agent_id)
        
        # 合并上下文
        full_context = {**(session.context or {}), **(context or {})}
        
        # 设置超时
        timeout_seconds = timeout or config.timeout_seconds
        
        try:
            # 异步调用，支持超时
            response = await asyncio.wait_for(
                agent.handle(input_data, full_context),
                timeout=timeout_seconds
            )
            
            # 更新会话
            session.add_interaction(input_data, response)
            
            return response
            
        except asyncio.TimeoutError:
            raise AgentTimeoutError(agent_id, timeout_seconds)
        except Exception as e:
            logger.error(f"Agent {agent_id} execution failed: {str(e)}", exc_info=True)
            raise AgentExecutionError(f"Execution failed: {str(e)}", agent_id, e)
    
    async def invoke_batch(
        self,
        batch_request: BatchRequest
    ) -> BatchResponse:
        """批量调用智能体"""
        start_time = datetime.now()
        responses = []
        
        if batch_request.parallel:
            # 并行执行
            tasks = [
                self.invoke_agent(
                    batch_request.agent_id,
                    request,
                    batch_request.context,
                    timeout=batch_request.timeout_seconds
                )
                for request in batch_request.requests
            ]
            
            # 使用gather允许部分失败
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    # 创建错误响应
                    responses.append(AgentResponse(
                        agent_id=batch_request.agent_id,
                        output={},
                        status="error",
                        error=str(result),
                        error_type=type(result).__name__,
                        duration_ms=0
                    ))
                else:
                    responses.append(result)
        else:
            # 顺序执行
            for request in batch_request.requests:
                try:
                    response = await self.invoke_agent(
                        batch_request.agent_id,
                        request,
                        batch_request.context,
                        timeout=batch_request.timeout_seconds
                    )
                    responses.append(response)
                except Exception as e:
                    responses.append(AgentResponse(
                        agent_id=batch_request.agent_id,
                        output={},
                        status="error",
                        error=str(e),
                        error_type=type(e).__name__,
                        duration_ms=0
                    ))
        
        # 计算总时间
        total_duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        
        return BatchResponse(
            request_id=batch_request.request_id,
            responses=responses,
            total_duration_ms=total_duration_ms
        )
    
    async def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """获取智能体配置"""
        return self.configs.get(agent_id)
    
    async def get_agent(self, agent_id: str) -> Optional[Agent]:
        """获取智能体实例"""
        return self.agents.get(agent_id)
    
    async def list_agents(
        self, 
        enabled_only: bool = False,
        tags: Optional[List[str]] = None
    ) -> List[AgentConfig]:
        """列出所有智能体"""
        configs = list(self.configs.values())
        
        # 过滤启用状态
        if enabled_only:
            configs = [c for c in configs if c.enabled]
        
        # 过滤标签
        if tags:
            configs = [
                c for c in configs 
                if any(tag in c.tags for tag in tags)
            ]
        
        return configs
    
    def create_session(
        self, 
        agent_id: str, 
        user_id: Optional[str] = None
    ) -> AgentSession:
        """创建会话"""
        if agent_id not in self.agents:
            raise AgentNotFoundError(agent_id)
        
        session = AgentSession(
            agent_id=agent_id,
            user_id=user_id
        )
        self.sessions[session.session_id] = session
        
        return session
    
    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    async def check_permission(
        self, 
        agent_id: str, 
        user_permissions: List[str]
    ) -> bool:
        """检查权限"""
        config = self.configs.get(agent_id)
        if not config:
            return False
        
        # 检查所需权限
        required = set(config.required_permissions)
        available = set(user_permissions)
        
        return required.issubset(available)
    
    def _validate_config(self, config: AgentConfig):
        """验证配置有效性"""
        if not config.agent_id:
            raise AgentConfigError("Agent ID is required")
        if not config.name:
            raise AgentConfigError("Agent name is required")
        if config.agent_id in self.configs:
            raise AgentConfigError(f"Agent {config.agent_id} already exists")
    
    def _get_or_create_session(
        self, 
        session_id: Optional[str], 
        agent_id: str
    ) -> AgentSession:
        """获取或创建会话"""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        
        return self.create_session(agent_id)
    
    async def _check_rate_limit(self, agent_id: str) -> bool:
        """检查速率限制"""
        # TODO: 实现速率限制逻辑
        return False


class MockAgentRuntime(AgentRuntime):
    """模拟智能体运行时（用于测试）"""
    
    def __init__(self):
        super().__init__()
        self.mock_responses: Dict[str, Dict[str, Any]] = {}
        self.mock_delays: Dict[str, float] = {}
        self._setup_default_agents()
    
    def _setup_default_agents(self):
        """设置默认的模拟智能体"""
        # 意图分类器
        intent_config = AgentConfig(
            agent_id="intent-classifier",
            name="Intent Classifier",
            description="Classifies user intent",
            meta_prompt="You are an intent classifier. Analyze the user message and return the intent.",
            model="gpt-3.5-turbo",
            tags=["nlp", "classification"],
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            },
            output_schema={
                "type": "object",
                "properties": {
                    "intent": {"type": "string"},
                    "confidence": {"type": "number"}
                },
                "required": ["intent", "confidence"]
            }
        )
        
        # 投诉专员
        complaint_config = AgentConfig(
            agent_id="complaint-specialist",
            name="Complaint Specialist",
            description="Handles customer complaints",
            meta_prompt="You are a complaint specialist. Handle the customer complaint professionally.",
            model="gpt-4",
            tags=["customer-service", "complaint"],
            capabilities=["escalation", "resolution"],
            timeout_seconds=60
        )
        
        # 通用助手
        assistant_config = AgentConfig(
            agent_id="general-assistant",
            name="General Assistant",
            description="General purpose assistant",
            meta_prompt="You are a helpful assistant.",
            model="gpt-3.5-turbo",
            tags=["general"],
            rate_limit={"requests_per_minute": 60}
        )
        
        # 注册智能体
        asyncio.create_task(self.register_agent(intent_config))
        asyncio.create_task(self.register_agent(complaint_config))
        asyncio.create_task(self.register_agent(assistant_config))
        
        # 设置默认响应
        self.set_mock_response("intent-classifier", {
            "intent": "complaint",
            "confidence": 0.95
        })
        
        self.set_mock_response("complaint-specialist", {
            "response": "I understand your concern and I'm here to help.",
            "action": "escalate",
            "priority": "high"
        })
        
        self.set_mock_response("general-assistant", {
            "response": "I can help you with that.",
            "status": "completed"
        })
    
    async def create_agent(self, config: AgentConfig) -> Agent:
        """创建模拟智能体实例"""
        # 创建一个简单的模拟智能体
        class MockAgent(Agent):
            def __init__(self, config: AgentConfig, runtime: 'MockAgentRuntime'):
                super().__init__(config)
                self.runtime = runtime
            
            async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
                # 模拟延迟
                delay = self.runtime.mock_delays.get(self.config.agent_id, 0.1)
                await asyncio.sleep(delay)
                
                # 返回预设响应
                mock_response = self.runtime.mock_responses.get(self.config.agent_id)
                if mock_response:
                    return mock_response
                
                # 默认响应
                return {
                    "response": f"Mock response from {self.config.name}",
                    "input_received": input_data
                }
        
        return MockAgent(config, self)
    
    def set_mock_response(self, agent_id: str, response: Dict[str, Any]):
        """设置模拟响应"""
        self.mock_responses[agent_id] = response
    
    def set_mock_delay(self, agent_id: str, delay_seconds: float):
        """设置模拟延迟"""
        self.mock_delays[agent_id] = delay_seconds
    
    def add_mock_agent(
        self, 
        agent_id: str,
        name: str,
        response: Dict[str, Any],
        **kwargs
    ):
        """快速添加模拟智能体"""
        config = AgentConfig(
            agent_id=agent_id,
            name=name,
            description=kwargs.get("description", f"Mock agent {name}"),
            meta_prompt=kwargs.get("meta_prompt", "You are a mock agent."),
            model=kwargs.get("model", "mock-model"),
            **kwargs
        )
        
        asyncio.create_task(self.register_agent(config))
        self.set_mock_response(agent_id, response)
    
    def simulate_error(self, agent_id: str, error_message: str):
        """模拟错误响应"""
        self.mock_responses[agent_id] = {
            "__error__": error_message
        }
    
    async def create_test_scenario(self, scenario_name: str):
        """创建测试场景"""
        scenarios = {
            "customer_service": [
                ("greeting-agent", "Greeting Agent", {"greeting": "Hello! How can I help you today?"}),
                ("routing-agent", "Routing Agent", {"route": "complaint", "department": "support"}),
                ("resolution-agent", "Resolution Agent", {"solution": "Issue resolved", "ticket_id": "12345"})
            ],
            "data_processing": [
                ("validator-agent", "Data Validator", {"valid": True, "errors": []}),
                ("transformer-agent", "Data Transformer", {"transformed_data": {"processed": True}}),
                ("storage-agent", "Storage Agent", {"stored": True, "location": "database"})
            ]
        }
        
        if scenario_name in scenarios:
            for agent_id, name, response in scenarios[scenario_name]:
                self.add_mock_agent(agent_id, name, response)
            
            logger.info(f"Created test scenario: {scenario_name}")
            return True
        
        return False


class OpenAIAgentRuntime(AgentRuntime):
    """OpenAI智能体运行时实现"""
    
    def __init__(
        self, 
        api_key: str, 
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        default_model: str = "gpt-4",
        config_storage: Optional[Any] = None
    ):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.default_model = default_model
        self.config_storage = config_storage
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化OpenAI客户端"""
        try:
            # 延迟导入，避免强制依赖
            from openai import AsyncOpenAI
            
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                organization=self.organization
            )
            logger.info("OpenAI client initialized successfully")
        except ImportError:
            logger.warning("OpenAI library not installed. Install with: pip install openai")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
    
    async def create_agent(self, config: AgentConfig) -> Agent:
        """创建OpenAI智能体实例"""
        return OpenAIAgent(config, self.client)
    
    async def load_from_storage(self):
        """从存储加载智能体配置"""
        if not self.config_storage:
            return
        
        try:
            # 从存储加载配置
            configs = await self.config_storage.list_agent_configs()
            for config in configs:
                await self.register_agent(config)
            
            logger.info(f"Loaded {len(configs)} agent configurations from storage")
        except Exception as e:
            logger.error(f"Failed to load configurations: {str(e)}")
    
    async def save_to_storage(self, agent_id: str):
        """保存智能体配置到存储"""
        if not self.config_storage:
            return
        
        config = self.configs.get(agent_id)
        if config:
            try:
                await self.config_storage.save_agent_config(config)
                logger.info(f"Saved agent configuration: {agent_id}")
            except Exception as e:
                logger.error(f"Failed to save configuration: {str(e)}")


class OpenAIAgent(LLMAgent):
    """基于OpenAI的智能体实现"""
    
    def __init__(self, config: AgentConfig, client: Any):
        super().__init__(config, client)
        self.system_prompt = self._build_system_prompt()
    
    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        parts = []
        
        # 元提示词
        if self.config.meta_prompt:
            parts.append(self.config.meta_prompt)
        
        # 输出格式说明
        if self.config.output_schema:
            schema_str = json.dumps(self.config.output_schema)
            parts.append(f"\nYou must return your response in the following JSON format:\n{schema_str}")
        
        # 工具说明
        if self.config.tools:
            parts.append(f"\nAvailable tools: {', '.join(self.config.tools)}")
        
        return "\n\n".join(parts)
    
    async def _call_llm(self, prompt: str) -> str:
        """调用OpenAI API"""
        if not self.llm_client:
            raise AgentExecutionError("OpenAI client not initialized", self.config.agent_id)
        
        try:
            # 构建消息
            messages = [
                {"role": "system", "content": self.system_prompt}
            ]
            
            # 添加历史对话
            for msg in self.conversation_history[-10:]:  # 最近10条
                messages.append(msg)
            
            # 添加当前提示
            messages.append({"role": "user", "content": prompt})
            
            # 调用API
            response = await self.llm_client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"} if self.config.output_schema else None
            )
            
            # 提取响应
            content = response.choices[0].message.content
            
            # 更新token使用统计
            if hasattr(response, 'usage'):
                self.last_token_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            
            return content
            
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}", exc_info=True)
            raise AgentExecutionError(f"LLM call failed: {str(e)}", self.config.agent_id, e)
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行智能体任务"""
        # 构建提示词
        prompt = self._build_prompt(input_data)
        
        # 调用LLM
        response = await self._call_llm(prompt)
        
        # 解析响应
        output = self._parse_response(response)
        
        # 添加token使用信息
        if hasattr(self, 'last_token_usage'):
            output['_token_usage'] = self.last_token_usage
        
        return output


class ConfigStorage(ABC):
    """配置存储接口"""
    
    @abstractmethod
    async def save_agent_config(self, config: AgentConfig):
        """保存智能体配置"""
        pass
    
    @abstractmethod
    async def load_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """加载智能体配置"""
        pass
    
    @abstractmethod
    async def list_agent_configs(self) -> List[AgentConfig]:
        """列出所有配置"""
        pass
    
    @abstractmethod
    async def delete_agent_config(self, agent_id: str):
        """删除配置"""
        pass


class FileConfigStorage(ConfigStorage):
    """基于文件的配置存储"""
    
    def __init__(self, storage_path: str = "./agent_configs"):
        self.storage_path = storage_path
        self._ensure_directory()
    
    def _ensure_directory(self):
        """确保存储目录存在"""
        import os
        os.makedirs(self.storage_path, exist_ok=True)
    
    def _get_config_path(self, agent_id: str) -> str:
        """获取配置文件路径"""
        import os
        return os.path.join(self.storage_path, f"{agent_id}.json")
    
    async def save_agent_config(self, config: AgentConfig):
        """保存配置到文件"""
        import aiofiles
        
        config_path = self._get_config_path(config.agent_id)
        config_dict = config.to_dict()
        
        async with aiofiles.open(config_path, 'w') as f:
            await f.write(json.dumps(config_dict, indent=2))
    
    async def load_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """从文件加载配置"""
        import aiofiles
        import os
        
        config_path = self._get_config_path(agent_id)
        if not os.path.exists(config_path):
            return None
        
        async with aiofiles.open(config_path, 'r') as f:
            content = await f.read()
            config_dict = json.loads(content)
            return AgentConfig(**config_dict)
    
    async def list_agent_configs(self) -> List[AgentConfig]:
        """列出所有配置"""
        import os
        configs = []
        
        for filename in os.listdir(self.storage_path):
            if filename.endswith('.json'):
                agent_id = filename[:-5]  # 移除.json后缀
                config = await self.load_agent_config(agent_id)
                if config:
                    configs.append(config)
        
        return configs
    
    async def delete_agent_config(self, agent_id: str):
        """删除配置文件"""
        import os
        config_path = self._get_config_path(agent_id)
        if os.path.exists(config_path):
            os.remove(config_path)
