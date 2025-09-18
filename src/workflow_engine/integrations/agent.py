"""
智能体核心类，负责智能体的业务逻辑和行为
"""
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import json
from abc import ABC, abstractmethod

from .models import AgentConfig, AgentResponse, AgentStatus
from .exceptions import AgentValidationError, AgentExecutionError
from .validators import SchemaValidator


logger = logging.getLogger(__name__)


class Agent(ABC):
    """智能体基类，定义智能体的核心行为"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.id = config.agent_id
        self.status = AgentStatus.IDLE
        self.memory: Dict[str, Any] = {}
        self.context: Dict[str, Any] = {}
        self.validator = SchemaValidator()
        self._initialize()
    
    def _initialize(self):
        """初始化智能体"""
        logger.info(f"Initializing agent: {self.id}")
        self.validate_config()
    
    def validate_config(self):
        """验证智能体配置"""
        if not self.config.agent_id:
            raise AgentValidationError("Agent ID is required")
        if not self.config.name:
            raise AgentValidationError("Agent name is required")
    
    async def handle(
        self, 
        input_data: Dict[str, Any], 
        context: Optional[Dict[str, Any]] = None
    ) -> AgentResponse:
        """处理输入并返回响应"""
        start_time = datetime.now()
        self.status = AgentStatus.PROCESSING
        
        try:
            # 合并上下文
            self.context.update(context or {})
            
            # 验证输入
            validation_errors = await self.validate_input(input_data)
            if validation_errors:
                raise AgentValidationError(f"Input validation failed: {validation_errors}")
            
            # 预处理
            processed_input = await self.preprocess(input_data)
            
            # 执行核心逻辑
            output = await self.execute(processed_input)
            
            # 验证输出
            output_errors = await self.validate_output(output)
            if output_errors:
                raise AgentValidationError(f"Output validation failed: {output_errors}")
            
            # 后处理
            final_output = await self.postprocess(output)
            
            # 更新记忆
            await self.update_memory(input_data, final_output)
            
            # 计算执行时间
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            self.status = AgentStatus.IDLE
            
            return AgentResponse(
                agent_id=self.id,
                output=final_output,
                status="success",
                duration_ms=duration_ms,
                metadata={
                    "agent_name": self.config.name,
                    "model": self.config.model,
                    "context_keys": list(self.context.keys())
                }
            )
            
        except Exception as e:
            self.status = AgentStatus.ERROR
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            logger.error(f"Agent {self.id} execution failed: {str(e)}", exc_info=True)
            
            return AgentResponse(
                agent_id=self.id,
                output={},
                status="error",
                error=str(e),
                duration_ms=duration_ms,
                metadata={"error_type": type(e).__name__}
            )
    
    async def validate_input(self, input_data: Dict[str, Any]) -> List[str]:
        """验证输入数据"""
        if not self.config.input_schema:
            return []
        
        return self.validator.validate(input_data, self.config.input_schema)
    
    async def validate_output(self, output_data: Dict[str, Any]) -> List[str]:
        """验证输出数据"""
        if not self.config.output_schema:
            return []
        
        return self.validator.validate(output_data, self.config.output_schema)
    
    async def preprocess(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """预处理输入数据"""
        return input_data
    
    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行核心业务逻辑 - 子类必须实现"""
        pass
    
    async def postprocess(self, output_data: Dict[str, Any]) -> Dict[str, Any]:
        """后处理输出数据"""
        return output_data
    
    async def update_memory(self, input_data: Dict[str, Any], output_data: Dict[str, Any]):
        """更新智能体记忆"""
        self.memory["last_input"] = input_data
        self.memory["last_output"] = output_data
        self.memory["last_execution"] = datetime.now().isoformat()
    
    def get_capabilities(self) -> List[str]:
        """获取智能体能力列表"""
        capabilities = []
        if self.config.tools:
            capabilities.extend(self.config.tools)
        if self.config.metadata and "capabilities" in self.config.metadata:
            capabilities.extend(self.config.metadata["capabilities"])
        return list(set(capabilities))
    
    def reset_memory(self):
        """重置记忆"""
        self.memory.clear()
    
    def get_status(self) -> Dict[str, Any]:
        """获取智能体状态"""
        return {
            "agent_id": self.id,
            "name": self.config.name,
            "status": self.status.value,
            "model": self.config.model,
            "capabilities": self.get_capabilities(),
            "memory_size": len(self.memory),
            "context_keys": list(self.context.keys())
        }


class LLMAgent(Agent):
    """基于大语言模型的智能体实现"""
    
    def __init__(self, config: AgentConfig, llm_client: Any = None):
        super().__init__(config)
        self.llm_client = llm_client
        self.conversation_history: List[Dict[str, str]] = []
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用LLM执行任务"""
        # 构建提示词
        prompt = self._build_prompt(input_data)
        
        # 添加到对话历史
        self.conversation_history.append({"role": "user", "content": json.dumps(input_data)})
        
        # 调用LLM
        response = await self._call_llm(prompt)
        
        # 添加响应到历史
        self.conversation_history.append({"role": "assistant", "content": response})
        
        # 解析响应
        return self._parse_response(response)
    
    def _build_prompt(self, input_data: Dict[str, Any]) -> str:
        """构建LLM提示词"""
        prompt_parts = []
        
        # 元提示词
        if self.config.meta_prompt:
            prompt_parts.append(self.config.meta_prompt)
        
        # 上下文信息
        if self.context:
            prompt_parts.append(f"Context: {json.dumps(self.context)}")
        
        # 输入数据
        prompt_parts.append(f"Input: {json.dumps(input_data)}")
        
        # 输出格式要求
        if self.config.output_schema:
            prompt_parts.append(f"Expected output format: {json.dumps(self.config.output_schema)}")
        
        return "\n\n".join(prompt_parts)
    
    async def _call_llm(self, prompt: str) -> str:
        """调用LLM API"""
        if not self.llm_client:
            # 模拟响应
            return json.dumps({"response": "This is a mock response", "status": "completed"})
        
        # TODO: 实际LLM调用逻辑
        raise NotImplementedError("LLM client integration not implemented")
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        try:
            # 尝试解析JSON
            return json.loads(response)
        except json.JSONDecodeError:
            # 如果不是JSON，包装成字典返回
            return {"response": response}
    
    def clear_history(self):
        """清除对话历史"""
        self.conversation_history.clear()


class RuleBasedAgent(Agent):
    """基于规则的智能体实现"""
    
    def __init__(self, config: AgentConfig, rules: Dict[str, Any] = None):
        super().__init__(config)
        self.rules = rules or {}
    
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """基于规则执行任务"""
        # 简单的规则匹配示例
        for rule_name, rule_config in self.rules.items():
            if self._match_rule(input_data, rule_config.get("condition", {})):
                return rule_config.get("action", {})
        
        # 默认响应
        return {"status": "no_matching_rule", "input": input_data}
    
    def _match_rule(self, input_data: Dict[str, Any], condition: Dict[str, Any]) -> bool:
        """匹配规则条件"""
        for key, expected_value in condition.items():
            if input_data.get(key) != expected_value:
                return False
        return True
    
    def add_rule(self, rule_name: str, condition: Dict[str, Any], action: Dict[str, Any]):
        """添加规则"""
        self.rules[rule_name] = {
            "condition": condition,
            "action": action
        }
    
    def remove_rule(self, rule_name: str):
        """删除规则"""
        self.rules.pop(rule_name, None)
