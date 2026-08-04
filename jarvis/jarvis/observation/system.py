"""Osservazione del PC: CPU, RAM, processi, carico.

Strategia di raccolta, in ordine di preferenza:
    1. ``psutil`` se installato — metriche complete su ogni piattaforma;
    2. fallback nativo per piattaforma — ``/proc`` su Linux, API di sistema
       (``kernel32``) su Windows;
    3. valori a zero con flag ``degraded`` — mai un'eccezione.

L'osservazione non deve MAI far cadere il sistema: ogni sonda è isolata e
degrada a un valore neutro se la piattaforma non la supporta.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

from jarvis.events import Event, EventBus
from jarvis.observation.base import Observer

try:  # psutil è opzionale
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dipende dall'ambiente
    psutil = None

_IS_WINDOWS = sys.platform == "win32"
_EMPTY_MEMORY: dict[str, float] = {"total_mb": 0.0, "available_mb": 0.0, "percent": 0.0}

# Campione precedente dei tempi CPU di Windows: la percentuale è un delta fra
# due letture, quindi va conservata tra un campionamento e l'altro.
_cpu_sample_lock = threading.Lock()
_previous_cpu_sample: tuple[int, int] | None = None


def _load_average() -> float:
    """Load average a 1 minuto.

    Ritorna 0.0 dove il concetto non esiste (Windows) o non è leggibile:
    ``os.getloadavg`` è assente su Windows, quindi va verificato con
    ``hasattr`` prima di chiamarlo.
    """
    if not hasattr(os, "getloadavg"):
        return 0.0
    try:
        return os.getloadavg()[0]
    except (OSError, ValueError):  # pragma: no cover - dipende dal kernel
        return 0.0


# ------------------------------------------------------------------- Linux


def _memory_linux() -> dict[str, float]:
    """RAM da ``/proc/meminfo``."""
    info: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split(" ")[0]
            if value.isdigit():
                info[key] = int(value)  # valori in kB
    except OSError:
        return dict(_EMPTY_MEMORY)
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    if not total:
        return dict(_EMPTY_MEMORY)
    return {
        "total_mb": round(total / 1024, 1),
        "available_mb": round(available / 1024, 1),
        "percent": round((1 - available / total) * 100, 1),
    }


def _process_count_linux() -> int | None:
    proc = Path("/proc")
    if not proc.exists():
        return None
    try:
        return sum(1 for entry in proc.iterdir() if entry.name.isdigit())
    except OSError:  # pragma: no cover - dipende dai permessi
        return None


# ----------------------------------------------------------------- Windows


def _memory_windows() -> dict[str, float]:
    """RAM tramite ``GlobalMemoryStatusEx`` (kernel32).

    Non testabile su questa piattaforma: qualunque errore degrada a zeri.
    """
    import ctypes  # import locale: su Linux non serve caricarlo

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return dict(_EMPTY_MEMORY)
    mib = 1024 * 1024
    return {
        "total_mb": round(status.ullTotalPhys / mib, 1),
        "available_mb": round(status.ullAvailPhys / mib, 1),
        "percent": float(status.dwMemoryLoad),
    }


def _cpu_percent_windows() -> float:
    """Percentuale CPU come delta fra due letture di ``GetSystemTimes``.

    Il primo campionamento non ha un riferimento precedente e ritorna 0.0;
    dal secondo in poi il valore è reale.
    """
    global _previous_cpu_sample
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def as_int(value: FileTime) -> int:
        return (value.high << 32) | value.low

    idle, kernel, user = FileTime(), FileTime(), FileTime()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        return 0.0

    # Su Windows il tempo "kernel" include già il tempo di idle.
    idle_time = as_int(idle)
    total_time = as_int(kernel) + as_int(user)

    with _cpu_sample_lock:
        previous = _previous_cpu_sample
        _previous_cpu_sample = (idle_time, total_time)

    if previous is None:
        return 0.0
    idle_delta = idle_time - previous[0]
    total_delta = total_time - previous[1]
    if total_delta <= 0:
        return 0.0
    busy = (total_delta - idle_delta) / total_delta * 100
    return round(min(max(busy, 0.0), 100.0), 1)


# ------------------------------------------------------------- dispatcher


def _memory_fallback() -> dict[str, float]:
    """RAM senza psutil, secondo la piattaforma."""
    try:
        if _IS_WINDOWS:
            return _memory_windows()
        return _memory_linux()
    except Exception:  # noqa: BLE001 - una sonda non deve mai propagare
        return dict(_EMPTY_MEMORY)


def _cpu_fallback() -> dict[str, float]:
    """CPU senza psutil, secondo la piattaforma."""
    cores = os.cpu_count() or 1
    load1 = _load_average()
    try:
        if _IS_WINDOWS:
            percent = _cpu_percent_windows()
        else:
            # Su Unix la stima deriva dal load average normalizzato sui core.
            percent = round(min(load1 / cores * 100, 100.0), 1)
    except Exception:  # noqa: BLE001 - una sonda non deve mai propagare
        percent = 0.0
    return {
        "percent": percent,
        "cores": float(cores),
        "load_1m": round(load1, 2),
    }


def _process_count_fallback() -> int | None:
    """Numero di processi senza psutil; ``None`` se non determinabile."""
    if _IS_WINDOWS:
        return None  # richiederebbe l'enumerazione via psapi: meglio psutil
    return _process_count_linux()


def collect_system_metrics(top_processes: int = 5) -> dict[str, Any]:
    """Snapshot delle metriche di sistema (funzione pura, riusabile).

    Args:
        top_processes: quanti processi più esosi includere (solo con psutil).

    Returns:
        Dizionario con ``cpu``, ``memory``, ``processes``, ``process_count``
        e ``degraded`` (vero quando psutil non è disponibile e le metriche
        provengono dai fallback nativi).
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
                "load_1m": round(_load_average(), 2),
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
        "memory": _memory_fallback(),
        "processes": [],
        "process_count": _process_count_fallback(),
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
