"""VoiceAgent: ponte tra la pipeline vocale e il resto del sistema.

Traduce le trascrizioni (``voice.transcript``) in richieste standard
(``request.received``) e rimanda le risposte pronte alla sintesi vocale
(``voice.speak``). La pipeline vocale vera e propria vive in
:mod:`jarvis.voice.pipeline`.
"""

from __future__ import annotations

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus


class VoiceAgent(BaseAgent):
    """Adatta l'I/O vocale al protocollo a eventi del sistema."""

    name = "voice"
    description = "Collega trascrizioni vocali e sintesi alle richieste"
    subscriptions = ("voice.transcript", "response.ready")

    def __init__(self, bus: EventBus) -> None:
        super().__init__(bus)
        self._voice_correlations: set[str] = set()

    async def handle(self, event: Event) -> None:
        if event.topic == "voice.transcript":
            correlation = event.correlation_id or event.event_id
            self._voice_correlations.add(correlation)
            await self.emit("request.received", {
                "text": str(event.payload.get("text", "")),
                "channel": "voice",
            }, correlation)
        elif event.topic == "response.ready":
            # Sintetizza solo le risposte a richieste arrivate dalla voce.
            if event.correlation_id in self._voice_correlations:
                self._voice_correlations.discard(event.correlation_id)
                await self.emit("voice.speak", {
                    "text": str(event.payload.get("text", "")),
                }, event.correlation_id)
