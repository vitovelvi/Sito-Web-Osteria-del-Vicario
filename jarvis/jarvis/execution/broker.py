"""ExecutionBroker: orchestratore della catena di esecuzione.

Per ogni step di un piano applica, nell'ordine e senza eccezioni:
    1. Validation      — lo step è formalmente eseguibile?
    2. Security Layer  — classificazione + gate di conferma;
    3. Sandbox         — timeout, confini, limiti di output;
    4. Executor        — l'azione registrata viene eseguita.

Ogni transizione è pubblicata sul bus (audit + dashboard + self-healing).
"""

from __future__ import annotations

from typing import Any

from jarvis.events import Event, EventBus
from jarvis.execution.executor import Executor
from jarvis.execution.sandbox import Sandbox, SandboxViolation
from jarvis.execution.validation import ValidationError, Validator
from jarvis.logging import get_logger
from jarvis.planning.plan import Plan, PlanStep, StepStatus
from jarvis.security import ConfirmationGate, OperationClassifier

_log = get_logger("execution.broker")


class ExecutionBroker:
    """Esegue piani rispettando dipendenze e catena di sicurezza."""

    def __init__(
        self,
        bus: EventBus,
        validator: Validator,
        classifier: OperationClassifier,
        gate: ConfirmationGate,
        sandbox: Sandbox,
        executor: Executor,
    ) -> None:
        self._bus = bus
        self._validator = validator
        self._classifier = classifier
        self._gate = gate
        self._sandbox = sandbox
        self._executor = executor

    async def execute_plan(self, plan: Plan) -> Plan:
        """Esegue il piano fino a completamento (o blocco).

        Gli step diventano eseguibili quando le loro dipendenze sono
        complete; uno step negato o fallito fa saltare i dipendenti.
        """
        await self._publish(plan, "execution.plan.started", {"goal": plan.goal})
        while not plan.is_complete():
            ready = plan.ready_steps()
            if not ready:
                self._skip_blocked(plan)
                break
            for step in ready:
                await self._execute_step(plan, step)
        topic = "plan.completed" if plan.succeeded() else "plan.failed"
        await self._publish(plan, topic, {
            "goal": plan.goal,
            "steps": [s.to_dict() for s in plan.steps],
        })
        return plan

    # ------------------------------------------------------------ internal

    async def _execute_step(self, plan: Plan, step: PlanStep) -> None:
        step.status = StepStatus.RUNNING
        await self._publish(plan, "execution.step.started", step.to_dict())

        # 1. Validation
        try:
            self._validator.validate(step)
        except ValidationError as exc:
            await self._fail(plan, step, f"validazione: {exc}")
            return

        # 2. Security Layer
        operation = self._classifier.classify(step.action, step.params)
        allowed = await self._gate.authorize(operation, plan.correlation_id)
        if not allowed:
            step.status = StepStatus.DENIED
            step.error = f"negato dal Security Layer ({operation.level.name})"
            await self._publish(plan, "execution.step.denied", step.to_dict())
            return

        # 3-4. Sandbox → Executor
        try:
            step.result = await self._sandbox.run(
                lambda: self._executor.execute(step.action, dict(step.params))
            )
        except SandboxViolation as exc:
            await self._fail(plan, step, f"sandbox: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - il broker isola i fallimenti
            await self._fail(plan, step, str(exc))
            return

        step.status = StepStatus.COMPLETED
        await self._publish(plan, "execution.step.completed", {
            **step.to_dict(),
            "result_preview": _preview(step.result),
        })

    async def _fail(self, plan: Plan, step: PlanStep, error: str) -> None:
        step.status = StepStatus.FAILED
        step.error = error
        _log.warning("Step %s fallito: %s", step.action, error)
        await self._publish(plan, "execution.step.failed", step.to_dict())

    def _skip_blocked(self, plan: Plan) -> None:
        for step in plan.steps:
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.SKIPPED
                step.error = "dipendenze non soddisfatte"

    async def _publish(self, plan: Plan, topic: str, payload: dict[str, Any]) -> None:
        await self._bus.publish(Event(
            topic=topic,
            payload={"plan_id": plan.plan_id, **payload},
            source="execution.broker",
            correlation_id=plan.correlation_id,
        ))


def _preview(result: Any, limit: int = 400) -> str:
    text = str(result)
    return text if len(text) <= limit else text[:limit] + "…"
