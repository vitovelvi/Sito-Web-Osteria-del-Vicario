"""Kernel: composition root di JARVIS.

Il Kernel è l'unico punto in cui i sottosistemi vengono costruiti e collegati
(dependency injection): tutto il resto del sistema riceve le proprie
dipendenze dal costruttore e comunica via Event Bus.

Ordine di boot:
    config → logging → bus → identità → memoria → security → LLM router →
    reasoning → planner → execution chain → task manager → self-healing →
    agenti → osservatori → voce → dashboard
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from jarvis.agents import AgentOrchestrator
from jarvis.agents.coding_agent import CodingAgent
from jarvis.agents.executive_agent import ExecutiveAgent
from jarvis.agents.memory_agent import MemoryAgent
from jarvis.agents.planner_agent import PlannerAgent
from jarvis.agents.research_agent import ResearchAgent
from jarvis.agents.security_agent import SecurityAgent
from jarvis.agents.voice_agent import VoiceAgent
from jarvis.agents.web_agent import WebAgent
from jarvis.config import Config
from jarvis.core.identity import CoreIdentity
from jarvis.dashboard import DashboardServer
from jarvis.events import Event, EventBus
from jarvis.execution import (
    ActionContext,
    ExecutionBroker,
    Executor,
    Sandbox,
    Validator,
)
from jarvis.execution.actions import register_standard_actions
from jarvis.healing import RecoverySupervisor, RetryPolicy
from jarvis.llm import LLMRouter
from jarvis.logging import LogBuffer, get_logger, setup_logging
from jarvis.memory import MemoryManager
from jarvis.observation import FilesystemObserver, SystemObserver
from jarvis.observation.base import Observer
from jarvis.observation.integrations import build_integration_observers
from jarvis.planning import Planner
from jarvis.reasoning import ReasoningEngine
from jarvis.security import ConfirmationGate, OperationClassifier
from jarvis.tasks import TaskManager
from jarvis.voice import VoicePipeline, build_voice_pipeline

_log = get_logger("kernel")


class Kernel:
    """Compone, avvia e ferma l'intero sistema."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.log_buffer: LogBuffer = setup_logging(config)
        self.identity = CoreIdentity.from_config(config)

        self.bus = EventBus(
            history_size=int(config.get("events.history_size", 500)),
            queue_size=int(config.get("events.queue_size", 4096)),
        )
        self.memory = MemoryManager(config, self.bus)

        # --- Execution chain (Planner → Broker → Validation → Sandbox → Executor)
        self.sandbox = Sandbox(config)
        self.executor = Executor(ActionContext(services={
            "memory": self.memory,
            "sandbox": self.sandbox,
            "identity": self.identity,
        }))
        register_standard_actions(self.executor)
        self.classifier = OperationClassifier(self.executor.base_levels())
        self.gate = ConfirmationGate(
            self.identity,
            self.bus,
            confirmation_from_level=int(
                config.get("security.confirmation_required_from_level", 2)),
            auto_deny_when_unattended=bool(
                config.get("security.auto_deny_when_unattended", True)),
        )
        self.broker = ExecutionBroker(
            self.bus, Validator(self.executor), self.classifier,
            self.gate, self.sandbox, self.executor,
        )

        # --- Cognizione
        self.llm_router = LLMRouter(config, self.bus)
        self.executor_context_late_bind()
        self.reasoning = ReasoningEngine(self.identity, self.llm_router)
        self.planner = Planner(self.bus)

        # --- Task e self-healing
        self.tasks = TaskManager(self.bus,
                                 max_history=int(config.get("tasks.max_history", 200)))
        self.healing = RecoverySupervisor(
            self.bus,
            retry_policy=RetryPolicy(
                max_retries=int(config.get("healing.max_retries", 3)),
                base_backoff_seconds=float(
                    config.get("healing.base_backoff_seconds", 0.5)),
                backoff_multiplier=float(
                    config.get("healing.backoff_multiplier", 2.0)),
            ),
        )

        # --- Agenti
        self.orchestrator = AgentOrchestrator()
        self.security_agent = SecurityAgent(self.bus)
        for agent in (
            ExecutiveAgent(self.bus, self.reasoning, self.planner,
                           self.broker, self.tasks, self.memory),
            PlannerAgent(self.bus, self.reasoning, self.planner),
            MemoryAgent(self.bus, self.memory),
            self.security_agent,
            VoiceAgent(self.bus),
            WebAgent(self.bus),
            ResearchAgent(self.bus, self.llm_router, self.memory),
            CodingAgent(self.bus, self.llm_router),
        ):
            self.orchestrator.register(agent)

        # --- Osservatori
        self.system_observer = SystemObserver(
            self.bus,
            interval_seconds=float(
                config.get("observation.system.interval_seconds", 5.0)),
        )
        self.observers: list[Observer] = []
        if bool(config.get("observation.system.enabled", True)):
            self.observers.append(self.system_observer)
        if bool(config.get("observation.filesystem.enabled", True)):
            watch = [config.resolve_path("_", p) for p in
                     config.get("observation.filesystem.watch_paths", [])]
            self.observers.append(FilesystemObserver(
                self.bus, watch,
                interval_seconds=float(
                    config.get("observation.filesystem.interval_seconds", 10.0)),
                ignore_patterns=tuple(
                    config.get("observation.filesystem.ignore_patterns", [])),
            ))
        self.observers.extend(
            o for o in build_integration_observers(self.bus, config) if o.enabled
        )

        # --- Voce e dashboard
        self.voice: VoicePipeline | None = (
            build_voice_pipeline(self.bus, config)
            if bool(config.get("voice.enabled", False)) else None
        )
        self.dashboard: DashboardServer | None = None
        if bool(config.get("dashboard.enabled", True)):
            self.dashboard = DashboardServer(
                host=str(config.get("dashboard.host", "127.0.0.1")),
                port=int(config.get("dashboard.port", 8765)),
                state_provider=self.state,
            )

        self._started_at: float | None = None

    def executor_context_late_bind(self) -> None:
        """Completa i servizi delle azioni che dipendono da componenti
        costruiti dopo l'Executor (il router LLM)."""
        self.executor._context.services["llm_router"] = self.llm_router  # noqa: SLF001

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Avvia bus, agenti, osservatori e dashboard."""
        await self.bus.start()
        await self.orchestrator.start_all()
        for observer in self.observers:
            await observer.start()
        if self.dashboard is not None:
            self.dashboard.start()  # accessorio: un fallimento non blocca il boot
        self._started_at = time.monotonic()
        await self.bus.publish(Event(
            topic="kernel.started",
            payload={"identity": self.identity.name},
            source="kernel",
        ))
        _log.info(
            "%s operativo. %s",
            self.identity.name,
            f"Dashboard: {self.dashboard.url}"
            if self.dashboard is not None and self.dashboard.running
            else "Dashboard non disponibile.",
        )

    async def stop(self) -> None:
        """Arresto ordinato: osservatori → agenti → bus → persistenza."""
        for observer in self.observers:
            await observer.stop()
        await self.orchestrator.stop_all()
        await self.bus.drain()
        await self.bus.stop()
        if self.dashboard is not None:
            self.dashboard.stop()
        self.memory.flush()
        _log.info("%s arrestato.", self.identity.name)

    # ------------------------------------------------------------------ API

    async def submit_request(self, text: str, channel: str = "cli") -> None:
        """Inoltra una richiesta utente al sistema (via evento)."""
        await self.bus.publish(Event(
            topic="request.received",
            payload={"text": text, "channel": channel},
            source=f"input.{channel}",
        ))

    async def submit_and_wait(self, text: str, timeout: float = 120.0) -> dict[str, Any]:
        """Inoltra una richiesta e attende la risposta corrispondente.

        Utility per CLI e demo: sottoscrive ``response.ready`` filtrando per
        correlazione con la richiesta inviata.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        request = Event(
            topic="request.received",
            payload={"text": text, "channel": "cli"},
            source="input.cli",
        )

        def on_response(event: Event) -> None:
            if event.correlation_id == request.event_id and not future.done():
                future.set_result(event.payload)

        subscription = self.bus.subscribe("response.ready", on_response)
        try:
            await self.bus.publish(request)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.bus.unsubscribe(subscription)

    def state(self) -> dict[str, Any]:
        """Stato aggregato del sistema (consumato dalla dashboard)."""
        uptime = int(time.monotonic() - self._started_at) if self._started_at else 0
        return {
            "identity": self.identity.describe(),
            "uptime_seconds": uptime,
            "system": self.system_observer.last_metrics or None,
            "memory": self.memory.snapshot(),
            "agents": self.orchestrator.snapshot(),
            "tasks": self.tasks.snapshot(),
            "events": self.bus.history(limit=50),
            "bus": self.bus.stats(),
            "notifications": self.security_agent.notifications(),
            "healing": self.healing.snapshot(),
            "logs": self.log_buffer.tail(limit=80),
            "observers": [
                {"name": o.name, "running": o.running} for o in self.observers
            ],
        }
