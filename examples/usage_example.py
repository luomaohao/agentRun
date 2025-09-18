"""
工作流引擎使用示例
"""
import asyncio
from pathlib import Path
import logging

from src.workflow_engine import WorkflowEngine, TaskScheduler
from src.workflow_engine.storage.repository import InMemoryWorkflowRepository, InMemoryExecutionRepository
from src.workflow_engine.integrations.event_bus import EventBus
from src.workflow_engine.integrations.agent_runtime import MockAgentRuntime
from src.workflow_engine.integrations.tool_registry import LocalToolRegistry, BuiltinTools
from src.workflow_engine.core.state_machine import StateMachineEngine


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def setup_workflow_engine():
    """设置工作流引擎"""
    # 创建组件
    workflow_repo = InMemoryWorkflowRepository()
    execution_repo = InMemoryExecutionRepository()
    scheduler = TaskScheduler()
    event_bus = EventBus()
    agent_runtime = MockAgentRuntime()
    tool_registry = LocalToolRegistry()
    
    # 注册内置工具
    await BuiltinTools.register_all(tool_registry)
    
    # 创建工作流引擎
    engine = WorkflowEngine(
        workflow_repository=workflow_repo,
        execution_repository=execution_repo,
        scheduler=scheduler,
        event_bus=event_bus,
        agent_runtime=agent_runtime,
        tool_registry=tool_registry
    )
    
    # 启动调度器
    await scheduler.start()
    
    return engine


async def example_dag_workflow(engine: WorkflowEngine):
    """DAG工作流示例"""
    print("\n=== DAG 工作流示例 ===")
    
    # 加载工作流定义
    workflow_file = Path("examples/customer_support_workflow.yaml")
    workflow_id = await engine.create_workflow(workflow_file)
    print(f"创建工作流: {workflow_id}")
    
    # 执行工作流
    context = {
        "trigger": {
            "message": "我的订单出现了问题，已经等了3天还没收到",
            "user_id": "user123",
            "channel": "web",
            "context": {
                "order_id": "ORDER-2024-001",
                "user_tier": "vip"
            }
        },
        "session": {
            "history": []
        },
        "config": {
            "compliance_rules": ["no_personal_info", "professional_tone"]
        }
    }
    
    execution_id = await engine.execute_workflow(workflow_id, context)
    print(f"启动工作流执行: {execution_id}")
    
    # 等待一段时间让工作流执行
    await asyncio.sleep(5)
    
    # 获取执行状态
    status = await engine.get_execution_status(execution_id)
    print(f"执行状态: {status}")


async def example_state_machine_workflow(engine: WorkflowEngine):
    """状态机工作流示例"""
    print("\n=== 状态机工作流示例 ===")
    
    # 创建状态机引擎
    state_machine_engine = StateMachineEngine(engine.event_bus)
    
    # 加载状态机工作流
    workflow_file = Path("examples/order_state_machine.yaml")
    workflow = engine.parser.parse(workflow_file)
    await state_machine_engine.register_workflow(workflow)
    print(f"注册状态机工作流: {workflow.id}")
    
    # 创建状态机实例
    instance = await state_machine_engine.create_instance(
        workflow_id=workflow.id,
        initial_context={
            "order_id": "ORDER-2024-002",
            "amount": 299.99,
            "payment_method": "credit_card",
            "inventory_available": True,
            "cancellation_allowed": True
        }
    )
    print(f"创建状态机实例: {instance.instance_id}")
    
    # 处理事件序列
    events = [
        ("pay", {"payment_method": "credit_card"}),
        ("confirm", {"estimated_delivery": "2024-01-20"}),
        ("ship", {"tracking_number": "TRACK123", "carrier": "FedEx"}),
        ("deliver", {"delivery_confirmation": "SIGN123"}),
        ("complete", {"customer_confirmed": True})
    ]
    
    for event, data in events:
        print(f"\n处理事件: {event}")
        success = await state_machine_engine.process_event(
            instance.instance_id,
            event,
            data
        )
        
        if success:
            status = await state_machine_engine.get_instance_status(instance.instance_id)
            print(f"当前状态: {status['current_state']}")
        else:
            print(f"事件 {event} 处理失败")
    
    # 获取最终状态
    final_status = await state_machine_engine.get_instance_status(instance.instance_id)
    print(f"\n最终状态: {final_status}")


