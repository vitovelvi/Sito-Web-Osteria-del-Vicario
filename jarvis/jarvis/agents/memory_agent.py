"""MemoryAgent: cura della memoria di lungo periodo.

Mantiene la working memory aggiornata con il dialogo corrente e consolida
in episodica le risposte consegnate. Espone inoltre la ricerca via evento
(``memory.query`` → ``memory.query.result``).
"""

from __future__ import annotations

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus
from jarvis.memory import MemoryManager


class MemoryAgent(BaseAgent):
    """Custode delle memorie."""

    name = "memory"
    description = "Aggiorna working/episodic memory e serve le query"
    subscriptions = ("request.received", "response.ready", "memory.query")

    def __init__(self, bus: EventBus, memory: MemoryManager) -> None:
        super().__init__(bus)
        self._memory = memory

    async def handle(self, event: Event) -> None:
        if event.topic == "request.received":
            self._memory.working.remember(
                {"role": "user", "text": event.payload.get("text", "")},
                tags=["dialogo"], importance=0.6,
            )
        elif event.topic == "response.ready":
            self._memory.working.remember(
                {"role": "jarvis", "text": event.payload.get("text", "")},
                tags=["dialogo"], importance=0.5,
            )
            self._memory.episodic.remember(
                {"request_task": event.payload.get("task_id"),
                 "success": event.payload.get("success"),
                 "answer": str(event.payload.get("text", ""))[:500]},
                tags=["risposta"], importance=0.5,
            )
        elif event.topic == "memory.query":
            hits = self._memory.context_for(
                str(event.payload.get("text", "")),
                limit=int(event.payload.get("limit", 5)),
            )
            await self.emit("memory.query.result", {"hits": hits},
                            event.correlation_id or event.event_id)
