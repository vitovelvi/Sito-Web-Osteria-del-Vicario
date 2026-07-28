"""Event bus interno: tipizzato, thread-safe, con storico e replay.

I moduli non si conoscono fra loro: pubblicano fatti e si sottoscrivono a fatti
altrui. E' la regola che rende sostituibile un sottosistema senza toccare gli
altri.

Tre problemi che un bus ingenuo non risolve, e che qui sono affrontati
esplicitamente:

**Affinita' di thread.** Se il thread di rete pubblica ``AI_RESPONSE`` e un
widget e' sottoscritto, un bus ingenuo esegue lo slot sul thread di rete: si
tocca la UI da un thread non-GUI e si ottengono crash sporadici, i piu' difficili
da diagnosticare. Qui :meth:`EventBus.publish` e' chiamabile da qualunque thread
e la consegna avviene **sempre sul thread proprietario del bus** (quello GUI),
grazie a un segnale Qt con connessione automatica.

**Perdite di memoria.** Un bus che tiene riferimenti forti ai metodi dei widget
ne impedisce la distruzione. I metodi legati sono quindi referenziati in modo
debole.

**Sottoscrittori tardivi.** Un plugin caricato dopo il boot si perderebbe lo
stato corrente. Lo storico circolare permette il *replay* dell'ultimo evento di
un tipo al momento della sottoscrizione.
"""

from __future__ import annotations

import itertools
import threading
import time
import weakref
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from types import MethodType
from typing import Any, Final, Generic, TypeVar

from core.events import PAYLOAD_TYPES, EventType
from core.logging_setup import LogCategory, get_logger
from core.qtcompat import QtCore, Signal

__all__ = ["Event", "EventBus", "EventKey", "Subscription"]

_log = get_logger(LogCategory.APP, "eventbus")

PayloadT = TypeVar("PayloadT")

#: Una sottoscrizione puo' riferirsi a un evento core (:class:`EventType`) o a
#: un evento di plugin, identificato da una stringa con prefisso ``plugin.``.
EventKey = EventType | str

_PLUGIN_PREFIX: Final[str] = "plugin."
_WILDCARD: Final[str] = "*"

_seq_counter = itertools.count(1)


@dataclass(frozen=True)
class Event(Generic[PayloadT]):
    """Un fatto avvenuto nel sistema.

    :param type: identificatore dell'evento.
    :param payload: dati, immutabili, della forma dichiarata in
        :data:`~core.events.PAYLOAD_TYPES`.
    :param source: chi lo ha pubblicato; compare nel log ed e' utile per
        distinguere l'origine quando piu' moduli emettono lo stesso tipo.
    :param ts: istante di pubblicazione (epoch, per la visualizzazione).
    :param seq: numero progressivo globale, utile per ordinare e per capire se
        un consumatore ha saltato eventi.
    """

    type: EventKey
    payload: PayloadT
    source: str = "core"
    ts: float = field(default_factory=time.time)
    seq: int = field(default_factory=lambda: next(_seq_counter))

    @property
    def key(self) -> str:
        """Chiave interna di indicizzazione."""
        return self.type.value if isinstance(self.type, EventType) else str(self.type)


Handler = Callable[[Event[Any]], None]


class Subscription:
    """Token restituito da :meth:`EventBus.subscribe`.

    Va conservato dal chiamante: quando viene rilasciato o si invoca
    :meth:`unsubscribe`, la sottoscrizione cessa. Utilizzabile anche come
    context manager per sottoscrizioni temporanee.
    """

    __slots__ = ("__weakref__", "_active", "_bus", "_key", "_token")

    def __init__(self, bus: EventBus, key: str, token: int) -> None:
        self._bus = weakref.ref(bus)
        self._key = key
        self._token = token
        self._active = True

    @property
    def active(self) -> bool:
        """Indica se la sottoscrizione e' ancora attiva."""
        return self._active

    def unsubscribe(self) -> None:
        """Disattiva la sottoscrizione. Idempotente."""
        if not self._active:
            return
        self._active = False
        bus = self._bus()
        if bus is not None:
            bus._remove(self._key, self._token)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *_: object) -> None:
        self.unsubscribe()


class _HandlerRef:
    """Riferimento a un handler, debole per i metodi legati.

    I metodi legati di un widget sono referenziati con :class:`weakref.WeakMethod`
    cosi' la distruzione del widget rimuove automaticamente la sottoscrizione.
    Le funzioni libere e le lambda sono tenute con riferimento forte: una lambda
    referenziata debolmente verrebbe raccolta immediatamente dopo la
    registrazione, cioe' non funzionerebbe mai.
    """

    __slots__ = ("_ref", "_strong", "once", "token")

    def __init__(self, handler: Handler, token: int, *, once: bool = False) -> None:
        self.token = token
        self.once = once
        if isinstance(handler, MethodType):
            self._ref: weakref.ref[Any] | None = weakref.WeakMethod(handler)
            self._strong: Handler | None = None
        else:
            self._ref = None
            self._strong = handler

    def resolve(self) -> Handler | None:
        """Restituisce l'handler, o ``None`` se il proprietario e' stato distrutto."""
        if self._strong is not None:
            return self._strong
        assert self._ref is not None
        return self._ref()  # type: ignore[return-value]


