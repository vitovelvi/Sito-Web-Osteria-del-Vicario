"""Event Bus asincrono con topic gerarchici e wildcard.

Pattern di sottoscrizione:
    - esatto:      ``system.metrics``
    - prefisso:    ``system.*``  (qualunque profondità sotto ``system``)
    - universale:  ``*``

Il bus disaccoppia produttori e consumatori: ``publish`` accoda l'evento e un
dispatcher unico lo consegna a tutti gli handler compatibili. Gli errori di un
handler non interrompono la consegna agli altri e vengono ripubblicati come
eventi ``bus.handler.error`` (consumati dal sistema di Self-Healing).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from jarvis.events.event import Event
from jarvis.logging import get_logger

Handler = Callable[[Event], None] | Callable[[Event], Awaitable[None]]

_log = get_logger("events.bus")


@dataclass(frozen=True, slots=True)
class Subscription:
    """Handle di sottoscrizione, usato per l'annullamento."""

    subscription_id: str
    pattern: str


def topic_matches(pattern: str, topic: str) -> bool:
    """Verifica se ``topic`` è coperto dal ``pattern``."""
    if pattern == "*" or pattern == topic:
        return True
    if pattern.endswith(".*"):
        return topic.startswith(pattern[:-1])  # mantiene il punto finale
    return False


class EventBus:
    """Bus di eventi asincrono, unico canale di comunicazione del sistema.

    Args:
        history_size: dimensione del ring-buffer degli ultimi eventi
            (consumato da dashboard e diagnostica).
        queue_size: capacità della coda interna.
    """

    def __init__(self, history_size: int = 500, queue_size: int = 4096) -> None:
        self._subscribers: dict[str, tuple[str, Handler]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._dispatch_task: asyncio.Task[None] | None = None
        self._published_count = 0

    # ------------------------------------------------------------------ API

    def subscribe(self, pattern: str, handler: Handler) -> Subscription:
        """Registra ``handler`` per tutti i topic coperti da ``pattern``."""
        sub_id = uuid.uuid4().hex
        self._subscribers[sub_id] = (pattern, handler)
        return Subscription(subscription_id=sub_id, pattern=pattern)

    def unsubscribe(self, subscription: Subscription) -> None:
        """Annulla una sottoscrizione (idempotente)."""
        self._subscribers.pop(subscription.subscription_id, None)

    async def publish(self, event: Event) -> None:
        """Accoda un evento per la consegna asincrona."""
        self._published_count += 1
        self._history.append(event.to_dict())
        await self._queue.put(event)

    def publish_threadsafe(self, event: Event, loop: asyncio.AbstractEventLoop) -> None:
        """Pubblica da un thread esterno al loop (osservatori, dashboard)."""
        asyncio.run_coroutine_threadsafe(self.publish(event), loop)

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Avvia il dispatcher."""
        if self._dispatch_task is None:
            self._dispatch_task = asyncio.create_task(
                self._dispatch_loop(), name="eventbus-dispatch"
            )

    async def stop(self) -> None:
        """Consegna gli eventi residui e ferma il dispatcher."""
        if self._dispatch_task is None:
            return
        await self._queue.join()
        self._dispatch_task.cancel()
        try:
            await self._dispatch_task
        except asyncio.CancelledError:
            pass
        self._dispatch_task = None

    async def drain(self) -> None:
        """Attende che la coda sia completamente consegnata (utile nei test)."""
        await self._queue.join()

    # ---------------------------------------------------------- internals

    async def _dispatch_loop(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                await self._deliver(event)
            finally:
                self._queue.task_done()

    async def _deliver(self, event: Event) -> None:
        for pattern, handler in list(self._subscribers.values()):
            if not topic_matches(pattern, event.topic):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001 - isolamento degli handler
                _log.error(
                    "Handler fallito su %s: %s", event.topic, exc,
                    extra={"data": {"topic": event.topic, "error": str(exc)}},
                )
                if event.topic != "bus.handler.error":
                    await self.publish(
                        event.child(
                            "bus.handler.error",
                            {
                                "failed_topic": event.topic,
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                            },
                            source="events.bus",
                        )
                    )

    # ------------------------------------------------------------- stato

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Ultimi eventi pubblicati (dal più vecchio al più recente)."""
        return list(self._history)[-limit:]

    def stats(self) -> dict[str, Any]:
        """Statistiche del bus per dashboard e diagnostica."""
        return {
            "published": self._published_count,
            "subscribers": len(self._subscribers),
            "queued": self._queue.qsize(),
        }
