"""AgentOrchestrator: registro e ciclo di vita degli agenti.

L'orchestratore non instrada messaggi (lo fa il bus): governa il ciclo di
vita, garantisce nomi univoci ed espone lo stato aggregato. Gli agenti
restano indipendenti: la rimozione di uno non tocca gli altri.
"""

from __future__ import annotations

from typing import Any

from jarvis.agents.base import BaseAgent
from jarvis.logging import get_logger

_log = get_logger("agents.orchestrator")


class AgentOrchestrator:
    """Coordinatore centrale del ciclo di vita degli agenti."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}
        self._started = False

    def register(self, agent: BaseAgent) -> None:
        """Registra un agente (nome univoco)."""
        if agent.name in self._agents:
            raise ValueError(f"Agente già registrato: {agent.name!r}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent | None:
        return self._agents.get(name)

    async def start_all(self) -> None:
        """Attiva tutti gli agenti registrati."""
        for agent in self._agents.values():
            await agent.start()
        self._started = True
        _log.info("Agenti attivi: %s", ", ".join(self._agents))

    async def stop_all(self) -> None:
        for agent in self._agents.values():
            await agent.stop()
        self._started = False

    def snapshot(self) -> list[dict[str, Any]]:
        """Stato di tutti gli agenti, per la dashboard."""
        return [agent.snapshot() for agent in self._agents.values()]
