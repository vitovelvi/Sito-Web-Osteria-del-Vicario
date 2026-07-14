"""Contratto degli agenti.

Un agente è un componente autonomo che:
    - dichiara i topic a cui è interessato (``subscriptions``);
    - reagisce agli eventi implementando :meth:`handle`;
    - comunica con il resto del sistema SOLO pubblicando eventi.

Le dipendenze (memoria, router, planner...) sono iniettate dal Kernel nel
costruttore del singolo agente: nessun accesso a stato globale.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jarvis.events import Event, EventBus
from jarvis.logging import get_logger


class BaseAgent(ABC):
    """Base per tutti gli agenti."""

    name: str = "agent"
    description: str = ""
    subscriptions: tuple[str, ...] = ()

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._log = get_logger(f"agents.{self.name}")
        self._handled = 0
        self._errors = 0
        self._active = False

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Attiva l'agente: sottoscrive i propri topic."""
        for pattern in self.subscriptions:
            self._bus.subscribe(pattern, self._dispatch)
        self._active = True
        self._log.debug("Agente %s attivo su %s", self.name, self.subscriptions)

    async def stop(self) -> None:
        self._active = False

    async def _dispatch(self, event: Event) -> None:
        if not self._active:
            return
        try:
            await self.handle(event)
            self._handled += 1
        except Exception:
            self._errors += 1
            raise  # il bus isola e ripubblica come bus.handler.error

    # -------------------------------------------------------------- to impl

    @abstractmethod
    async def handle(self, event: Event) -> None:
        """Reagisce a un evento sottoscritto."""

    # --------------------------------------------------------------- utils

    async def emit(self, topic: str, payload: dict[str, Any],
                   correlation_id: str | None = None) -> None:
        """Pubblica un evento a nome dell'agente."""
        await self._bus.publish(Event(
            topic=topic, payload=payload,
            source=f"agents.{self.name}", correlation_id=correlation_id,
        ))

    def snapshot(self) -> dict[str, Any]:
        """Stato per dashboard e orchestratore."""
        return {
            "name": self.name,
            "description": self.description,
            "active": self._active,
            "handled": self._handled,
            "errors": self._errors,
            "subscriptions": list(self.subscriptions),
        }
