"""Contratto degli osservatori.

Un osservatore è un sensore: campiona una sorgente (PC, filesystem, servizio
esterno) a intervalli regolari e pubblica eventi sul bus. Non decide nulla:
le reazioni appartengono ad agenti e self-healing.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from jarvis.events import Event, EventBus
from jarvis.logging import get_logger


class Observer(ABC):
    """Base per osservatori periodici asincroni.

    Args:
        bus: event bus su cui pubblicare.
        interval_seconds: periodo di campionamento.
    """

    name: str = "observer"

    def __init__(self, bus: EventBus, interval_seconds: float) -> None:
        self._bus = bus
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._log = get_logger(f"observation.{self.name}")

    @abstractmethod
    async def observe(self) -> list[Event]:
        """Campiona la sorgente e ritorna gli eventi da pubblicare."""

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name=f"observer-{self.name}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _loop(self) -> None:
        while True:
            try:
                for event in await self.observe():
                    await self._bus.publish(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - un sensore non deve morire
                self._log.error("Osservazione fallita: %s", exc)
            await asyncio.sleep(self._interval)