class EventBus(QtCore.QObject):
    """Bus pubblicazione/sottoscrizione dell'applicazione.

    Il bus vive nel thread GUI. ``publish`` e' sicuro da qualsiasi thread; la
    consegna avviene nel thread del bus.
    """

    #: Segnale interno usato per attraversare il confine fra thread. Con
    #: ``AutoConnection`` Qt sceglie da solo: chiamata diretta se l'emittente e'
    #: gia' nel thread del bus, accodamento altrimenti. E' esattamente la
    #: semantica voluta — sincrono quando puo' esserlo, sicuro quando serve.
    _relay = Signal(object)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        history: int = 512,
        strict: bool = False,
    ) -> None:
        """
        :param history: numero di eventi conservati per il pannello Log e per il
            replay ai sottoscrittori tardivi.
        :param strict: se attivo, un payload non conforme solleva ``TypeError``.
            Da tenere acceso in sviluppo e nei test, spento in produzione — dove
            un evento malformato va scartato, non fatto esplodere.
        """
        super().__init__(parent)
        self._handlers: dict[str, list[_HandlerRef]] = {}
        self._last: dict[str, Event[Any]] = {}
        self._history: deque[Event[Any]] = deque(maxlen=history)
        self._lock = threading.RLock()
        self._tokens = itertools.count(1)
        self._strict = strict
        self._dead_letters: Counter[str] = Counter()
        self._published = 0
        self._delivered = 0
        self._handler_errors = 0
        # Guardia contro la ricorsione: un handler di ERROR che a sua volta
        # fallisce genererebbe un altro ERROR, all'infinito.
        self._in_error_dispatch = False
        self._relay.connect(self._dispatch)

    # ------------------------------------------------------------------ #
    # Pubblicazione
    # ------------------------------------------------------------------ #

    def publish(
        self,
        event_type: EventKey,
        payload: Any = None,
        *,
        source: str = "core",
    ) -> None:
        """Pubblica un evento. Chiamabile da qualunque thread.

        :param event_type: tipo dell'evento.
        :param payload: dati; deve corrispondere al tipo dichiarato in
            :data:`~core.events.PAYLOAD_TYPES` quando l'evento e' un
            :class:`EventType` noto.
        :param source: identificativo di chi pubblica.
        :raises TypeError: solo in modalita' ``strict``, per payload non conforme.
        """
        event: Event[Any] = Event(type=event_type, payload=payload, source=source)
        self.publish_event(event)

    def publish_event(self, event: Event[Any]) -> None:
        """Variante di :meth:`publish` per un :class:`Event` gia' costruito."""
        if not self._validate(event):
            return

        with self._lock:
            self._published += 1
            self._last[event.key] = event
            self._history.append(event)

        # Da qui in poi la consegna e' responsabilita' di Qt: se siamo nel thread
        # del bus l'esecuzione prosegue in modo sincrono, altrimenti l'evento
        # viene accodato e consegnato dal ciclo di eventi del thread GUI.
        self._relay.emit(event)

    def _validate(self, event: Event[Any]) -> bool:
        """Verifica la conformita' del payload al contratto dichiarato."""
        if not isinstance(event.type, EventType):
            key = str(event.type)
            if not key.startswith(_PLUGIN_PREFIX):
                message = (
                    f"Evento '{key}' non riconosciuto: gli eventi non core devono "
                    f"usare il prefisso '{_PLUGIN_PREFIX}'"
                )
                if self._strict:
                    raise TypeError(message)
                _log.warning("%s", message)
                return False
            return True

        expected = PAYLOAD_TYPES.get(event.type)
        if expected is None or isinstance(event.payload, expected):
            return True

        message = (
            f"Payload non conforme per {event.type.value}: atteso "
            f"{expected.__name__}, ricevuto {type(event.payload).__name__}"
        )
        if self._strict:
            raise TypeError(message)
        _log.warning("%s", message)
        return False

    # ------------------------------------------------------------------ #
    # Sottoscrizione
    # ------------------------------------------------------------------ #

    def subscribe(
        self,
        event_type: EventKey,
        handler: Handler,
        *,
        replay_last: bool = False,
        once: bool = False,
    ) -> Subscription:
        """Registra un handler per un tipo di evento.

        :param handler: callable che riceve l':class:`Event`. Se e' un metodo
            legato, il bus lo referenzia in modo debole: distruggere il widget
            annulla la sottoscrizione, senza bisogno di cleanup manuale.
        :param replay_last: consegna subito l'ultimo evento noto di quel tipo,
            se esiste. Serve ai moduli che si avviano dopo che lo stato e' gia'
            cambiato — tipicamente i plugin.
        :param once: rimuove la sottoscrizione dopo la prima consegna.
        :returns: token di disiscrizione, da conservare.
        """
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        token = next(self._tokens)

        with self._lock:
            self._handlers.setdefault(key, []).append(
                _HandlerRef(handler, token, once=once)
            )
            last = self._last.get(key) if replay_last else None

        if last is not None:
            self._invoke(handler, last)

        return Subscription(self, key, token)

    def subscribe_many(
        self, event_types: Iterable[EventKey], handler: Handler
    ) -> list[Subscription]:
        """Sottoscrive lo stesso handler a piu' eventi."""
        return [self.subscribe(t, handler) for t in event_types]

    def subscribe_all(self, handler: Handler) -> Subscription:
        """Sottoscrive **ogni** evento del bus.

        Riservato a consumatori trasversali — pannello Log, telemetria,
        registratore di sessione. Un modulo funzionale che si sottoscrive a
        tutto e' quasi sempre un errore di progettazione.
        """
        return self.subscribe(_WILDCARD, handler)

    def _remove(self, key: str, token: int) -> None:
        """Rimuove una sottoscrizione dato il suo token."""
        with self._lock:
            refs = self._handlers.get(key)
            if not refs:
                return
            self._handlers[key] = [r for r in refs if r.token != token]
            if not self._handlers[key]:
                del self._handlers[key]

    # ------------------------------------------------------------------ #
    # Consegna
    # ------------------------------------------------------------------ #

    def _dispatch(self, event: Event[Any]) -> None:
        """Consegna l'evento; eseguito sempre nel thread proprietario del bus."""
        key = event.key

        with self._lock:
            specific = list(self._handlers.get(key, ()))
            wildcard = list(self._handlers.get(_WILDCARD, ()))

        targets = specific + wildcard
        if not targets:
            with self._lock:
                self._dead_letters[key] += 1
            return

        expired: list[tuple[str, int]] = []
        for ref in targets:
            handler = ref.resolve()
            if handler is None:
                # Il proprietario e' stato distrutto: si ripulisce la voce.
                expired.append((key if ref in specific else _WILDCARD, ref.token))
                continue
            self._invoke(handler, event)
            if ref.once:
                expired.append((key if ref in specific else _WILDCARD, ref.token))

        for exp_key, token in expired:
            self._remove(exp_key, token)

    def _invoke(self, handler: Handler, event: Event[Any]) -> None:
        """Esegue un handler isolandone i guasti.

        Un handler che solleva non deve impedire agli altri di ricevere
        l'evento: e' il principio "se un modulo fallisce, gli altri continuano"
        applicato alla consegna.
        """
        try:
            handler(event)
            with self._lock:
                self._delivered += 1
        except Exception as exc:
            with self._lock:
                self._handler_errors += 1
            name = getattr(handler, "__qualname__", repr(handler))
            _log.exception("Handler '%s' fallito su %s: %s", name, event.key, exc)

            if event.type is EventType.ERROR or self._in_error_dispatch:
                return  # niente ricorsione: un errore nell'errore si logga e basta
            self._in_error_dispatch = True
            try:
                from core.errors import ErrorCondition, ErrorSeverity
                from core.events import ErrorRaised

                self.publish(
                    EventType.ERROR,
                    ErrorRaised(
                        ErrorCondition.from_exception(
                            f"eventbus.{name}", exc, severity=ErrorSeverity.WARNING, ttl=8.0
                        )
                    ),
                    source="eventbus",
                )
            finally:
                self._in_error_dispatch = False

    # ------------------------------------------------------------------ #
    # Introspezione
    # ------------------------------------------------------------------ #

    def last(self, event_type: EventKey) -> Event[Any] | None:
        """Ultimo evento noto di un tipo, o ``None``."""
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        with self._lock:
            return self._last.get(key)

    def history(self) -> tuple[Event[Any], ...]:
        """Copia dello storico circolare, dal piu' vecchio al piu' recente."""
        with self._lock:
            return tuple(self._history)

    def metrics(self) -> dict[str, Any]:
        """Contatori per il pannello di diagnostica.

        ``dead_letters`` merita attenzione: un evento pubblicato che nessuno
        ascolta e' quasi sempre un sintomo, non una scelta.
        """
        with self._lock:
            return {
                "published": self._published,
                "delivered": self._delivered,
                "handler_errors": self._handler_errors,
                "subscriptions": sum(len(v) for v in self._handlers.values()),
                "dead_letters": dict(self._dead_letters),
            }

    def clear(self) -> None:
        """Rimuove sottoscrizioni e storico. Usato nei test fra un caso e l'altro."""
        with self._lock:
            self._handlers.clear()
            self._last.clear()
            self._history.clear()
            self._dead_letters.clear()

    def __iter__(self) -> Iterator[Event[Any]]:
        return iter(self.history())
