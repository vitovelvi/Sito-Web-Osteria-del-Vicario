"""Planner: trasforma un ragionamento in un piano multi-step eseguibile.

Il Planner non esegue nulla: produce piani i cui step riferiscono solo azioni
registrate nell'Executor. La strategia è a template per gli intenti noti, con
composizione dinamica di raccolta-contesto → elaborazione → risposta.
"""

from __future__ import annotations

from jarvis.events import Event, EventBus
from jarvis.logging import get_logger
from jarvis.planning.plan import Plan, PlanStep
from jarvis.reasoning import Reasoning

_log = get_logger("planner")


class Planner:
    """Generatore di piani multi-step."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def build_plan(self, reasoning: Reasoning,
                         correlation_id: str | None = None) -> Plan:
        """Costruisce il piano per un ragionamento e lo pubblica sul bus."""
        builder = {
            "system_report": self._plan_system_report,
            "research": self._plan_research,
            "coding": self._plan_generic_llm,
            "memory": self._plan_memory,
            "file_ops": self._plan_file_ops,
            "general": self._plan_generic_llm,
        }.get(reasoning.intent, self._plan_generic_llm)

        plan = builder(reasoning)
        plan.correlation_id = correlation_id
        _log.info("Piano %s: %d step per intento %s",
                  plan.plan_id, len(plan.steps), reasoning.intent)
        await self._bus.publish(Event(
            topic="plan.created",
            payload=plan.to_dict(),
            source="planner",
            correlation_id=correlation_id,
        ))
        return plan

    # ------------------------------------------------------------ template

    def _plan_system_report(self, reasoning: Reasoning) -> Plan:
        stats = PlanStep(
            action="system.stats",
            description="Raccogli metriche di sistema (CPU, RAM, processi)",
        )
        recall = PlanStep(
            action="memory.recall",
            params={"text": "sistema", "limit": 5},
            description="Recupera contesto rilevante dalla memoria",
        )
        respond = PlanStep(
            action="respond",
            params={"template": "system_report", "request": reasoning.request_text},
            depends_on=[stats.step_id, recall.step_id],
            description="Componi il report per l'utente",
        )
        return Plan(goal=reasoning.request_text, steps=[stats, recall, respond])

    def _plan_research(self, reasoning: Reasoning) -> Plan:
        search = PlanStep(
            action="web.search",
            params={"query": reasoning.request_text},
            description="Ricerca informazioni",
        )
        respond = PlanStep(
            action="respond",
            params={"template": "research", "request": reasoning.request_text},
            depends_on=[search.step_id],
            description="Sintetizza i risultati",
        )
        return Plan(goal=reasoning.request_text, steps=[search, respond])

    def _plan_memory(self, reasoning: Reasoning) -> Plan:
        store = PlanStep(
            action="memory.store",
            params={"content": {"note": reasoning.request_text}, "store": "semantic"},
            description="Memorizza l'informazione richiesta",
        )
        respond = PlanStep(
            action="respond",
            params={"template": "ack", "request": reasoning.request_text},
            depends_on=[store.step_id],
            description="Conferma all'utente",
        )
        return Plan(goal=reasoning.request_text, steps=[store, respond])

    def _plan_file_ops(self, reasoning: Reasoning) -> Plan:
        listing = PlanStep(
            action="fs.list",
            params={"path": "."},
            description="Elenca il contenuto della directory di lavoro",
        )
        respond = PlanStep(
            action="respond",
            params={"template": "file_report", "request": reasoning.request_text},
            depends_on=[listing.step_id],
            description="Riporta l'esito",
        )
        return Plan(goal=reasoning.request_text, steps=[listing, respond])

    def _plan_generic_llm(self, reasoning: Reasoning) -> Plan:
        generate = PlanStep(
            action="llm.generate",
            params={
                "prompt": reasoning.request_text,
                "context": reasoning.context,
                "quality": "standard",
            },
            description="Elabora la richiesta con il modello instradato",
        )
        respond = PlanStep(
            action="respond",
            params={"template": "llm", "request": reasoning.request_text},
            depends_on=[generate.step_id],
            description="Consegna la risposta",
        )
        return Plan(goal=reasoning.request_text, steps=[generate, respond])
