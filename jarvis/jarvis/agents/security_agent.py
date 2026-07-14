"""SecurityAgent: vigilanza su sicurezza e salute del sistema.

Osserva gli eventi di sicurezza e gli allarmi di sistema, li trasforma in
notifiche per l'utente e mantiene un registro consultabile dalla dashboard.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus

_SEVERITY = {
    "security.confirmation.required": "warning",
    "security.confirmation.denied": "warning",
    "system.alert.cpu": "critical",
    "system.alert.memory": "critical",
    "healing.detected": "info",
}


class SecurityAgent(BaseAgent):
    """Sorveglia sicurezza, allarmi e guarigioni; genera notifiche."""

    name = "security"
    description = "Vigila su conferme, allarmi di sistema e anomalie"
    subscriptions = ("security.*", "system.alert.*", "healing.detected")

    def __init__(self, bus: EventBus, max_notifications: int = 100) -> None:
        super().__init__(bus)
        self._notifications: deque[dict[str, Any]] = deque(maxlen=max_notifications)

    async def handle(self, event: Event) -> None:
        severity = _SEVERITY.get(event.topic)
        if severity is None:
            return  # es. security.confirmation.granted: audit senza notifica
        notification = {
            "ts": event.timestamp,
            "severity": severity,
            "topic": event.topic,
            "detail": event.payload,
        }
        self._notifications.append(notification)
        await self.emit("notification.created", notification,
                        event.correlation_id)

    def notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        """Ultime notifiche, per la dashboard."""
        return list(self._notifications)[-limit:]
