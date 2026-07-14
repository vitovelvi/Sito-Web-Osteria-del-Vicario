"""MemoryManager: composizione degli store e integrazione con l'Event Bus.

Il manager costruisce il backend scelto in configurazione, istanzia i cinque
store e — sottoscrivendosi al bus — registra automaticamente gli episodi
salienti del sistema.
"""

from __future__ import annotations

from typing import Any

from jarvis.config import Config
from jarvis.events import Event, EventBus
from jarvis.logging import get_logger
from jarvis.memory.backends import InMemoryBackend, JsonFileBackend, SQLiteBackend
from jarvis.memory.base import MemoryBackend
from jarvis.memory.stores import (
    EpisodicMemory,
    OperationalLog,
    PreferenceMemory,
    SemanticMemory,
    WorkingMemory,
)

_log = get_logger("memory.manager")

# Topic che meritano una traccia episodica automatica.
_EPISODIC_TOPICS = ("request.received", "plan.completed", "plan.failed",
                    "security.confirmation.denied")


def _build_backend(config: Config) -> MemoryBackend:
    kind = str(config.get("memory.backend", "json")).lower()
    data_dir = config.resolve_path("memory.data_dir", "runtime/memory")
    if kind == "memory":
        return InMemoryBackend()
    if kind == "sqlite":
        return SQLiteBackend(data_dir / "memory.db")
    if kind == "json":
        return JsonFileBackend(data_dir)
    raise ValueError(f"Backend di memoria sconosciuto: {kind!r}")


class MemoryManager:
    """Facciata del Memory System.

    Args:
        config: configurazione globale.
        bus: event bus per la registrazione automatica degli episodi.
    """

    def __init__(self, config: Config, bus: EventBus) -> None:
        self._bus = bus
        backend = _build_backend(config)
        mem = config.section("memory")
        self.working = WorkingMemory(
            backend,
            capacity=int(mem.get("working.capacity", 64)),
            ttl_seconds=float(mem.get("working.ttl_seconds", 900)),
        )
        self.episodic = EpisodicMemory(
            backend, max_records=int(mem.get("episodic.max_records", 5000))
        )
        self.semantic = SemanticMemory(
            backend, max_records=int(mem.get("semantic.max_records", 20000))
        )
        self.preference = PreferenceMemory(
            backend, max_records=int(mem.get("preference.max_records", 1000))
        )
        self.operational = OperationalLog(
            backend, max_records=int(mem.get("operational.max_records", 10000))
        )
        self._backend = backend
        for topic in _EPISODIC_TOPICS:
            bus.subscribe(topic, self._on_salient_event)
        bus.subscribe("execution.step.failed", self._on_operational_event)
        bus.subscribe("healing.*", self._on_operational_event)

    # ------------------------------------------------------------- handlers

    def _on_salient_event(self, event: Event) -> None:
        self.episodic.remember(
            {"topic": event.topic, "payload": event.payload, "source": event.source},
            tags=["auto", event.topic],
            importance=0.6,
        )

    def _on_operational_event(self, event: Event) -> None:
        self.operational.log(event.topic, {"payload": event.payload})

    # ------------------------------------------------------------------ API

    def flush(self) -> None:
        """Persiste tutte le memorie su disco."""
        self._backend.flush()

    def snapshot(self) -> dict[str, Any]:
        """Statistiche per la dashboard."""
        return {
            "working": self.working.count(),
            "episodic": self.episodic.count(),
            "semantic": self.semantic.count(),
            "preference": self.preference.count(),
            "operational": self.operational.count(),
        }

    def context_for(self, text: str, limit: int = 5) -> list[dict[str, Any]]:
        """Contesto rilevante per una richiesta: working + episodic + semantic."""
        results: list[dict[str, Any]] = []
        for store in (self.working, self.semantic, self.episodic):
            for record in store.recall(text=text, limit=limit):
                results.append({"store": store.store_name, **record.content})
        return results[: limit * 3]
