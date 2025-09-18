"""
工作流解析器
"""
import yaml
import json
from typing import Dict, Any, List, Optional, Union
from pathlib import Path

from ..models.workflow import (
    Workflow, Node, Edge, NodeType, WorkflowType,
    ControlNodeSubtype, StateDefinition, StateMachineWorkflow
)
from ..exceptions import WorkflowParseError, WorkflowValidationError


class WorkflowParser:
    """工作流解析器"""
    
    def __init__(self):
        self.parsers = {
            'yaml': self._parse_yaml,
            'yml': self._parse_yaml,
            'json': self._parse_json
        }
    
    def parse(self, source: Union[str, Path, Dict[str, Any]]) -> Workflow:
        """
        解析工作流定义
        
        Args:
            source: 工作流定义来源，可以是文件路径、字符串或字典
            
        Returns:
            Workflow: 解析后的工作流对象
        """
        if isinstance(source, dict):
            return self._parse_dict(source)
        
        if isinstance(source, (str, Path)):
            path = Path(source)
            if path.exists() and path.is_file():
                return self.parse_file(path)
            else:
                # 尝试作为YAML/JSON字符串解析
                return self.parse_string(str(source))
        
        raise WorkflowParseError(f"Unsupported source type: {type(source)}")
    
    def parse_file(self, file_path: Path) -> Workflow:
        """解析工作流文件"""
        suffix = file_path.suffix.lower().lstrip('.')
        if suffix not in self.parsers:
            raise WorkflowParseError(f"Unsupported file format: {suffix}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        data = self.parsers[suffix](content)
        return self._parse_dict(data)
    
    def parse_string(self, content: str) -> Workflow:
        """解析工作流字符串"""
        # 尝试解析为YAML
        try:
            data = self._parse_yaml(content)
            return self._parse_dict(data)
        except Exception:
            pass
        
        # 尝试解析为JSON
        try:
            data = self._parse_json(content)
            return self._parse_dict(data)
        except Exception:
            pass
        
        raise WorkflowParseError("Failed to parse workflow string as YAML or JSON")
    
    def _parse_yaml(self, content: str) -> Dict[str, Any]:
        """解析YAML格式"""
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise WorkflowParseError(f"Failed to parse YAML: {e}")
    
    def _parse_json(self, content: str) -> Dict[str, Any]:
        """解析JSON格式"""
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise WorkflowParseError(f"Failed to parse JSON: {e}")
    
    def _parse_dict(self, data: Dict[str, Any]) -> Workflow:
        """解析字典格式的工作流定义"""
        if 'workflow' in data:
            data = data['workflow']
        
        # 确定工作流类型
        workflow_type = WorkflowType(data.get('type', 'dag'))
        
        if workflow_type == WorkflowType.STATE_MACHINE:
            return self._parse_state_machine_workflow(data)
        else:
            return self._parse_dag_workflow(data)
    
    def _parse_dag_workflow(self, data: Dict[str, Any]) -> Workflow:
        """解析DAG工作流"""
        workflow = Workflow(
            id=data.get('id', ''),
            name=data.get('name', ''),
            version=data.get('version', '1.0.0'),
            type=WorkflowType(data.get('type', 'dag')),
            description=data.get('description'),
            variables=data.get('variables', {}),
            triggers=data.get('triggers', []),
            error_handlers=data.get('error_handlers', []),
            metadata=data.get('metadata', {})
        )
        
        # 解析节点
        nodes_data = data.get('nodes', [])
        for node_data in nodes_data:
            node = self._parse_node(node_data)
            workflow.nodes.append(node)
        
        # 解析边
        edges_data = data.get('edges', [])
        for edge_data in edges_data:
            edge = self._parse_edge(edge_data)
            workflow.edges.append(edge)
        
        # 如果没有显式定义边，从节点依赖关系推断
        if not workflow.edges:
            workflow.edges = self._infer_edges_from_dependencies(workflow.nodes)
        
        # 验证工作流
        errors = workflow.validate()
        if errors:
            raise WorkflowValidationError(f"Workflow validation failed: {errors}")
        
        return workflow
    
    def _parse_state_machine_workflow(self, data: Dict[str, Any]) -> StateMachineWorkflow:
        """解析状态机工作流"""
        workflow = StateMachineWorkflow(
            id=data.get('id', ''),
            name=data.get('name', ''),
            version=data.get('version', '1.0.0'),
            description=data.get('description'),
            initial_state=data.get('initial_state', ''),
            final_states=data.get('final_states', []),
            metadata=data.get('metadata', {})
        )
        
        # 解析状态
        states_data = data.get('states', [])
        for state_data in states_data:
            state = self._parse_state(state_data)
            workflow.states.append(state)
        
        # 验证状态机
        if not workflow.initial_state:
            raise WorkflowValidationError("State machine must have an initial state")
        
        return workflow
    
    def _parse_node(self, data: Dict[str, Any]) -> Node:
        """解析节点"""
        node_type = NodeType(data.get('type', 'agent'))
        
        # 处理配置
        config = data.get('config', {})
        if node_type == NodeType.AGENT and 'agent' in data:
            config['agent_id'] = data['agent']
        elif node_type == NodeType.TOOL and 'tool' in data:
            config['tool_id'] = data['tool']
        
        node = Node(
            id=data.get('id', ''),
            name=data.get('name', data.get('id', '')),
            type=node_type,
            subtype=data.get('subtype'),
            config=config,
            inputs=data.get('inputs', {}),
            outputs=data.get('outputs', []),
            dependencies=data.get('dependencies', []),
            timeout=data.get('timeout'),
            retry_policy=data.get('retry_policy'),
            metadata=data.get('metadata', {})
        )
        
        # 处理控制节点的特殊配置
        if node.type == NodeType.CONTROL:
            self._parse_control_node_config(node, data)
        
        return node
    
    def _parse_control_node_config(self, node: Node, data: Dict[str, Any]):
        """解析控制节点配置"""
        if node.subtype == ControlNodeSubtype.SWITCH.value:
            node.config['condition'] = data.get('condition', '')
            node.config['branches'] = data.get('branches', [])
        elif node.subtype == ControlNodeSubtype.LOOP.value:
            node.config['condition'] = data.get('condition', '')
            node.config['max_iterations'] = data.get('max_iterations', 100)
        elif node.subtype == ControlNodeSubtype.PARALLEL.value:
            node.config['branches'] = data.get('branches', [])
            node.config['wait_all'] = data.get('wait_all', True)
    
    def _parse_edge(self, data: Dict[str, Any]) -> Edge:
        """解析边"""
        edge = Edge(
            source=data.get('from', data.get('source', '')),
            target=data.get('to', data.get('target', '')),
            condition=data.get('condition'),
            data_mapping=data.get('data_mapping', {}),
            metadata=data.get('metadata', {})
        )
        
        # 处理简化格式
        if 'from' in data and 'to' in data and len(data) == 2:
            # 简单边定义：只有 from 和 to
            pass
        
        return edge
    
    def _parse_state(self, data: Dict[str, Any]) -> StateDefinition:
        """解析状态定义"""
        return StateDefinition(
            name=data.get('name', ''),
            type=data.get('type', 'normal'),
            on_enter=data.get('on_enter', []),
            on_exit=data.get('on_exit', []),
            transitions=data.get('transitions', []),
            metadata=data.get('metadata', {})
        )
    
    def _infer_edges_from_dependencies(self, nodes: List[Node]) -> List[Edge]:
        """从节点依赖关系推断边"""
        edges = []
        for node in nodes:
            for dep_id in node.dependencies:
                edge = Edge(source=dep_id, target=node.id)
                edges.append(edge)
        return edges
    
    def optimize_workflow(self, workflow: Workflow) -> Workflow:
        """优化工作流"""
        # 识别可并行执行的节点组
        parallel_groups = self._identify_parallel_groups(workflow)
        
        # 在元数据中标记并行组信息
        for group_id, nodes in enumerate(parallel_groups):
            for node_id in nodes:
                node = workflow.get_node(node_id)
                if node:
                    node.metadata['parallel_group'] = group_id
        
        return workflow
    
    def _identify_parallel_groups(self, workflow: Workflow) -> List[List[str]]:
        """识别可并行执行的节点组"""
        from collections import defaultdict, deque
        
        # 构建邻接表
        adj = defaultdict(list)
        in_degree = defaultdict(int)
        
        for node in workflow.nodes:
            in_degree[node.id] = len(node.dependencies)
        
        for edge in workflow.edges:
            adj[edge.source].append(edge.target)
        
        # 分层拓扑排序
        groups = []
        remaining_nodes = set(node.id for node in workflow.nodes)
        
        while remaining_nodes:
            # 找出当前层可以并行执行的节点
            current_group = []
            for node_id in remaining_nodes:
                if in_degree[node_id] == 0:
                    current_group.append(node_id)
            
            if not current_group:
                # 存在循环依赖
                break
            
            groups.append(current_group)
            
            # 更新剩余节点和入度
            for node_id in current_group:
                remaining_nodes.remove(node_id)
                for neighbor in adj[node_id]:
                    in_degree[neighbor] -= 1
        
        return groups
