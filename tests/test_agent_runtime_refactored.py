"""
智能体运行时重构后的测试
"""
import pytest
import asyncio
from typing import Dict, Any

from src.workflow_engine.integrations import (
    MockAgentRuntime,
    AgentConfig,
    AgentResponse,
    BatchRequest,
    AgentNotFoundError,
    AgentValidationError,
    Agent,
    RuleBasedAgent
)


@pytest.mark.asyncio
async def test_agent_registration():
    """测试智能体注册"""
    runtime = MockAgentRuntime()
    
    # 创建配置
    config = AgentConfig(
        agent_id="test-agent",
        name="Test Agent",
        description="Test agent for unit testing",
        meta_prompt="You are a test agent",
        tags=["test", "unit-test"]
    )
    
    # 注册智能体
    agent_id = await runtime.register_agent(config)
    assert agent_id == "test-agent"
    
    # 验证智能体已注册
    agent_config = await runtime.get_agent_config(agent_id)
    assert agent_config is not None
    assert agent_config.name == "Test Agent"
    
    # 测试重复注册
    with pytest.raises(Exception):
        await runtime.register_agent(config)


@pytest.mark.asyncio
async def test_agent_invocation():
    """测试智能体调用"""
    runtime = MockAgentRuntime()
    await asyncio.sleep(0.1)  # 等待默认智能体注册
    
    # 调用意图分类器
    response = await runtime.invoke_agent(
        agent_id="intent-classifier",
        input_data={"message": "I have a complaint"}
    )
    
    assert isinstance(response, AgentResponse)
    assert response.status == "success"
    assert "intent" in response.output
    assert response.output["intent"] == "complaint"


@pytest.mark.asyncio
async def test_batch_processing():
    """测试批量处理"""
    runtime = MockAgentRuntime()
    await asyncio.sleep(0.1)
    
    # 创建批量请求
    batch_request = BatchRequest(
        agent_id="general-assistant",
        requests=[
            {"question": "Question 1"},
            {"question": "Question 2"},
            {"question": "Question 3"}
        ],
        parallel=True
    )
    
    # 执行批量处理
    batch_response = await runtime.invoke_batch(batch_request)
    
    assert len(batch_response.responses) == 3
    assert batch_response.success_count == 3
    assert batch_response.error_count == 0
    assert batch_response.success_rate == 1.0


@pytest.mark.asyncio
async def test_agent_not_found():
    """测试智能体未找到异常"""
    runtime = MockAgentRuntime()
    
    with pytest.raises(AgentNotFoundError):
        await runtime.invoke_agent(
            agent_id="non-existent-agent",
            input_data={"test": "data"}
        )


@pytest.mark.asyncio
async def test_agent_update():
    """测试智能体配置更新"""
    runtime = MockAgentRuntime()
    
    # 创建并注册智能体
    config = AgentConfig(
        agent_id="update-test",
        name="Update Test Agent",
        description="Test agent for update",
        meta_prompt="Test prompt",
        temperature=0.7
    )
    
    await runtime.register_agent(config)
    
    # 更新配置
    updated_config = await runtime.update_agent_config(
        "update-test",
        {
            "temperature": 0.5,
            "tags": ["updated", "test"],
            "enabled": False
        }
    )
    
    assert updated_config.temperature == 0.5
    assert "updated" in updated_config.tags
    assert updated_config.enabled is False


@pytest.mark.asyncio
async def test_agent_deletion():
    """测试智能体删除"""
    runtime = MockAgentRuntime()
    
    # 创建并注册智能体
    config = AgentConfig(
        agent_id="delete-test",
        name="Delete Test Agent",
        description="Test agent for deletion",
        meta_prompt="Test prompt"
    )
    
    await runtime.register_agent(config)
    
    # 验证智能体存在
    assert await runtime.get_agent_config("delete-test") is not None
    
    # 删除智能体
    await runtime.delete_agent("delete-test")
    
    # 验证智能体已删除
    assert await runtime.get_agent_config("delete-test") is None
    
    # 尝试调用已删除的智能体
    with pytest.raises(AgentNotFoundError):
        await runtime.invoke_agent("delete-test", {"test": "data"})


@pytest.mark.asyncio
async def test_session_management():
    """测试会话管理"""
    runtime = MockAgentRuntime()
    await asyncio.sleep(0.1)
    
    # 创建会话
    session = runtime.create_session("general-assistant", user_id="test-user")
    assert session.agent_id == "general-assistant"
    assert session.user_id == "test-user"
    
    # 使用会话调用智能体
    response = await runtime.invoke_agent(
        agent_id="general-assistant",
        input_data={"message": "Hello"},
        session_id=session.session_id
    )
    
    # 验证会话历史
    assert len(session.history) == 1
    assert session.history[0]["input"]["message"] == "Hello"


@pytest.mark.asyncio
async def test_custom_agent():
    """测试自定义智能体"""
    runtime = MockAgentRuntime()
    
    # 创建自定义智能体类
    class CustomAgent(Agent):
        async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "processed": True,
                "input_length": len(str(input_data)),
                "custom_response": "This is a custom agent"
            }
    
    # 注册自定义智能体
    config = AgentConfig(
        agent_id="custom-agent",
        name="Custom Agent",
        description="Custom agent implementation",
        meta_prompt="Custom prompt"
    )
    
    runtime.agents[config.agent_id] = CustomAgent(config)
    runtime.configs[config.agent_id] = config
    
    # 调用自定义智能体
    response = await runtime.invoke_agent(
        agent_id="custom-agent",
        input_data={"test": "data"}
    )
    
    assert response.output["processed"] is True
    assert response.output["custom_response"] == "This is a custom agent"


@pytest.mark.asyncio
async def test_input_validation():
    """测试输入验证"""
    runtime = MockAgentRuntime()
    
    # 创建带有输入schema的智能体
    config = AgentConfig(
        agent_id="validated-agent",
        name="Validated Agent",
        description="Agent with input validation",
        meta_prompt="Test prompt",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0}
            },
            "required": ["name", "age"]
        }
    )
    
    await runtime.register_agent(config)
    
    # 测试有效输入
    response = await runtime.invoke_agent(
        agent_id="validated-agent",
        input_data={"name": "John", "age": 25}
    )
    assert response.status == "success"
    
    # 测试无效输入 - 缺少必需字段
    with pytest.raises(AgentValidationError):
        await runtime.invoke_agent(
            agent_id="validated-agent",
            input_data={"name": "John"}  # 缺少age字段
        )


@pytest.mark.asyncio
async def test_mock_scenarios():
    """测试模拟场景"""
    runtime = MockAgentRuntime()
    
    # 创建客服场景
    success = await runtime.create_test_scenario("customer_service")
    assert success is True
    
    # 验证场景中的智能体已创建
    await asyncio.sleep(0.1)  # 等待异步注册
    
    greeting_response = await runtime.invoke_agent(
        agent_id="greeting-agent",
        input_data={"message": "Hello"}
    )
    assert "greeting" in greeting_response.output


if __name__ == "__main__":
    asyncio.run(test_agent_registration())
    asyncio.run(test_agent_invocation())
    asyncio.run(test_batch_processing())
