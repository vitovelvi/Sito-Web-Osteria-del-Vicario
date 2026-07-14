"""Logging strutturato per tutto il sistema.

Ogni componente logga tramite ``get_logger(__name__)``; l'output è:
    - console: formato umano o JSON (configurabile);
    - file: JSON Lines con rotazione;
    - :class:`LogBuffer`: ring-buffer in memoria consumato dalla dashboard.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.config import Config

_LOGGER_ROOT = "jarvis"


class StructuredFormatter(logging.Formatter):
    """Formatter che emette una riga JSON per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "data", None)
        if isinstance(extra, dict):
            payload["data"] = extra
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Formato console compatto e leggibile."""

    def __init__(self) -> None:
        super().__init__(fmt="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
                         datefmt="%H:%M:%S")


class LogBuffer(logging.Handler):
    """Handler che conserva gli ultimi N record per la dashboard."""

    def __init__(self, capacity: int = 300) -> None:
        super().__init__()
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock_buf = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        with self._lock_buf:
            self._records.append(entry)

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Ultimi ``limit`` record, dal più vecchio al più recente."""
        with self._lock_buf:
            items = list(self._records)
        return items[-limit:]


def setup_logging(config: Config) -> LogBuffer:
    """Configura il logging di sistema a partire dalla configurazione.

    Returns:
        Il :class:`LogBuffer` condiviso, da iniettare nella dashboard.
    """
    section = config.section("logging")
    root = logging.getLogger(_LOGGER_ROOT)
    root.setLevel(getattr(logging, str(section.get("level", "INFO")).upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    if section.get("console", True):
        console = logging.StreamHandler()
        if section.get("console_format", "human") == "json":
            console.setFormatter(StructuredFormatter())
        else:
            console.setFormatter(HumanFormatter())
        root.addHandler(console)

    file_path = section.get("file")
    if file_path:
        target = config.resolve_path("logging.file", str(file_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            target,
            maxBytes=int(section.get("max_bytes", 5 * 1024 * 1024)),
            backupCount=int(section.get("backup_count", 3)),
            encoding="utf-8",
        )
        file_handler.setFormatter(StructuredFormatter())
        root.addHandler(file_handler)

    buffer = LogBuffer()
    root.addHandler(buffer)
    return buffer


def get_logger(name: str) -> logging.Logger:
    """Logger di componente sotto la gerarchia ``jarvis.*``."""
    if name.startswith(_LOGGER_ROOT):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_ROOT}.{name}")
