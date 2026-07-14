"""ExecutiveAgent: guida il flusso richiesta → risposta.

È l'unico agente con la visione d'insieme: riceve ``request.received``,
apre un task, invoca Reasoning Engine e Planner, consegna il piano
all'ExecutionBroker e compone la risposta finale (``response.ready``).

Reasoning, pianificazione ed esecuzione restano sistemi separati: qui sono
solo orchestrati, con ogni passaggio tracciato da eventi.
"""

from __future__ import annotations

import json
from typing import Any

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus
from jarvis.execution import ExecutionBroker
from jarvis.memory import MemoryManager
from jarvis.planning import Plan, Planner, StepStatus
from jarvis.reasoning import ReasoningEngine
from jarvis.tasks import TaskManager, TaskPriority, TaskState


class ExecutiveAgent(BaseAgent):
    """Coordinatore del ciclo cognitivo completo."""

    name = "executive"
    description = "Trasforma le richieste in task, piani ed esecuzioni tracciate"
    subscriptions = ("request.received",)

    def __init__(
        self,
        bus: EventBus,
        reasoning: ReasoningEngine,
        planner: Planner,
        broker: ExecutionBroker,
        tasks: TaskManager,
        memory: MemoryManager,
    ) -> None:
        super().__init__(bus)
        self._reasoning = reasoning
        self._planner = planner
        self._broker = broker
        self._tasks = tasks
        self._memory = memory

    async def handle(self, event: Event) -> None:
        text = str(event.payload.get("text", "")).strip()
        if not text:
            return
        correlation = event.correlation_id or event.event_id

        task = await self._tasks.create(
            title=text[:120],
            priority=TaskPriority(int(event.payload.get("priority", 1))),
            payload={"request": text},
            correlation_id=correlation,
        )
        await self._tasks.transition(task.task_id, TaskState.RUNNING,
                                     "presa in carico")

        context = self._memory.context_for(text)
        reasoning = await self._reasoning.reason(text, context)
        await self.emit("reasoning.completed", {
            "intent": reasoning.intent,
            "analysis": reasoning.analysis,
            "risk": reasoning.risk_note,
        }, correlation)

        plan = await self._planner.build_plan(reasoning, correlation)
        plan = await self._broker.execute_plan(plan)

        answer = self._compose_answer(plan)
        final_state = TaskState.COMPLETED if plan.succeeded() else TaskState.FAILED
        await self._tasks.transition(task.task_id, final_state,
                                     f"piano {plan.plan_id}: {final_state.value}")
        await self.emit("response.ready", {
            "task_id": task.task_id,
            "plan_id": plan.plan_id,
            "success": plan.succeeded(),
            "text": answer,
        }, correlation)

    # ------------------------------------------------------------ risposta

    def _compose_answer(self, plan: Plan) -> str:
        """Compone la risposta finale dai risultati degli step."""
        respond_step = next(
            (s for s in plan.steps if s.action == "respond"
             and s.status == StepStatus.COMPLETED), None)
        template = (respond_step.result or {}).get("template", "llm") \
            if respond_step else "llm"

        results: dict[str, Any] = {
            s.action: s.result for s in plan.steps
            if s.status == StepStatus.COMPLETED and s.action != "respond"
        }
        failures = [f"{s.action}: {s.error}" for s in plan.steps
                    if s.status in (StepStatus.FAILED, StepStatus.DENIED)]

        if template == "system_report" and "system.stats" in results:
            body = self._format_system_report(results["system.stats"])
        elif template == "llm" and "llm.generate" in results:
            body = str(results["llm.generate"].get("text", ""))
        elif template == "file_report" and "fs.list" in results:
            listing = results["fs.list"]
            body = (f"Contenuto di {listing['path']}:\n  "
                    + "\n  ".join(listing["entries"]))
        elif template == "research" and "web.search" in results:
            search = results["web.search"]
            body = (search.get("note") or
                    json.dumps(search.get("results", []), ensure_ascii=False))
        elif template == "ack":
            body = "Fatto. Informazione registrata in memoria."
        else:
            body = json.dumps(results, ensure_ascii=False, default=str)[:1500]

        if failures:
            body += "\n\nStep non completati:\n  " + "\n  ".join(failures)
        return body

    @staticmethod
    def _format_system_report(stats: dict[str, Any]) -> str:
        cpu = stats.get("cpu", {})
        mem = stats.get("memory", {})
        lines = [
            "Report di sistema:",
            f"  CPU: {cpu.get('percent', '?')}% su {int(cpu.get('cores', 0))} core"
            f" (load 1m: {cpu.get('load_1m', '?')})",
            f"  RAM: {mem.get('percent', '?')}% usata — "
            f"{mem.get('available_mb', '?')} MB disponibili su {mem.get('total_mb', '?')} MB",
            f"  Processi attivi: {stats.get('process_count', '?')}",
        ]
        if stats.get("degraded"):
            lines.append("  (metriche in modalità degradata: psutil non installato)")
        return "\n".join(lines)
