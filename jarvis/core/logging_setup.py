"""Configurazione del logging: categorie, rotazione, redazione dei segreti.

Il brief chiede categorie ``NETWORK``, ``VOICE``, ``VISION``, ``SYSTEM`` accanto
ai livelli ``INFO``/``WARNING``/``ERROR``. Sono due assi diversi e vanno tenuti
separati: il **livello** dice quanto e' grave, la **categoria** dice chi parla.
Le categorie sono quindi logger con nome gerarchico (``jarvis.network``), non
livelli custom — cosi' restano compatibili con l'intero ecosistema Python e si
possono filtrare singolarmente.

I log vivono nella directory dati dell'utente, **non** nel repository (docs
§2.6): la cartella d'installazione puo' essere in sola lettura e un
aggiornamento non deve cancellare la diagnostica.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

__all__ = [
    "LogCategory",
    "LogRecordSnapshot",
    "RingBufferHandler",
    "get_logger",
    "setup_logging",
]

_ROOT_NAME: Final[str] = "jarvis"
_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s %(name)-18s %(message)s"
_DATEFMT: Final[str] = "%Y-%m-%d %H:%M:%S"


class LogCategory(str, Enum):
    """Categorie previste. Il valore e' il suffisso del nome del logger."""

    APP = "app"
    NETWORK = "network"
    VOICE = "voice"
    VISION = "vision"
    SYSTEM = "system"
    UI = "ui"
    STATE = "state"
    PLUGIN = "plugin"
    PROTOCOL = "protocol"


def get_logger(category: LogCategory | str, sub: str | None = None) -> logging.Logger:
    """Restituisce il logger di una categoria.

    :param category: categoria principale.
    :param sub: sottonome opzionale (``get_logger(NETWORK, "heartbeat")`` →
        ``jarvis.network.heartbeat``).
    """
    name = category.value if isinstance(category, LogCategory) else str(category)
    full = f"{_ROOT_NAME}.{name}" + (f".{sub}" if sub else "")
    return logging.getLogger(full)


# --------------------------------------------------------------------------- #
# Redazione dei segreti
# --------------------------------------------------------------------------- #

#: Pattern di chiavi e token da oscurare. Un log condiviso per debug non deve
#: poter esfiltrare credenziali (docs §8).
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bxi-api-key\S*"),
)

_REDACTED: Final[str] = "«redatto»"


class RedactionFilter(logging.Filter):
    """Sostituisce i segreti riconosciuti nel messaggio formattato."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - un log rotto non blocca l'app
            return True

        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(_REDACTED, redacted)

        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


# --------------------------------------------------------------------------- #
# Buffer circolare per il pannello Log della GUI
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LogRecordSnapshot:
    """Copia immutabile e leggera di un record, sicura da passare fra thread."""

    timestamp: float
    level: int
    level_name: str
    category: str
    message: str


class RingBufferHandler(logging.Handler):
    """Conserva gli ultimi N record in memoria per il pannello Log.

    Il pannello legge da qui invece di seguire il file: e' immediato, non tocca
    il disco e sopravvive alla rotazione. Il buffer e' un ``deque`` limitato,
    quindi l'occupazione di memoria e' costante.
    """

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self._buffer: deque[LogRecordSnapshot] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            name = record.name.removeprefix(f"{_ROOT_NAME}.")
            self._buffer.append(
                LogRecordSnapshot(
                    timestamp=record.created,
                    level=record.levelno,
                    level_name=record.levelname,
                    category=name.split(".")[0] if name else "app",
                    message=record.getMessage(),
                )
            )
        except Exception:  # noqa: BLE001 - un handler non deve mai propagare
            self.handleError(record)

    def snapshot(self) -> tuple[LogRecordSnapshot, ...]:
        """Copia immutabile del contenuto corrente."""
        return tuple(self._buffer)


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #


def setup_logging(
    log_dir: Path,
    *,
    level: int | str = logging.INFO,
    console: bool = True,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    ring_capacity: int = 500,
    quiet_loggers: Iterable[str] = ("websockets", "asyncio", "PIL"),
) -> RingBufferHandler:
    """Configura il logging dell'applicazione.

    Idempotente: chiamarla due volte non duplica gli handler.

    :param log_dir: directory dei file di log; creata se assente.
    :param level: livello del logger radice ``jarvis``.
    :param console: se scrivere anche su stderr (utile in sviluppo).
    :param max_bytes: dimensione massima del file prima della rotazione.
    :param backup_count: numero di file storici da conservare.
    :param ring_capacity: record mantenuti in memoria per la GUI.
    :param quiet_loggers: logger di terze parti da alzare a ``WARNING``.
    :returns: l'handler circolare, da passare al pannello Log.
    """
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level)
    # I record non risalgono al root globale: evita doppie righe se
    # l'applicazione ospite ha gia' configurato il logging.
    root.propagate = False

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    redaction = RedactionFilter()

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "jarvis.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redaction)
        root.addHandler(file_handler)
    except OSError as exc:
        # Disco pieno o permessi negati non devono impedire l'avvio: si perde la
        # persistenza, non l'applicazione.
        print(f"[jarvis] log su file non disponibile: {exc}", file=sys.stderr)

    if console:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(redaction)
        root.addHandler(stream)

    ring = RingBufferHandler(capacity=ring_capacity)
    ring.addFilter(redaction)
    root.addHandler(ring)

    for name in quiet_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    return ring
