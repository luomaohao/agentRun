"""
工作流解析器测试
"""
import pytest
from src.workflow_engine.core.parser import WorkflowParser
from src.workflow_engine.models.workflow import WorkflowType, NodeType
from src.workflow_engine.exceptions import WorkflowParseError, WorkflowValidationError


class TestWorkflowParser:
    """工作流解析器测试类"""
    
    @pytest.fixture
    def parser(self):
        """创建解析器实例"""
        return WorkflowParser()
    
    def test_parse_dag_workflow(self, parser, sample_dag_workflow):
        """测试解析 DAG 工作流"""
        workflow = parser.parse(sample_dag_workflow)
        
        assert workflow.name == "Test DAG Workflow"
        assert workflow.version == "1.0.0"
        assert workflow.type == WorkflowType.DAG
        assert len(workflow.nodes) == 2
        assert len(workflow.edges) == 1
    
    def test_parse_state_machine_workflow(self, parser, sample_state_machine_workflow):
        """测试解析状态机工作流"""
        workflow = parser.parse(sample_state_machine_workflow)
        
        assert workflow.name == "Test State Machine"
        assert workflow.type == WorkflowType.STATE_MACHINE
        assert hasattr(workflow, 'initial_state')
        assert hasattr(workflow, 'states')
        assert len(workflow.states) == 4
    
    def test_parse_yaml_string(self, parser):
        """测试解析 YAML 字符串"""
        yaml_content = """
workflow:
  name: Simple Workflow
  type: dag
  nodes:
    - id: node1
      type: agent
      config:
        agent_id: test-agent
        """
        
        workflow = parser.parse_string(yaml_content)
        assert workflow.name == "Simple Workflow"
        assert len(workflow.nodes) == 1
    
    def test_parse_json_string(self, parser):
        """测试解析 JSON 字符串"""
        json_content = """
{
  "workflow": {
    "name": "JSON Workflow",
    "type": "dag",
    "nodes": [
      {
        "id": "node1",
        "type": "tool",
        "config": {
          "tool_id": "test-tool"
        }
      }
    ]
  }
}
        """
        
        workflow = parser.parse_string(json_content)
        assert workflow.name == "JSON Workflow"
        assert workflow.nodes[0].type == NodeType.TOOL
    
    def test_validate_workflow_with_cycle(self, parser):
        """测试验证包含循环的工作流"""
        workflow_def = {
            "workflow": {
                "name": "Cyclic Workflow",
                "type": "dag",
                "nodes": [
                    {"id": "a", "type": "agent", "config": {"agent_id": "test"}},
                    {"id": "b", "type": "agent", "config": {"agent_id": "test"}},
                    {"id": "c", "type": "agent", "config": {"agent_id": "test"}}
                ],
                "edges": [
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "c"},
                    {"source": "c", "target": "a"}  # 创建循环
                ]
            }
        }
        
        with pytest.raises(WorkflowValidationError) as exc_info:
            parser.parse(workflow_def)
        
        assert "cycle" in str(exc_info.value).lower()
    
    def test_optimize_workflow(self, parser):
        """测试工作流优化"""
        workflow_def = {
            "workflow": {
                "name": "Parallel Workflow",
                "type": "dag",
                "nodes": [
                    {"id": "start", "type": "agent", "config": {"agent_id": "test"}},
                    {"id": "parallel1", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["start"]},
                    {"id": "parallel2", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["start"]},
                    {"id": "parallel3", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["start"]},
                    {"id": "end", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["parallel1", "parallel2", "parallel3"]}
                ]
            }
        }
        
        workflow = parser.parse(workflow_def)
        optimized = parser.optimize_workflow(workflow)
        
        # 检查并行组标记
        parallel_nodes = ["parallel1", "parallel2", "parallel3"]
        for node_id in parallel_nodes:
            node = optimized.get_node(node_id)
            assert "parallel_group" in node.metadata
            # 所有并行节点应该在同一组
            assert node.metadata["parallel_group"] == optimized.get_node(parallel_nodes[0]).metadata["parallel_group"]
    
    def test_parse_invalid_node_type(self, parser):
        """测试解析无效节点类型"""
        workflow_def = {
            "workflow": {
                "name": "Invalid Node Type",
                "type": "dag",
                "nodes": [
                    {"id": "bad", "type": "invalid_type", "config": {}}
                ]
            }
        }
        
        with pytest.raises(ValueError):
            parser.parse(workflow_def)
    
    def test_parse_missing_required_fields(self, parser):
        """测试解析缺少必需字段的工作流"""
        # 缺少节点ID
        workflow_def = {
            "workflow": {
                "name": "Missing ID",
                "type": "dag",
                "nodes": [
                    {"type": "agent", "config": {"agent_id": "test"}}
                ]
            }
        }
        
        with pytest.raises(Exception):  # 具体异常类型取决于实现
            parser.parse(workflow_def)
    
    def test_infer_edges_from_dependencies(self, parser):
        """测试从依赖关系推断边"""
        workflow_def = {
            "workflow": {
                "name": "Dependencies Only",
                "type": "dag",
                "nodes": [
                    {"id": "a", "type": "agent", "config": {"agent_id": "test"}},
                    {"id": "b", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["a"]},
                    {"id": "c", "type": "agent", "config": {"agent_id": "test"}, "dependencies": ["b"]}
                ]
                # 没有显式定义边
            }
        }
        
        workflow = parser.parse(workflow_def)
        
        # 应该自动创建边
        assert len(workflow.edges) == 2
        edge_pairs = [(e.source, e.target) for e in workflow.edges]
        assert ("a", "b") in edge_pairs
        assert ("b", "c") in edge_pairs