async def example_parallel_execution(engine: WorkflowEngine):
    """并行执行示例"""
    print("\n=== 并行执行示例 ===")
    
    # 创建一个包含并行节点的工作流
    parallel_workflow = {
        "workflow": {
            "id": "parallel-example",
            "name": "并行执行示例",
            "type": "dag",
            "nodes": [
                {
                    "id": "start",
                    "type": "agent",
                    "agent": "intent-classifier",
                    "inputs": {"message": "${input.message}"}
                },
                {
                    "id": "parallel-tasks",
                    "type": "control",
                    "subtype": "parallel",
                    "dependencies": ["start"],
                    "branches": ["task1", "task2", "task3"],
                    "wait_all": True
                },
                {
                    "id": "task1",
                    "type": "tool",
                    "tool": "http_request",
                    "dependencies": ["parallel-tasks"],
                    "inputs": {
                        "url": "https://api.example.com/service1",
                        "method": "GET"
                    }
                },
                {
                    "id": "task2",
                    "type": "tool",
                    "tool": "database_query",
                    "dependencies": ["parallel-tasks"],
                    "inputs": {
                        "query": "SELECT * FROM users WHERE id = ?"
                    }
                },
                {
                    "id": "task3",
                    "type": "agent",
                    "agent": "complaint-specialist",
                    "dependencies": ["parallel-tasks"],
                    "inputs": {"context": "${start.output}"}
                },
                {
                    "id": "aggregate",
                    "type": "aggregation",
                    "dependencies": ["task1", "task2", "task3"],
                    "config": {"strategy": "merge"}
                }
            ]
        }
    }
    
    # 创建并执行工作流
    workflow_id = await engine.create_workflow(parallel_workflow)
    execution_id = await engine.execute_workflow(
        workflow_id,
        {"input": {"message": "测试并行执行"}}
    )
    
    print(f"并行工作流执行: {execution_id}")
    
    # 监控执行进度
    for i in range(10):
        await asyncio.sleep(1)
        status = await engine.get_execution_status(execution_id)
        running_nodes = [
            node_id for node_id, node_status in status["node_executions"].items()
            if node_status["status"] == "running"
        ]
        print(f"运行中的节点: {running_nodes}")
        
        if status["status"] in ["completed", "failed"]:
            break


async def example_error_handling(engine: WorkflowEngine):
    """错误处理示例"""
    print("\n=== 错误处理示例 ===")
    
    # 创建一个会出错的工作流
    error_workflow = {
        "workflow": {
            "id": "error-handling-example",
            "name": "错误处理示例",
            "type": "dag",
            "nodes": [
                {
                    "id": "will-fail",
                    "type": "tool",
                    "tool": "non-existent-tool",  # 不存在的工具
                    "retry_policy": {
                        "max_retries": 3,
                        "retry_delay": 1,
                        "backoff_factor": 2
                    }
                }
            ],
            "error_handlers": [
                {
                    "node_pattern": "will-fail",
                    "error_type": "execution_error",
                    "action": {
                        "type": "fallback",
                        "target": "error-recovery"
                    }
                }
            ]
        }
    }
    
    # 订阅错误事件
    error_events = []
    
    async def error_handler(event):
        error_events.append(event)
        print(f"错误事件: {event.payload}")
    
    await engine.event_bus.subscribe("workflow.node.events", error_handler)
    
    # 执行工作流
    workflow_id = await engine.create_workflow(error_workflow)
    execution_id = await engine.execute_workflow(workflow_id)
    
    # 等待执行
    await asyncio.sleep(5)
    
    # 查看错误事件
    print(f"捕获的错误事件数: {len(error_events)}")


async def main():
    """主函数"""
    # 设置工作流引擎
    engine = await setup_workflow_engine()
    
    try:
        # 运行示例
        await example_dag_workflow(engine)
        await example_state_machine_workflow(engine)
        await example_parallel_execution(engine)
        await example_error_handling(engine)
        
    finally:
        # 停止调度器
        await engine.scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
