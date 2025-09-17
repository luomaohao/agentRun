"""
工作流定义模型
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from enum import Enum
from uuid import uuid4
from datetime import datetime


class WorkflowType(Enum):
    """工作流类型"""
    DAG = "dag"
    STATE_MACHINE = "state_machine"
    HYBRID = "hybrid"


class NodeType(Enum):
    """节点类型"""
    AGENT = "agent"
    TOOL = "tool"
    CONTROL = "control"
    AGGREGATION = "aggregation"
    SUB_WORKFLOW = "sub_workflow"


class ControlNodeSubtype(Enum):
    """控制节点子类型"""
    SWITCH = "switch"
    PARALLEL = "parallel"
    LOOP = "loop"
    CONDITION = "condition"


@dataclass
class Node:
    """工作流节点"""
    id: str
    name: str
    type: NodeType
    subtype: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    inputs: Dict[str, str] = field(default_factory=dict)  # 输入映射
    outputs: List[str] = field(default_factory=list)  # 输出字段
    dependencies: List[str] = field(default_factory=list)  # 依赖节点ID
    timeout: Optional[int] = None  # 超时时间（秒）
    retry_policy: Optional[Dict[str, Any]] = None  # 重试策略
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """验证节点配置"""
        if self.type == NodeType.CONTROL and not self.subtype:
            raise ValueError("Control nodes must have a subtype")
        
        if self.type == NodeType.AGENT and "agent_id" not in self.config:
            raise ValueError("Agent nodes must specify agent_id in config")
        
        if self.type == NodeType.TOOL and "tool_id" not in self.config:
            raise ValueError("Tool nodes must specify tool_id in config")


@dataclass 
class Edge:
    """工作流边"""
    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = ""  # 源节点ID
    target: str = ""  # 目标节点ID
    condition: Optional[str] = None  # 条件表达式
    data_mapping: Dict[str, str] = field(default_factory=dict)  # 数据映射
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    """工作流定义"""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    version: str = "1.0.0"
    type: WorkflowType = WorkflowType.DAG
    description: Optional[str] = None
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)  # 工作流变量
    triggers: List[Dict[str, Any]] = field(default_factory=list)  # 触发器配置
    error_handlers: List[Dict[str, Any]] = field(default_factory=list)  # 错误处理器
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    def get_node(self, node_id: str) -> Optional[Node]:
        """根据ID获取节点"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None
    
    def get_dependencies(self, node_id: str) -> List[Node]:
        """获取节点的依赖节点"""
        node = self.get_node(node_id)
        if not node:
            return []
        
        dependencies = []
        for dep_id in node.dependencies:
            dep_node = self.get_node(dep_id)
            if dep_node:
                dependencies.append(dep_node)
        
        return dependencies
    
    def get_downstream_nodes(self, node_id: str) -> List[Node]:
        """获取节点的下游节点"""
        downstream = []
        for edge in self.edges:
            if edge.source == node_id:
                target_node = self.get_node(edge.target)
                if target_node:
                    downstream.append(target_node)
        
        return downstream
    
    def validate(self) -> List[str]:
        """验证工作流定义的合法性"""
        errors = []
        
        # 检查节点ID唯一性
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            errors.append("Duplicate node IDs found")
        
        # 检查边的合法性
        for edge in self.edges:
            if edge.source not in node_ids:
                errors.append(f"Edge source '{edge.source}' not found in nodes")
            if edge.target not in node_ids:
                errors.append(f"Edge target '{edge.target}' not found in nodes")
        
        # 检查DAG是否有环
        if self.type == WorkflowType.DAG and self._has_cycle():
            errors.append("DAG workflow contains cycles")
        
        # 检查是否有孤立节点
        connected_nodes = set()
        for edge in self.edges:
            connected_nodes.add(edge.source)
            connected_nodes.add(edge.target)
        
        isolated_nodes = set(node_ids) - connected_nodes
        if isolated_nodes and len(self.nodes) > 1:
            errors.append(f"Isolated nodes found: {isolated_nodes}")
        
        return errors
    
    def _has_cycle(self) -> bool:
        """检测是否存在环（用于DAG验证）"""
        # 使用拓扑排序检测环
        from collections import defaultdict, deque
        
        # 构建邻接表和入度表
        adj = defaultdict(list)
        in_degree = defaultdict(int)
        
        for node in self.nodes:
            in_degree[node.id] = 0
        
        for edge in self.edges:
            adj[edge.source].append(edge.target)
            in_degree[edge.target] += 1
        
        # 拓扑排序
        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        visited = 0
        
        while queue:
            node_id = queue.popleft()
            visited += 1
            
            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return visited != len(self.nodes)


@dataclass
class StateDefinition:
    """状态机状态定义"""
    name: str
    type: str = "normal"  # initial, normal, final
    on_enter: List[Dict[str, Any]] = field(default_factory=list)
    on_exit: List[Dict[str, Any]] = field(default_factory=list)
    transitions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StateMachineWorkflow(Workflow):
    """状态机工作流"""
    states: List[StateDefinition] = field(default_factory=list)
    initial_state: str = ""
    final_states: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        self.type = WorkflowType.STATE_MACHINE
