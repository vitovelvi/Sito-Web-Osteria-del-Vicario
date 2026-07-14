"""ResearchAgent: approfondimenti su richiesta.

Serve ``research.request``: raccoglie contesto dalla memoria, interroga il
LLM Router per una sintesi ragionata e pubblica ``research.completed``.
Quando la ricerca web sarà configurata (azione ``web.search``), il flusso
si arricchisce automaticamente senza modificare questo agente.
"""

from __future__ import annotations

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus
from jarvis.llm import LLMRequest, LLMRouter, Quality
from jarvis.llm.base import ProviderUnavailable
from jarvis.memory import MemoryManager


class ResearchAgent(BaseAgent):
    """Conduce ricerche e sintesi su richiesta."""

    name = "research"
    description = "Sintesi ragionate da memoria e fonti disponibili"
    subscriptions = ("research.request",)

    def __init__(self, bus: EventBus, router: LLMRouter,
                 memory: MemoryManager) -> None:
        super().__init__(bus)
        self._router = router
        self._memory = memory

    async def handle(self, event: Event) -> None:
        topic_text = str(event.payload.get("text", "")).strip()
        if not topic_text:
            return
        correlation = event.correlation_id or event.event_id
        context = self._memory.context_for(topic_text, limit=5)
        try:
            response = await self._router.generate(LLMRequest(
                prompt=(f"Fai una sintesi ragionata su: {topic_text}\n"
                        f"Contesto noto: {context}"),
                quality=Quality.STANDARD,
                max_tokens=800,
            ))
            summary = response.text
        except ProviderUnavailable:
            summary = ("Ricerca registrata; nessun provider LLM disponibile "
                       "per la sintesi in questo momento.")
        self._memory.semantic.remember(
            {"research": topic_text, "summary": summary[:1000]},
            tags=["research"], importance=0.6,
        )
        await self.emit("research.completed",
                        {"topic": topic_text, "summary": summary}, correlation)
