"""Workflow parser converts declarative definitions into runtime models."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .errors import WorkflowValidationError
from .models import Edge, Node, Workflow, WorkflowType

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class WorkflowParser:
    """Parser that understands YAML/JSON workflow definitions."""

    def __init__(self, strict: bool = True) -> None:
        self.strict = strict

    def parse(self, data: str, fmt: str = "yaml") -> Workflow:
        if fmt == "yaml":
            if yaml is None:
                raise WorkflowValidationError("PyYAML is required for YAML parsing")
            payload = yaml.safe_load(data)
        elif fmt == "json":
            payload = json.loads(data)
        else:
            raise WorkflowValidationError(f"Unsupported workflow format: {fmt}")
        return self._from_dict(payload)

    def parse_dict(self, payload: Dict[str, Any]) -> Workflow:
        return self._from_dict(payload)

    def _from_dict(self, payload: Dict[str, Any]) -> Workflow:
        if "workflow" in payload:
            payload = payload["workflow"]

        required = {"id", "name", "version", "type", "nodes"}
        missing = required - payload.keys()
        if missing:
            raise WorkflowValidationError(f"Missing required workflow keys: {missing}")

        workflow_type = WorkflowType(payload["type"])

        node_map: Dict[str, Node] = {}
        for node_spec in payload["nodes"]:
            node = self._parse_node(node_spec)
            node_map[node.id] = node

        edges = [self._parse_edge(edge_spec) for edge_spec in payload.get("edges", [])]

        workflow = Workflow(
            id=payload["id"],
            name=payload["name"],
            version=payload["version"],
            type=workflow_type,
            nodes=node_map,
            edges=edges,
            metadata=payload.get("metadata", {}),
        )

        self._validate_workflow(workflow)
        return workflow

    def _parse_node(self, spec: Dict[str, Any]) -> Node:
        if "id" not in spec or "type" not in spec:
            raise WorkflowValidationError("Node must include 'id' and 'type'")

        config = spec.get("config", {})
        retries = int(config.get("retries", spec.get("retries", 0)))
        retry_delay = float(config.get("retry_delay", spec.get("retry_delay", 0.0)))

        return Node(
            id=spec["id"],
            type=spec["type"],
            name=spec.get("name"),
            agent=spec.get("agent"),
            subtype=spec.get("subtype"),
            inputs=spec.get("inputs", {}),
            outputs=spec.get("outputs", []),
            config=config,
            retries=retries,
            retry_delay=retry_delay,
        )

    def _parse_edge(self, spec: Dict[str, Any]) -> Edge:
        if "from" in spec:
            source = spec["from"]
        else:
            source = spec.get("source")
        if "to" in spec:
            target = spec["to"]
        else:
            target = spec.get("target")

        if not source or not target:
            raise WorkflowValidationError("Edge must include 'from/to' or 'source/target'")

        return Edge(source=source, target=target, condition=spec.get("condition"))

    def _validate_workflow(self, workflow: Workflow) -> None:
        node_ids = set(workflow.nodes.keys())
        for edge in workflow.edges:
            if edge.source not in node_ids and edge.source != "start":
                raise WorkflowValidationError(f"Edge source {edge.source} not defined")
            if edge.target not in node_ids and edge.target != "end":
                raise WorkflowValidationError(f"Edge target {edge.target} not defined")

        if self.strict and workflow.type == WorkflowType.DAG:
            self._ensure_acyclic(workflow)

    def _ensure_acyclic(self, workflow: Workflow) -> None:
        visited: Dict[str, str] = {}

        def visit(node_id: str, stack: List[str]) -> None:
            state = visited.get(node_id)
            if state == "temp":
                raise WorkflowValidationError(
                    f"Cycle detected: {' -> '.join(stack + [node_id])}"
                )
            if state == "perm":
                return
            visited[node_id] = "temp"
            for edge in workflow.edges:
                if edge.source == node_id:
                    visit(edge.target, stack + [node_id])
            visited[node_id] = "perm"

        for node_id in workflow.nodes:
            if node_id not in visited:
                visit(node_id, [])

    def serialize(self, workflow: Workflow, fmt: str = "json") -> str:
        data = {
            "workflow": {
                "id": workflow.id,
                "name": workflow.name,
                "version": workflow.version,
                "type": workflow.type.value,
                "nodes": [self._node_to_dict(n) for n in workflow.nodes.values()],
                "edges": [self._edge_to_dict(e) for e in workflow.edges],
                "metadata": workflow.metadata,
            }
        }
        if fmt == "json":
            return json.dumps(data, ensure_ascii=False, indent=2)
        if fmt == "yaml":
            if yaml is None:
                raise WorkflowValidationError("PyYAML is required for YAML serialisation")
            return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        raise WorkflowValidationError(f"Unsupported serialisation format: {fmt}")

    def _node_to_dict(self, node: Node) -> Dict[str, Any]:
        return {
            "id": node.id,
            "type": node.type,
            "name": node.name,
            "agent": node.agent,
            "subtype": node.subtype,
            "inputs": node.inputs,
            "outputs": node.outputs,
            "config": node.config,
            "retries": node.retries,
            "retry_delay": node.retry_delay,
        }

    def _edge_to_dict(self, edge: Edge) -> Dict[str, Any]:
        payload = {"from": edge.source, "to": edge.target}
        if edge.condition:
            payload["condition"] = edge.condition
        return payload
