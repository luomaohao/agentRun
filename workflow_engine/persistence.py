"""SQLite backed persistence layer for workflow definitions and executions."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional

from .errors import PersistenceError
from .models import ExecutionContext, ExecutionStatus, Workflow


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT NOT NULL,
        version TEXT NOT NULL,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        definition TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id, version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS executions (
        execution_id TEXT PRIMARY KEY,
        workflow_id TEXT NOT NULL,
        workflow_version TEXT NOT NULL,
        status TEXT NOT NULL,
        context TEXT NOT NULL,
        started_at REAL,
        finished_at REAL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id TEXT NOT NULL,
        node_id TEXT,
        event TEXT NOT NULL,
        payload TEXT,
        created_at REAL
    );
    """,
]


class PersistenceLayer:
    """Persistence layer storing workflows and executions."""

    def __init__(self, database: Optional[str] = None, *, uri: bool = False) -> None:
        if database is None:
            database = "file:workflow_engine?mode=memory&cache=shared"
            uri = True
        self.database = database
        self._uri = uri
        self._lock = threading.RLock()
        self._base_conn = sqlite3.connect(
            self.database, uri=self._uri, check_same_thread=False
        )
        self._apply_schema(self._base_conn)

    def _apply_schema(self, conn: sqlite3.Connection) -> None:
        cursor = conn.cursor()
        for ddl in SCHEMA_SQL:
            cursor.executescript(ddl)
        conn.commit()

    @contextmanager
    def _connection(self) -> Iterable[sqlite3.Connection]:
        try:
            with self._lock:
                yield self._base_conn
        except sqlite3.Error as exc:  # pragma: no cover - hard to reach
            raise PersistenceError(str(exc))
        finally:
            # shared connection remains open for reuse
            pass

    def save_workflow(self, workflow: Workflow) -> None:
        payload = json.dumps({
            "id": workflow.id,
            "name": workflow.name,
            "version": workflow.version,
            "type": workflow.type.value,
            "nodes": {node_id: self._node_json(node) for node_id, node in workflow.nodes.items()},
            "edges": [edge.__dict__ for edge in workflow.edges],
            "metadata": workflow.metadata,
        })
        with self._connection() as conn:
            conn.execute(
                "REPLACE INTO workflows (id, version, name, type, definition) VALUES (?, ?, ?, ?, ?)",
                (workflow.id, workflow.version, workflow.name, workflow.type.value, payload),
            )
            conn.commit()

    def load_workflow(self, workflow_id: str, version: Optional[str] = None) -> Workflow:
        query = "SELECT definition FROM workflows WHERE id = ?"
        params = [workflow_id]
        if version:
            query += " AND version = ?"
            params.append(version)
        else:
            query += " ORDER BY created_at DESC LIMIT 1"
        with self._connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                raise PersistenceError(f"Workflow {workflow_id} not found")
            definition = json.loads(row[0])
        return self._workflow_from_json(definition)

    def create_execution(self, workflow: Workflow, context: ExecutionContext) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO executions (execution_id, workflow_id, workflow_version, status, context, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    context.execution_id,
                    workflow.id,
                    workflow.version,
                    context.status.value,
                    json.dumps(context.variables),
                    context.start_time,
                ),
            )
            conn.commit()

    def update_execution_status(
        self, context: ExecutionContext, status: ExecutionStatus
    ) -> None:
        context.status = status
        with self._connection() as conn:
            conn.execute(
                "UPDATE executions SET status = ?, finished_at = ? WHERE execution_id = ?",
                (status.value, time_or_none(status, context), context.execution_id),
            )
            conn.commit()

    def record_event(
        self, execution_id: str, event: str, node_id: Optional[str] = None, payload: Optional[Dict[str, str]] = None
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO execution_events (execution_id, node_id, event, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    execution_id,
                    node_id,
                    event,
                    json.dumps(payload or {}),
                    time.time(),
                ),
            )
            conn.commit()

    def fetch_execution_events(self, execution_id: str) -> Iterable[Dict[str, str]]:
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT node_id, event, payload, created_at FROM execution_events WHERE execution_id = ? ORDER BY id",
                (execution_id,),
            )
            for node_id, event, payload, created_at in cursor.fetchall():
                yield {
                    "node_id": node_id,
                    "event": event,
                    "payload": json.loads(payload or "{}"),
                    "created_at": created_at,
                }

    def _workflow_from_json(self, data: Dict[str, Any]) -> Workflow:
        from .parser import WorkflowParser

        parser = WorkflowParser()
        return parser.parse_dict({"workflow": data})

    def _node_json(self, node) -> Dict[str, Any]:
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


def time_or_none(status: ExecutionStatus, context: ExecutionContext) -> Optional[float]:
    if status in {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.COMPENSATED}:
        return time.time()
    return None
