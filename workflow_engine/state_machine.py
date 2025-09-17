"""State machine service for stateful workflows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .models import ExecutionContext, StateMachineDefinition, StateTransition


@dataclass
class StateMachineInstance:
    """Runtime state for a state machine execution."""

    definition: StateMachineDefinition
    current_state: str

    def is_finished(self) -> bool:
        return self.current_state in self.definition.final_states


class StateMachineService:
    """Executes state machine transitions based on the execution context."""

    def __init__(self) -> None:
        self._definitions: Dict[str, StateMachineDefinition] = {}

    def register(self, workflow_id: str, definition: StateMachineDefinition) -> None:
        self._definitions[workflow_id] = definition

    def get_definition(self, workflow_id: str) -> StateMachineDefinition:
        return self._definitions[workflow_id]

    def create_instance(self, workflow_id: str) -> StateMachineInstance:
        definition = self.get_definition(workflow_id)
        return StateMachineInstance(definition=definition, current_state=definition.initial_state)

    def transition(
        self, instance: StateMachineInstance, context: ExecutionContext
    ) -> Optional[StateTransition]:
        definition = instance.definition
        for transition in definition.get_transitions(instance.current_state):
            if transition.condition is None or transition.condition(context):
                if transition.action:
                    transition.action(context)
                instance.current_state = transition.target
                return transition
        return None
