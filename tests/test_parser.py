import pytest

from workflow_engine.errors import WorkflowValidationError
from workflow_engine.parser import WorkflowParser


def sample_workflow_dict():
    return {
        "workflow": {
            "id": "wf1",
            "name": "Test Workflow",
            "version": "1.0",
            "type": "dag",
            "nodes": [
                {"id": "start", "type": "task"},
                {"id": "end", "type": "task"},
            ],
            "edges": [
                {"from": "start", "to": "end"},
            ],
        }
    }


def test_parse_workflow_json():
    parser = WorkflowParser()
    workflow = parser.parse_dict(sample_workflow_dict())
    assert workflow.id == "wf1"
    assert len(workflow.nodes) == 2
    assert workflow.edges[0].source == "start"


def test_cycle_detection():
    parser = WorkflowParser()
    definition = sample_workflow_dict()
    definition["workflow"]["edges"].append({"from": "end", "to": "start"})
    with pytest.raises(WorkflowValidationError):
        parser.parse_dict(definition)
