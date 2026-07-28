"""Gerarchia delle eccezioni, condizione d'errore e reti di sicurezza globali.

Principio guida del progetto: **la GUI non deve mai crashare**. Un sottosistema
puo' fallire, e in quel caso lo si mostra; ma il processo resta vivo.

Qui vivono tre cose distinte:

* la gerarchia :class:`JarvisError`, per distinguere gli errori attesi;
* :class:`ErrorCondition`, che modella un errore *come stato visibile* — non
  come eccezione — ed e' cio' che l'HUD mostra (docs §2.3);
* le reti di sicurezza (:func:`safe_slot`, :func:`install_excepthooks`), perche'
  in PySide6 un'eccezione sollevata dentro uno slot puo' terminare il processo
  senza traccia utile.
"""

from __future__ import annotations

import functools
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, ParamSpec, TypeVar

from jarvis_protocol.errors import ProtocolError, TransportError

__all__ = [
    "AudioError",
    "ConfigError",
    "ErrorCondition",
    "ErrorSeverity",
    "JarvisError",
    "PluginError",
    "ProtocolError",
    "ServiceError",
    "TransportError",
    "VisionError",
    "install_excepthooks",
    "safe_slot",
]

_log = logging.getLogger("jarvis.errors")

P = ParamSpec("P")
R = TypeVar("R")


# --------------------------------------------------------------------------- #
# Gerarchia delle eccezioni
# --------------------------------------------------------------------------- #


class JarvisError(Exception):
    """Radice di tutte le eccezioni applicative.

    Un ``except JarvisError`` distingue i guasti previsti (backend irraggiungibile,
    config invalida) dai bug veri, che devono restare visibili.
    """


#: Riesportate dal contratto: il resto dell'applicazione continua a scrivere
#: ``from core.errors import ProtocolError`` senza conoscere il pacchetto JCP.
#: Non derivano da :class:`JarvisError` perche' appartengono al protocollo, che
#: non conosce la gerarchia di eccezioni dell'applicazione.
ProtocolError = ProtocolError
TransportError = TransportError


class ConfigError(JarvisError):
    """Configurazione assente, malformata o non valida."""


class ServiceError(JarvisError):
    """Un servizio non e' riuscito ad avviarsi o si e' interrotto."""


class PluginError(JarvisError):
    """Un plugin ha fallito il caricamento o l'attivazione."""


class AudioError(ServiceError):
    """Guasto del sottosistema audio (dispositivo assente, formato non supportato)."""


class VisionError(ServiceError):
    """Guasto del sottosistema di visione (webcam assente o occupata)."""


# --------------------------------------------------------------------------- #
# Errore come condizione osservabile
# --------------------------------------------------------------------------- #


class ErrorSeverity(IntEnum):
    """Gravita' di una condizione d'errore.

    Ordinabile: la condizione piu' grave vince nella risoluzione visiva.
    """

    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40


@dataclass(frozen=True, slots=True)
class ErrorCondition:
    """Un errore nella forma in cui l'interfaccia lo mostra.

    Non e' un'eccezione: e' un fatto che persiste finche' non viene risolto o
    non scade. Modellare l'errore come *condizione sovrapposta* invece che come
    stato evita di perdere l'informazione su cosa stesse facendo l'assistente
    (docs §2.3).

    :param source: sottosistema di origine (``network``, ``audio``, ...).
    :param message: testo mostrabile all'utente, gia' localizzato.
    :param severity: gravita'; da ``ERROR`` in su il nucleo diventa rosso.
    :param detail: dettaglio tecnico per il pannello di log, non per l'utente.
    :param expires_at: istante oltre il quale la condizione si autorimuove.
        ``None`` significa che va risolta esplicitamente.
    """

    source: str
    message: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    detail: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float | None = None

    def is_expired(self, now: float | None = None) -> bool:
        """Indica se la condizione ha superato la propria scadenza."""
        if self.expires_at is None:
            return False
        return (now if now is not None else time.monotonic()) >= self.expires_at

    @classmethod
    def from_exception(
        cls,
        source: str,
        exc: BaseException,
        *,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        message: str | None = None,
        ttl: float | None = None,
    ) -> ErrorCondition:
        """Costruisce una condizione a partire da un'eccezione catturata."""
        return cls(
            source=source,
            message=message or f"{type(exc).__name__}: {exc}",
            severity=severity,
            detail="".join(traceback.format_exception(exc)),
            expires_at=None if ttl is None else time.monotonic() + ttl,
        )


