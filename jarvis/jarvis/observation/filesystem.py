"""Osservazione del filesystem: cartelle, file, eventi di modifica.

Strategia a snapshot-diff (polling): portabile e senza dipendenze. Per volumi
elevati si può sostituire con watchdog/inotify implementando la stessa
interfaccia :class:`Observer`.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.events import Event, EventBus
from jarvis.observation.base import Observer

Snapshot = dict[str, float]  # percorso -> mtime


class FilesystemObserver(Observer):
    """Emette ``file.created`` / ``file.modified`` / ``file.deleted``."""

    name = "filesystem"

    def __init__(
        self,
        bus: EventBus,
        watch_paths: list[Path],
        interval_seconds: float = 10.0,
        ignore_patterns: tuple[str, ...] = (".git", "__pycache__", "node_modules"),
    ) -> None:
        super().__init__(bus, interval_seconds)
        self._paths = watch_paths
        self._ignore = ignore_patterns
        self._snapshot: Snapshot | None = None
        for path in self._paths:
            path.mkdir(parents=True, exist_ok=True)

    def _scan(self) -> Snapshot:
        snapshot: Snapshot = {}
        for root in self._paths:
            if not root.exists():
                continue
            for item in root.rglob("*"):
                if any(part in self._ignore for part in item.parts):
                    continue
                if item.is_file():
                    try:
                        snapshot[str(item)] = item.stat().st_mtime
                    except OSError:
                        continue
        return snapshot

    async def observe(self) -> list[Event]:
        current = self._scan()
        if self._snapshot is None:
            # Primo giro: stabilisce la baseline senza inondare il bus.
            self._snapshot = current
            return []

        events: list[Event] = []
        previous = self._snapshot
        for path, mtime in current.items():
            if path not in previous:
                events.append(Event(topic="file.created",
                                    payload={"path": path}, source=self.name))
            elif mtime != previous[path]:
                events.append(Event(topic="file.modified",
                                    payload={"path": path}, source=self.name))
        for path in previous:
            if path not in current:
                events.append(Event(topic="file.deleted",
                                    payload={"path": path}, source=self.name))
        self._snapshot = current
        return events
