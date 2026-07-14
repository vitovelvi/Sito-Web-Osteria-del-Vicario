"""CodingAgent: generazione di codice su richiesta.

Serve ``coding.request`` e pubblica ``coding.completed`` con il codice
proposto. Il codice generato NON viene mai eseguito: al più viene salvato
nella sandbox tramite l'azione registrata ``fs.write`` (Livello 1), passando
per l'intera catena di esecuzione.
"""

from __future__ import annotations

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus
from jarvis.llm import LLMRequest, LLMRouter, Quality
from jarvis.llm.base import ProviderUnavailable


class CodingAgent(BaseAgent):
    """Genera codice tramite il LLM Router (qualità alta)."""

    name = "coding"
    description = "Propone codice; mai esecuzione diretta"
    subscriptions = ("coding.request",)

    def __init__(self, bus: EventBus, router: LLMRouter) -> None:
        super().__init__(bus)
        self._router = router

    async def handle(self, event: Event) -> None:
        spec = str(event.payload.get("text", "")).strip()
        if not spec:
            return
        correlation = event.correlation_id or event.event_id
        try:
            response = await self._router.generate(LLMRequest(
                prompt=(f"Scrivi il codice richiesto, completo e commentato.\n"
                        f"Specifica: {spec}"),
                quality=Quality.BEST,
                max_tokens=2000,
                temperature=0.1,
            ))
            await self.emit("coding.completed", {
                "spec": spec,
                "code": response.text,
                "provider": response.provider,
            }, correlation)
        except ProviderUnavailable as exc:
            await self.emit("coding.failed",
                            {"spec": spec, "error": str(exc)}, correlation)
