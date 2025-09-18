"""
智能体运行时使用示例
"""
import asyncio
from typing import Dict, Any

from .agent_runtime import MockAgentRuntime, OpenAIAgentRuntime, FileConfigStorage
from .models import AgentConfig, BatchRequest
from .agent import LLMAgent, RuleBasedAgent


async def example_mock_runtime():
    """使用模拟运行时的示例"""
    print("=== Mock Agent Runtime Example ===")
    
    # 创建模拟运行时
    runtime = MockAgentRuntime()
    
    # 等待默认智能体注册完成
    await asyncio.sleep(0.1)
    
    # 1. 调用意图分类器
    response = await runtime.invoke_agent(
        agent_id="intent-classifier",
        input_data={"message": "I'm very unhappy with your service!"}
    )
    print(f"Intent classification result: {response.output}")
    
    # 2. 创建测试场景
    await runtime.create_test_scenario("customer_service")
    
    # 3. 批量调用示例
    batch_request = BatchRequest(
        agent_id="general-assistant",
        requests=[
            {"question": "What is the weather today?"},
            {"question": "How do I reset my password?"},
            {"question": "What are your business hours?"}
        ],
        parallel=True
    )
    
    batch_response = await runtime.invoke_batch(batch_request)
    print(f"Batch processing completed: {batch_response.success_count}/{len(batch_response.responses)} successful")
    
    # 4. 会话管理示例
    session = runtime.create_session("general-assistant", user_id="user123")
    session_response = await runtime.invoke_agent(
        agent_id="general-assistant",
        input_data={"message": "Hello"},
        session_id=session.session_id
    )
    print(f"Session {session.session_id} created")


async def example_openai_runtime():
    """使用OpenAI运行时的示例"""
    print("\n=== OpenAI Agent Runtime Example ===")
    
    # 创建配置存储
    storage = FileConfigStorage("./agent_configs")
    
    # 创建OpenAI运行时
    runtime = OpenAIAgentRuntime(
        api_key="your-api-key-here",
        config_storage=storage
    )
    
    # 1. 注册新的智能体
    summarizer_config = AgentConfig(
        agent_id="text-summarizer",
        name="Text Summarizer",
        description="Summarizes long texts into concise summaries",
        meta_prompt="""You are a professional text summarizer. 
        Create clear, concise summaries that capture the main points.""",
        model="gpt-3.5-turbo",
        temperature=0.3,
        tags=["nlp", "summarization"],
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to summarize"},
                "max_length": {"type": "integer", "description": "Maximum summary length", "default": 100}
            },
            "required": ["text"]
        },
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "key_points": {"type": "array", "items": {"type": "string"}},
                "word_count": {"type": "integer"}
            },
            "required": ["summary", "key_points"]
        }
    )
    
    await runtime.register_agent(summarizer_config)
    
    # 2. 保存配置到存储
    await runtime.save_to_storage("text-summarizer")
    
    # 3. 调用智能体
    try:
        response = await runtime.invoke_agent(
            agent_id="text-summarizer",
            input_data={
                "text": "Your long text here...",
                "max_length": 50
            }
        )
        print(f"Summary: {response.output.get('summary')}")
        print(f"Token usage: {response.metadata.get('token_usage', {})}")
    except Exception as e:
        print(f"Error: {e}")


async def example_custom_agent():
    """创建自定义智能体的示例"""
    print("\n=== Custom Agent Example ===")
    
    # 创建基于规则的智能体配置
    rule_config = AgentConfig(
        agent_id="order-processor",
        name="Order Processor",
        description="Processes orders based on business rules",
        meta_prompt="Process orders according to rules",
        tags=["business", "orders"],
        capabilities=["validation", "routing", "pricing"]
    )
    
    # 创建运行时
    runtime = MockAgentRuntime()
    
    # 定义规则
    rules = {
        "high_value_order": {
            "condition": {"order_value_exceeds": 1000},
            "action": {
                "status": "requires_approval",
                "route_to": "manager",
                "priority": "high"
            }
        },
        "rush_order": {
            "condition": {"is_rush": True},
            "action": {
                "status": "expedited",
                "shipping": "express",
                "priority": "urgent"
            }
        }
    }
    
    # 创建基于规则的智能体
    class OrderProcessorAgent(RuleBasedAgent):
        def _match_rule(self, input_data: Dict[str, Any], condition: Dict[str, Any]) -> bool:
            """自定义规则匹配逻辑"""
            if "order_value_exceeds" in condition:
                return input_data.get("order_value", 0) > condition["order_value_exceeds"]
            if "is_rush" in condition:
                return input_data.get("rush_delivery", False) == condition["is_rush"]
            return super()._match_rule(input_data, condition)
    
    # 注册自定义智能体
    runtime.agents[rule_config.agent_id] = OrderProcessorAgent(rule_config, rules)
    runtime.configs[rule_config.agent_id] = rule_config
    
    # 测试订单处理
    test_orders = [
        {"order_id": "001", "order_value": 1500, "rush_delivery": False},
        {"order_id": "002", "order_value": 200, "rush_delivery": True},
        {"order_id": "003", "order_value": 800, "rush_delivery": False}
    ]
    
    for order in test_orders:
        response = await runtime.invoke_agent("order-processor", order)
        print(f"Order {order['order_id']}: {response.output}")


async def example_agent_lifecycle():
    """智能体生命周期管理示例"""
    print("\n=== Agent Lifecycle Management Example ===")
    
    runtime = MockAgentRuntime()
    
    # 1. 创建并注册智能体
    config = AgentConfig(
        agent_id="lifecycle-demo",
        name="Lifecycle Demo Agent",
        description="Demonstrates agent lifecycle",
        meta_prompt="Demo agent",
        enabled=True
    )
    
    agent_id = await runtime.register_agent(config)
    print(f"Registered agent: {agent_id}")
    
    # 2. 列出所有智能体
    all_agents = await runtime.list_agents()
    print(f"Total agents: {len(all_agents)}")
    
    # 3. 更新智能体配置
    updated_config = await runtime.update_agent_config(
        agent_id,
        {
            "temperature": 0.5,
            "tags": ["demo", "lifecycle"],
            "enabled": False
        }
    )
    print(f"Updated agent config: temperature={updated_config.temperature}, enabled={updated_config.enabled}")
    
    # 4. 列出仅启用的智能体
    enabled_agents = await runtime.list_agents(enabled_only=True)
    print(f"Enabled agents: {len(enabled_agents)}")
    
    # 5. 获取智能体状态
    agent = await runtime.get_agent(agent_id)
    if agent:
        status = agent.get_status()
        print(f"Agent status: {status}")
    
    # 6. 删除智能体
    await runtime.delete_agent(agent_id)
    print(f"Deleted agent: {agent_id}")


async def main():
    """运行所有示例"""
    await example_mock_runtime()
    # await example_openai_runtime()  # 需要有效的API密钥
    await example_custom_agent()
    await example_agent_lifecycle()


if __name__ == "__main__":
    asyncio.run(main())
