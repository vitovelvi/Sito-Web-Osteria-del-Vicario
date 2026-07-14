"""Execution System di JARVIS.

Catena obbligatoria per ogni step:
    Planner → ExecutionBroker → Validation → Sandbox → Executor

Nessun componente (LLM incluso) può raggiungere direttamente il sistema:
solo azioni registrate nell'Executor sono eseguibili.
"""

from jarvis.execution.executor import ActionContext, ActionSpec, Executor
from jarvis.execution.validation import ValidationError, Validator
from jarvis.execution.sandbox import Sandbox, SandboxViolation
from jarvis.execution.broker import ExecutionBroker

__all__ = [
    "ActionContext", "ActionSpec", "Executor",
    "Validator", "ValidationError",
    "Sandbox", "SandboxViolation",
    "ExecutionBroker",
]
