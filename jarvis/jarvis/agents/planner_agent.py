"""PlannerAgent: interfaccia a eventi verso il Planner.

Permette a qualsiasi componente (voce, integrazioni, altri agenti) di
richiedere un piano pubblicando ``plan.request``; il piano risultante è
pubblicato dal Planner stesso come ``plan.created``.
"""

from __future__ import annotations

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus
from jarvis.planning import Planner
from jarvis.reasoning import ReasoningEngine


class PlannerAgent(BaseAgent):
    """Costruisce piani su richiesta via bus."""

    name = "planner"
    description = "Trasforma richieste in piani multi-step (via plan.request)"
    subscriptions = ("plan.request",)

    def __init__(self, bus: EventBus, reasoning: ReasoningEngine,
                 planner: Planner) -> None:
        super().__init__(bus)
        self._reasoning = reasoning
        self._planner = planner

    async def handle(self, event: Event) -> None:
        text = str(event.payload.get("text", "")).strip()
        if not text:
            return
        reasoning = await self._reasoning.reason(text)
        await self._planner.build_plan(
            reasoning, event.correlation_id or event.event_id
        )
