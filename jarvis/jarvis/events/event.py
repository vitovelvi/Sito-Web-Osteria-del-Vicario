"""Definizione dell'evento, unità di comunicazione universale del sistema.

Ogni componente di JARVIS comunica esclusivamente pubblicando e sottoscrivendo
eventi: nessuna chiamata diretta tra sottosistemi.

I topic sono gerarchici, separati da punto, ad esempio:
    system.metrics, file.created, request.received, plan.created,
    execution.step.completed, security.confirmation.required, task.updated
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class Event:
    """Evento immutabile.

    Attributes:
        topic: topic gerarchico (es. ``system.metrics``).
        payload: dati dell'evento, serializzabili in JSON.
        source: componente che ha emesso l'evento.
        correlation_id: collega eventi della stessa catena causale
            (richiesta → piano → step → risultato).
        event_id: identificativo univoco.
        timestamp: istante di emissione (ISO-8601, UTC).
    """

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    correlation_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_now_iso)

    def child(self, topic: str, payload: dict[str, Any], source: str) -> "Event":
        """Crea un evento derivato che eredita la catena di correlazione."""
        return Event(
            topic=topic,
            payload=payload,
            source=source,
            correlation_id=self.correlation_id or self.event_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Rappresentazione serializzabile (dashboard, log, memoria)."""
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
