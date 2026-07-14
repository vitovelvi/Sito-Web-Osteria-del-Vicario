"""Osservazione del PC: CPU, RAM, processi, carico.

Usa ``psutil`` quando installato; altrimenti degrada a ``/proc`` (Linux) e
``os``: il sistema resta osservabile senza dipendenze.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jarvis.events import Event, EventBus
from jarvis.observation.base import Observer

try:  # psutil è opzionale
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dipende dall'ambiente
    psutil = None


def _meminfo_fallback() -> dict[str, float]:
    """Legge la RAM da /proc/meminfo (Linux)."""
    info: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split(" ")[0]
            if value.isdigit():
                info[key] = int(value)
    except OSError:
        return {"total_mb": 0.0, "available_mb": 0.0, "percent": 0.0}
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    percent = (1 - available / total) * 100 if total else 0.0
    return {
        "total_mb": round(total / 1024, 1),
        "available_mb": round(available / 1024, 1),
        "percent": round(percent, 1),
    }


def _cpu_fallback() -> dict[str, float]:
    """Stima la CPU dal load average normalizzato sui core."""
    cores = os.cpu_count() or 1
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        load1 = 0.0
    return {
        "percent": round(min(load1 / cores * 100, 100.0), 1),
        "cores": float(cores),
        "load_1m": round(load1, 2),
    }


def collect_system_metrics(top_processes: int = 5) -> dict[str, Any]:
    """Snapshot delle metriche di sistema (funzione pura, riusabile).

    Returns:
        Dizionario con ``cpu``, ``memory``, ``processes`` e ``degraded``
        (vero quando psutil non è disponibile).
    """
    if psutil is not None:
        virtual = psutil.virtual_memory()
        processes: list[dict[str, Any]] = []
        for proc in sorted(
            psutil.process_iter(["pid", "name", "memory_percent"]),
            key=lambda p: p.info.get("memory_percent") or 0.0,
            reverse=True,
        )[:top_processes]:
            processes.append({
                "pid": proc.info["pid"],
                "name": proc.info["name"],
                "memory_percent": round(proc.info.get("memory_percent") or 0.0, 2),
            })
        return {
            "cpu": {
                "percent": psutil.cpu_percent(interval=None),
                "cores": float(psutil.cpu_count() or 1),
                "load_1m": round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else 0.0,
            },
            "memory": {
                "total_mb": round(virtual.total / 1024 / 1024, 1),
                "available_mb": round(virtual.available / 1024 / 1024, 1),
                "percent": virtual.percent,
            },
            "processes": processes,
            "process_count": len(psutil.pids()),
            "degraded": False,
        }

    return {
        "cpu": _cpu_fallback(),
        "memory": _meminfo_fallback(),
        "processes": [],
        "process_count": len(list(Path("/proc").glob("[0-9]*"))) if Path("/proc").exists() else 0,
        "degraded": True,
    }


class SystemObserver(Observer):
    """Pubblica periodicamente ``system.metrics`` e allarmi di soglia."""

    name = "system"

    def __init__(
        self,
        bus: EventBus,
        interval_seconds: float = 5.0,
        cpu_alert_percent: float = 90.0,
        memory_alert_percent: float = 90.0,
    ) -> None:
        super().__init__(bus, interval_seconds)
        self._cpu_alert = cpu_alert_percent
        self._memory_alert = memory_alert_percent
        self.last_metrics: dict[str, Any] = {}

    async def observe(self) -> list[Event]:
        metrics = collect_system_metrics()
        self.last_metrics = metrics
        events = [Event(topic="system.metrics", payload=metrics, source=self.name)]
        if metrics["cpu"].get("percent", 0) >= self._cpu_alert:
            events.append(Event(
                topic="system.alert.cpu",
                payload={"percent": metrics["cpu"]["percent"]},
                source=self.name,
            ))
        if metrics["memory"].get("percent", 0) >= self._memory_alert:
            events.append(Event(
                topic="system.alert.memory",
                payload={"percent": metrics["memory"]["percent"]},
                source=self.name,
            ))
        return events
