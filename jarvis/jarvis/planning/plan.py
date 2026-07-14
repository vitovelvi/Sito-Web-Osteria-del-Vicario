"""Strutture dati dei piani multi-step."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    """Ciclo di vita di uno step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DENIED = "denied"  # bloccato dal Security Layer


@dataclass(slots=True)
class PlanStep:
    """Singolo step di un piano.

    Attributes:
        action: nome dell'azione registrata nell'Executor (mai comandi liberi).
        params: parametri dell'azione.
        description: descrizione leggibile.
        depends_on: id degli step che devono completarsi prima.
        step_id: identificativo.
        status: stato corrente.
        result: risultato dell'esecuzione.
        error: errore, se fallito.
    """

    action: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    step_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "depends_on": self.depends_on,
            "status": self.status.value,
            "error": self.error,
        }


@dataclass(slots=True)
class Plan:
    """Piano multi-step generato dal Planner.

    Attributes:
        goal: obiettivo della richiesta.
        steps: step ordinati (l'ordine rispetta le dipendenze).
        plan_id: identificativo.
        correlation_id: catena causale (richiesta di origine).
    """

    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    correlation_id: str | None = None

    def ready_steps(self) -> list[PlanStep]:
        """Step eseguibili ora: pendenti con dipendenze completate."""
        done = {s.step_id for s in self.steps if s.status == StepStatus.COMPLETED}
        return [
            step for step in self.steps
            if step.status == StepStatus.PENDING and set(step.depends_on) <= done
        ]

    def is_complete(self) -> bool:
        """Vero quando nessuno step è più pendente o in esecuzione."""
        return all(
            s.status not in (StepStatus.PENDING, StepStatus.RUNNING) for s in self.steps
        )

    def succeeded(self) -> bool:
        return all(s.status == StepStatus.COMPLETED for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "correlation_id": self.correlation_id,
            "steps": [s.to_dict() for s in self.steps],
        }
