"""Self-Healing: rilevamento, classificazione, retry, rollback, recovery.

Componenti:
    - :class:`ErrorClassifier`   — assegna una classe a ogni errore;
    - :class:`RetryPolicy`       — backoff esponenziale per errori transitori;
    - :class:`RollbackManager`   — undo registrati esplicitamente dalle azioni;
    - :class:`RecoverySupervisor`— ascolta gli eventi di errore sul bus e
      applica la strategia adeguata, pubblicando ``healing.*``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

from jarvis.events import Event, EventBus
from jarvis.logging import get_logger

_log = get_logger("healing")


class ErrorClass(str, Enum):
    """Classi di errore riconosciute dal sistema."""

    TRANSIENT = "transient"    # rete, timeout: si ritenta
    RESOURCE = "resource"      # memoria/disco esauriti: si degrada
    LOGIC = "logic"            # bug o input non valido: non si ritenta
    EXTERNAL = "external"      # servizio terzo guasto: failover/attesa
    FATAL = "fatal"            # incoerenza interna: si isola il componente


# Mappatura per tipo di eccezione e per frammenti nel messaggio.
_TYPE_MAP: dict[str, ErrorClass] = {
    "TimeoutError": ErrorClass.TRANSIENT,
    "ConnectionError": ErrorClass.TRANSIENT,
    "ConnectionResetError": ErrorClass.TRANSIENT,
    "URLError": ErrorClass.EXTERNAL,
    "HTTPError": ErrorClass.EXTERNAL,
    "ProviderUnavailable": ErrorClass.EXTERNAL,
    "MemoryError": ErrorClass.RESOURCE,
    "OSError": ErrorClass.RESOURCE,
    "KeyError": ErrorClass.LOGIC,
    "ValueError": ErrorClass.LOGIC,
    "TypeError": ErrorClass.LOGIC,
    "ValidationError": ErrorClass.LOGIC,
    "SandboxViolation": ErrorClass.LOGIC,
}
_MESSAGE_HINTS: tuple[tuple[str, ErrorClass], ...] = (
    ("timeout", ErrorClass.TRANSIENT),
    ("temporarily", ErrorClass.TRANSIENT),
    ("connection", ErrorClass.TRANSIENT),
    ("no space", ErrorClass.RESOURCE),
    ("memory", ErrorClass.RESOURCE),
    ("rate limit", ErrorClass.EXTERNAL),
    ("unauthorized", ErrorClass.EXTERNAL),
)


class ErrorClassifier:
    """Classifica errori da eccezione o da payload di evento."""

    def classify_exception(self, exc: BaseException) -> ErrorClass:
        return self.classify(type(exc).__name__, str(exc))

    def classify(self, error_type: str, message: str) -> ErrorClass:
        if error_type in _TYPE_MAP:
            return _TYPE_MAP[error_type]
        lowered = message.lower()
        for fragment, klass in _MESSAGE_HINTS:
            if fragment in lowered:
                return klass
        return ErrorClass.LOGIC


@dataclass(slots=True)
class RetryPolicy:
    """Retry con backoff esponenziale per errori recuperabili."""

    max_retries: int = 3
    base_backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    retryable: frozenset[ErrorClass] = frozenset(
        {ErrorClass.TRANSIENT, ErrorClass.EXTERNAL}
    )

    def backoff(self, attempt: int) -> float:
        """Attesa prima del tentativo ``attempt`` (1-based)."""
        return self.base_backoff_seconds * (self.backoff_multiplier ** (attempt - 1))

    async def run(
        self,
        fn: Callable[[], Awaitable[Any]],
        classifier: ErrorClassifier,
        on_retry: Callable[[int, BaseException], Awaitable[None]] | None = None,
    ) -> Any:
        """Esegue ``fn`` con retry; rilancia l'ultima eccezione se esaurito."""
        attempt = 0
        while True:
            try:
                return await fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - il punto è gestirli
                attempt += 1
                klass = classifier.classify_exception(exc)
                if klass not in self.retryable or attempt > self.max_retries:
                    raise
                if on_retry is not None:
                    await on_retry(attempt, exc)
                await asyncio.sleep(self.backoff(attempt))


@dataclass(slots=True)
class RollbackManager:
    """Registro di azioni di undo per contesto (piano, task, transazione)."""

    _undo_stacks: dict[str, list[Callable[[], Awaitable[None]]]] = field(
        default_factory=dict
    )

    def register(self, context_id: str, undo: Callable[[], Awaitable[None]]) -> None:
        """Registra un'azione di rollback per il contesto dato."""
        self._undo_stacks.setdefault(context_id, []).append(undo)

    def discard(self, context_id: str) -> None:
        """Scarta gli undo (il contesto si è concluso con successo)."""
        self._undo_stacks.pop(context_id, None)

    async def rollback(self, context_id: str) -> int:
        """Esegue gli undo in ordine inverso; ritorna quanti sono riusciti."""
        stack = self._undo_stacks.pop(context_id, [])
        succeeded = 0
        for undo in reversed(stack):
            try:
                await undo()
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 - il rollback non deve fermarsi
                _log.error("Undo fallito per %s: %s", context_id, exc)
        return succeeded


class RecoverySupervisor:
    """Ascolta gli errori sul bus e coordina la risposta del sistema.

    Sottoscrive ``execution.step.failed`` e ``bus.handler.error``; per ogni
    errore pubblica ``healing.detected`` con la classe assegnata e la
    strategia raccomandata. Le strategie attive (retry di step, rollback di
    piano) sono esposte come metodi per Broker e agenti.
    """

    def __init__(
        self,
        bus: EventBus,
        classifier: ErrorClassifier | None = None,
        retry_policy: RetryPolicy | None = None,
        rollback: RollbackManager | None = None,
    ) -> None:
        self._bus = bus
        self.classifier = classifier or ErrorClassifier()
        self.retry_policy = retry_policy or RetryPolicy()
        self.rollback = rollback or RollbackManager()
        self._detected: int = 0
        bus.subscribe("execution.step.failed", self._on_error_event)
        bus.subscribe("bus.handler.error", self._on_error_event)

    async def _on_error_event(self, event: Event) -> None:
        message = str(event.payload.get("error", ""))
        error_type = str(event.payload.get("error_type", ""))
        klass = self.classifier.classify(error_type, message)
        strategy = {
            ErrorClass.TRANSIENT: "retry",
            ErrorClass.EXTERNAL: "retry_or_failover",
            ErrorClass.RESOURCE: "degrade",
            ErrorClass.LOGIC: "report",
            ErrorClass.FATAL: "isolate",
        }[klass]
        self._detected += 1
        await self._bus.publish(event.child(
            "healing.detected",
            {"error_class": klass.value, "strategy": strategy,
             "origin_topic": event.topic, "error": message},
            source="healing.supervisor",
        ))

    def snapshot(self) -> dict[str, Any]:
        return {"errors_detected": self._detected,
                "max_retries": self.retry_policy.max_retries}
