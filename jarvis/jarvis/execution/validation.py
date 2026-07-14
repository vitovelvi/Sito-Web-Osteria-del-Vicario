"""Validation: primo filtro della catena di esecuzione.

Verifica che uno step sia formalmente eseguibile PRIMA della classificazione
di sicurezza: azione registrata, parametri completi e serializzabili, nessun
tentativo di esecuzione arbitraria.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis.execution.executor import Executor
from jarvis.planning.plan import PlanStep


class ValidationError(Exception):
    """Step non valido: non deve raggiungere la sandbox."""


class Validator:
    """Valida gli step di piano contro il registro delle azioni."""

    # Nomi che non devono MAI comparire come azione: barriera esplicita
    # contro qualunque tentativo di esecuzione diretta.
    _FORBIDDEN = frozenset({"shell", "bash", "exec", "eval", "terminal", "cmd"})

    def __init__(self, executor: Executor) -> None:
        self._executor = executor

    def validate(self, step: PlanStep) -> None:
        """Solleva :class:`ValidationError` se lo step non è eseguibile."""
        action = step.action.strip().lower()
        if not action:
            raise ValidationError("Step senza azione")
        if action in self._FORBIDDEN or action.split(".")[0] in self._FORBIDDEN:
            raise ValidationError(
                f"Azione vietata dalla policy di esecuzione: {step.action!r}"
            )
        spec = self._executor.spec(step.action)
        if spec is None:
            raise ValidationError(f"Azione non registrata: {step.action!r}")

        missing = [p for p in spec.required_params if p not in step.params]
        if missing:
            raise ValidationError(
                f"Parametri mancanti per {step.action!r}: {', '.join(missing)}"
            )
        self._ensure_serializable(step.params)

    @staticmethod
    def _ensure_serializable(params: dict[str, Any]) -> None:
        try:
            json.dumps(params)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Parametri non serializzabili: {exc}") from exc
