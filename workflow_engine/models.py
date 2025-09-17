"""Core data models used by the workflow engine."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Iterable, Set


class WorkflowType(str, enum.Enum):
    """Supported workflow types."""

    DAG = "dag"
    STATE_MACHINE = "state_machine"
    HYBRID = "hybrid"


@dataclass
class Node:
    """A node in the workflow graph."""

    id: str
    type: str
    name: Optional[str] = None
    agent: Optional[str] = None
    subtype: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    retry_delay: float = 0.0
    compensation: Optional[Callable[["ExecutionContext", Dict[str, Any]], None]] = None


@dataclass
class Edge:
    """Edge connecting two nodes."""

    source: str
    target: str
    condition: Optional[str] = None


@dataclass
class Workflow:
    """Workflow definition as parsed from YAML/JSON."""

    id: str
    name: str
    version: str
    type: WorkflowType
    nodes: Dict[str, Node]
    edges: List[Edge]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def upstream(self, node_id: str) -> List[Node]:
        return [self.nodes[e.source] for e in self.edges if e.target == node_id]

    def downstream(self, node_id: str) -> List[Node]:
        return [self.nodes[e.target] for e in self.edges if e.source == node_id]


class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class ExecutionContext:
    """Runtime context for a workflow execution."""

    workflow_id: str
    execution_id: str
    variables: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    node_results: Dict[str, Any] = field(default_factory=dict)
    status: ExecutionStatus = ExecutionStatus.PENDING
    retry_counts: Dict[str, int] = field(default_factory=dict)

    def record_result(self, node_id: str, result: Any) -> None:
        self.node_results[node_id] = result

    def get_retry_count(self, node_id: str) -> int:
        return self.retry_counts.get(node_id, 0)

    def increment_retry(self, node_id: str) -> int:
        count = self.retry_counts.get(node_id, 0) + 1
        self.retry_counts[node_id] = count
        return count


@dataclass
class ExecutionPlan:
    """Plan containing ordered tasks for execution."""

    workflow: Workflow
    start_nodes: List[Node]
    ready: List[str] = field(default_factory=list)
    completed: Set[str] = field(default_factory=set)

    def mark_ready(self, node_id: str) -> None:
        if node_id not in self.ready:
            self.ready.append(node_id)

    def next_batch(self, batch_size: int) -> List[str]:
        batch = self.ready[:batch_size]
        self.ready = self.ready[batch_size:]
        return batch

    def mark_completed(self, node_id: str) -> None:
        self.completed.add(node_id)

    def outstanding(self) -> Iterable[Node]:
        for node_id in self.workflow.nodes:
            if node_id not in self.completed:
                yield self.workflow.nodes[node_id]


@dataclass
class ScheduledTask:
    """Wrapper for scheduled node execution."""

    node: Node
    context: ExecutionContext
    dependencies: List[str] = field(default_factory=list)


@dataclass
class StateTransition:
    """Represents a state transition in the state machine."""

    source: str
    target: str
    condition: Optional[Callable[[ExecutionContext], bool]] = None
    action: Optional[Callable[[ExecutionContext], None]] = None


@dataclass
class StateMachineDefinition:
    """Definition of a state machine driven workflow."""

    states: Set[str]
    initial_state: str
    final_states: Set[str]
    transitions: List[StateTransition]

    def get_transitions(self, state: str) -> List[StateTransition]:
        return [t for t in self.transitions if t.source == state]
