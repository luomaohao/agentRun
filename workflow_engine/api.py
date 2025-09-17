"""HTTP API for workflow management and monitoring."""
from __future__ import annotations

from typing import Any, Dict, Optional

try:  # pragma: no cover - optional dependency
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore
    BaseModel = object  # type: ignore
    HTTPException = Exception  # type: ignore

from .engine import ExecutionEngine
from .parser import WorkflowParser


class WorkflowPayload(BaseModel):  # type: ignore[misc]
    workflow: Dict[str, Any]


class ExecutionRequest(BaseModel):  # type: ignore[misc]
    workflow_id: str
    version: Optional[str] = None
    context: Dict[str, Any] = {}


def create_app(engine: ExecutionEngine) -> Any:
    if FastAPI is None:  # pragma: no cover - fallback for missing dependency
        raise RuntimeError("FastAPI is required to create the API application")

    parser = WorkflowParser()
    app = FastAPI(title="Workflow Engine", version="1.0.0")

    @app.post("/workflows")
    def create_workflow(payload: WorkflowPayload) -> Dict[str, str]:
        workflow = parser.parse_dict(payload.workflow)
        engine.persistence.save_workflow(workflow)
        return {"id": workflow.id, "version": workflow.version}

    @app.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        try:
            workflow = engine.persistence.load_workflow(workflow_id, version)
        except Exception as exc:  # pragma: no cover - HTTP mapping
            raise HTTPException(status_code=404, detail=str(exc))
        return parser.serialize(workflow, fmt="json")  # type: ignore[return-value]

    @app.post("/executions")
    async def start_execution(request: ExecutionRequest) -> Dict[str, str]:
        workflow = engine.persistence.load_workflow(request.workflow_id, request.version)
        execution_id = await engine.execute_workflow(workflow, request.context)
        return {"execution_id": execution_id}

    @app.get("/executions/{execution_id}")
    def get_execution(execution_id: str) -> Dict[str, Any]:
        with engine.persistence._connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT workflow_id, workflow_version, status FROM executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="execution not found")
        events = list(engine.persistence.fetch_execution_events(execution_id))
        return {
            "execution_id": execution_id,
            "workflow_id": row[0],
            "workflow_version": row[1],
            "status": row[2],
            "events": events,
        }

    return app
