"""
工作流执行测试
"""
import pytest
import asyncio
from src.workflow_engine.models.execution import ExecutionStatus, NodeExecutionStatus


class TestWorkflowExecution:
    """工作流执行测试类"""
    
    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self, memory_workflow_engine, sample_dag_workflow):
        """测试执行简单工作流"""
        engine = memory_workflow_engine
        
        # 创建工作流
        workflow_id = await engine.create_workflow(sample_dag_workflow)
        
        # 执行工作流
        execution_id = await engine.execute_workflow(
            workflow_id,
            {"input": {"message": "test message"}}
        )
        
        # 等待执行完成
        await asyncio.sleep(1)
        
        # 检查执行状态
        status = await engine.get_execution_status(execution_id)
        assert status["execution_id"] == execution_id
        assert status["workflow_id"] == workflow_id
        
        # 检查节点执行
        node_executions = status["node_executions"]
        assert len(node_executions) > 0
    
    @pytest.mark.asyncio
    async def test_execute_workflow_with_dependencies(self, memory_workflow_engine):
        """测试执行带依赖的工作流"""
        workflow_def = {
            "workflow": {
                "name": "Dependency Test",
                "type": "dag",
                "nodes": [
                    {
                        "id": "node1",
                        "type": "agent",
                        "config": {"agent_id": "intent-classifier"}
                    },
                    {
                        "id": "node2",
                        "type": "agent",
                        "config": {"agent_id": "intent-classifier"},
                        "dependencies": ["node1"]
                    },
                    {
                        "id": "node3",
                        "type": "agent",
                        "config": {"agent_id": "intent-classifier"},
                        "dependencies": ["node1", "node2"]
                    }
                ]
            }
        }
        
        engine = memory_workflow_engine
        workflow_id = await engine.create_workflow(workflow_def)
        execution_id = await engine.execute_workflow(workflow_id)
        
        # 等待执行
        await asyncio.sleep(2)
        
        # 获取执行详情
        execution = await engine.execution_repository.get(execution_id)
        
        # 验证执行顺序
        node1_exec = execution.get_node_execution("node1")
        node2_exec = execution.get_node_execution("node2")
        node3_exec = execution.get_node_execution("node3")
        
        # node2 应该在 node1 之后开始
        if node1_exec.start_time and node2_exec.start_time:
            assert node2_exec.start_time >= node1_exec.start_time
        
        # node3 应该在 node1 和 node2 之后开始
        if node3_exec.start_time:
            assert node3_exec.start_time >= node1_exec.start_time
            assert node3_exec.start_time >= node2_exec.start_time
    
    @pytest.mark.asyncio
    async def test_cancel_workflow_execution(self, memory_workflow_engine, sample_dag_workflow):
        """测试取消工作流执行"""
        engine = memory_workflow_engine
        
        # 创建一个会运行较长时间的工作流
        workflow_def = {
            "workflow": {
                "name": "Long Running",
                "type": "dag",
                "nodes": [
                    {
                        "id": "slow",
                        "type": "agent",
                        "config": {"agent_id": "intent-classifier"},
                        "timeout": 10
                    }
                ]
            }
        }
        
        workflow_id = await engine.create_workflow(workflow_def)
        execution_id = await engine.execute_workflow(workflow_id)
        
        # 等待一小段时间后取消
        await asyncio.sleep(0.5)
        await engine.cancel_execution(execution_id)
        
        # 检查状态
        execution = await engine.execution_repository.get(execution_id)
        assert execution.status == ExecutionStatus.CANCELLED
    
    @pytest.mark.asyncio
    async def test_suspend_and_resume_execution(self, memory_workflow_engine):
        """测试暂停和恢复执行"""
        engine = memory_workflow_engine
        
        workflow_def = {
            "workflow": {
                "name": "Suspendable",
                "type": "dag",
                "nodes": [
                    {"id": "node1", "type": "agent", "config": {"agent_id": "intent-classifier"}},
                    {"id": "node2", "type": "agent", "config": {"agent_id": "intent-classifier"}, "dependencies": ["node1"]},
                    {"id": "node3", "type": "agent", "config": {"agent_id": "intent-classifier"}, "dependencies": ["node2"]}
                ]
            }
        }
        
        workflow_id = await engine.create_workflow(workflow_def)
        execution_id = await engine.execute_workflow(workflow_id)
        
        # 等待第一个节点完成后暂停
        await asyncio.sleep(0.5)
        await engine.suspend_execution(execution_id)
        
        # 检查状态
        execution = await engine.execution_repository.get(execution_id)
        assert execution.status == ExecutionStatus.SUSPENDED
        
        # 恢复执行
        await engine.resume_execution(execution_id)
        
        # 等待完成
        await asyncio.sleep(2)
        
        # 检查最终状态
        execution = await engine.execution_repository.get(execution_id)
        assert execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.RUNNING]
    
    @pytest.mark.asyncio
    async def test_parallel_node_execution(self, memory_workflow_engine):
        """测试并行节点执行"""
        workflow_def = {
            "workflow": {
                "name": "Parallel Execution",
                "type": "dag",
                "nodes": [
                    {"id": "start", "type": "agent", "config": {"agent_id": "intent-classifier"}},
                    {"id": "parallel1", "type": "agent", "config": {"agent_id": "intent-classifier"}, "dependencies": ["start"]},
                    {"id": "parallel2", "type": "agent", "config": {"agent_id": "intent-classifier"}, "dependencies": ["start"]},
                    {"id": "parallel3", "type": "agent", "config": {"agent_id": "intent-classifier"}, "dependencies": ["start"]},
                    {"id": "end", "type": "agent", "config": {"agent_id": "intent-classifier"}, 
                     "dependencies": ["parallel1", "parallel2", "parallel3"]}
                ]
            }
        }
        
        engine = memory_workflow_engine
        workflow_id = await engine.create_workflow(workflow_def)
        execution_id = await engine.execute_workflow(workflow_id)
        
        # 等待执行
        await asyncio.sleep(3)
        
        # 获取执行详情
        execution = await engine.execution_repository.get(execution_id)
        
        # 检查并行节点是否同时运行
        parallel_nodes = ["parallel1", "parallel2", "parallel3"]
        start_times = []
        
        for node_id in parallel_nodes:
            node_exec = execution.get_node_execution(node_id)
            if node_exec and node_exec.start_time:
                start_times.append(node_exec.start_time)
        
        # 并行节点的开始时间应该很接近
        if len(start_times) >= 2:
            time_diffs = [abs((start_times[i] - start_times[i+1]).total_seconds()) 
                         for i in range(len(start_times)-1)]
            # 时间差应该小于1秒
            assert all(diff < 1.0 for diff in time_diffs)
    
    @pytest.mark.asyncio
    async def test_workflow_with_context_passing(self, memory_workflow_engine):
        """测试上下文传递"""
        workflow_def = {
            "workflow": {
                "name": "Context Passing",
                "type": "dag",
                "nodes": [
                    {
                        "id": "producer",
                        "type": "agent",
                        "config": {"agent_id": "intent-classifier"},
                        "inputs": {"data": "${input.data}"},
                        "outputs": ["result"]
                    },
                    {
                        "id": "consumer",
                        "type": "agent",
                        "config": {"agent_id": "complaint-specialist"},
                        "dependencies": ["producer"],
                        "inputs": {"previous_result": "${producer.result}"}
                    }
                ]
            }
        }
        
        engine = memory_workflow_engine
        workflow_id = await engine.create_workflow(workflow_def)
        
        # 执行工作流并传递输入
        execution_id = await engine.execute_workflow(
            workflow_id,
            {"input": {"data": "test input"}}
        )
        
        # 等待执行
        await asyncio.sleep(2)
        
        # 获取执行详情
        execution = await engine.execution_repository.get(execution_id)
        
        # 检查上下文是否正确传递
        assert execution.context.inputs.get("input", {}).get("data") == "test input"
        
        # 检查节点间数据传递
        producer_exec = execution.get_node_execution("producer")
        assert producer_exec is not None
        
        # Mock 智能体应该返回了结果
        if producer_exec.output_data:
            assert "intent" in producer_exec.output_data