# --------------------------------------------------------------------------- #
# Reti di sicurezza
# --------------------------------------------------------------------------- #

#: Callback invocata da ogni rete di sicurezza. Impostata da
#: :func:`install_excepthooks`; di norma pubblica un evento ``ERROR`` sul bus.
_error_sink: Callable[[ErrorCondition], None] | None = None


def _report(condition: ErrorCondition) -> None:
    """Inoltra la condizione al sink, senza mai propagare a sua volta."""
    _log.error("[%s] %s", condition.source, condition.message)
    if condition.detail:
        _log.debug("Dettaglio:\n%s", condition.detail)
    if _error_sink is None:
        return
    try:
        _error_sink(condition)
    except Exception:
        _log.exception("Il sink degli errori ha a sua volta fallito")


def safe_slot(
    source: str = "ui",
    *,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    default: Any = None,
) -> Callable[[Callable[P, R]], Callable[P, R | Any]]:
    """Decoratore per slot Qt e callback: cattura qualunque eccezione.

    Qt invoca gli slot dal proprio ciclo di eventi C++, che non ha un
    ``try/except`` Python attorno: un'eccezione non gestita puo' abortire il
    processo. Ogni slot connesso a un segnale va quindi decorato.

    Uso::

        @safe_slot("ui.reactor")
        def _on_state_changed(self, event: Event[Any]) -> None:
            ...

    :param source: etichetta del sottosistema, per il log e per l'HUD.
    :param severity: gravita' attribuita alla condizione generata.
    :param default: valore restituito quando la chiamata fallisce.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R | Any]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                _report(
                    ErrorCondition.from_exception(
                        f"{source}.{func.__name__}", exc, severity=severity, ttl=8.0
                    )
                )
                return default

        return wrapper

    return decorator


def install_excepthooks(sink: Callable[[ErrorCondition], None] | None = None) -> None:
    """Installa i gestori globali delle eccezioni non catturate.

    Copre i tre canali da cui un'eccezione puo' sfuggire:

    1. il thread principale (``sys.excepthook``);
    2. i thread secondari (``threading.excepthook``, da Python 3.8);
    3. i messaggi interni di Qt (``qInstallMessageHandler``), che altrimenti
       finiscono su stderr e vengono persi.

    :param sink: callback che riceve ogni condizione prodotta. Tipicamente
        pubblica un evento ``ERROR`` sul bus.
    """
    global _error_sink
    _error_sink = sink

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        # KeyboardInterrupt deve restare interrompente: non lo si assorbe.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _report(
            ErrorCondition.from_exception(
                "uncaught", exc, severity=ErrorSeverity.CRITICAL
            )
        )

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        _report(
            ErrorCondition.from_exception(
                f"thread.{args.thread.name if args.thread else '?'}",
                args.exc_value,
                severity=ErrorSeverity.CRITICAL,
            )
        )

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    _install_qt_message_handler()


def _install_qt_message_handler() -> None:
    """Reindirizza i messaggi interni di Qt nel logging applicativo."""
    try:
        from core.qtcompat import QtCore
    except ImportError:  # pragma: no cover - utile nei test senza Qt
        return

    qt_log = logging.getLogger("jarvis.qt")
    levels = {
        QtCore.QtMsgType.QtDebugMsg: logging.DEBUG,
        QtCore.QtMsgType.QtInfoMsg: logging.INFO,
        QtCore.QtMsgType.QtWarningMsg: logging.WARNING,
        QtCore.QtMsgType.QtCriticalMsg: logging.ERROR,
        QtCore.QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode: Any, context: Any, message: str) -> None:
        qt_log.log(levels.get(mode, logging.INFO), "%s", message)

    QtCore.qInstallMessageHandler(handler)
