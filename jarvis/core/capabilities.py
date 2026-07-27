"""Capability Manager: cosa il backend dichiara di saper fare.

L'interfaccia si adatta a cio' che OpenClaw dichiara, e a nient'altro. Un
pannello Task senza la capability ``tasks`` non viene nascosto per prudenza: non
viene proprio costruito, perche' mostrare un pannello vuoto che non si popolera'
mai e' peggio che non mostrarlo.

Il valore di questo modulo si vede nel tempo. Con la negoziazione:

* un backend piu' vecchio fa **degradare** la GUI in modo controllato;
* un backend piu' recente puo' dichiarare capability sconosciute, che vengono
  conservate e ignorate senza errori;
* aggiungere una funzione non richiede di aggiornare GUI e backend nello stesso
  momento — che e' l'unico modo perche' un progetto sopravviva agli anni.

Alla disconnessione l'insieme viene **svuotato**: senza canale nessuna funzione
e' disponibile, e l'interfaccia deve dirlo invece di lasciare pulsanti attivi
che falliranno al primo clic.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from core.errors import JarvisError
from core.eventbus import EventBus, Subscription
from core.events import CapabilitySet, EventType
from core.logging_setup import LogCategory, get_logger
from core.protocol.capabilities import CLIENT_CAPABILITIES, Capability

__all__ = ["CapabilityManager", "MissingCapabilityError"]

_log = get_logger(LogCategory.PROTOCOL, "capabilities")


class MissingCapabilityError(JarvisError):
    """Sollevata da :meth:`CapabilityManager.require` quando manca una funzione."""


class CapabilityManager:
    """Registro delle capability negoziate con il backend."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._granted: frozenset[str] = frozenset()
        self._unknown: frozenset[str] = frozenset()
        self._protocol_version = 0
        self._listeners: list[Callable[[frozenset[str]], None]] = []

    # ------------------------------------------------------------------ #
    # Interrogazione
    # ------------------------------------------------------------------ #

    def has(self, capability: Capability | str) -> bool:
        """Indica se il backend ha dichiarato una capability."""
        name = capability.value if isinstance(capability, Capability) else str(capability)
        with self._lock:
            return name in self._granted

    def has_all(self, capabilities: Iterable[Capability | str]) -> bool:
        """Vero se tutte le capability indicate sono disponibili."""
        return all(self.has(c) for c in capabilities)

    def require(self, capability: Capability | str) -> None:
        """Verifica una capability, sollevando se assente.

        Da usare nei percorsi in cui l'assenza e' un bug della GUI — aver
        costruito un pannello senza averne verificato il presupposto — non nei
        percorsi guidati dall'utente, dove l'assenza va gestita disabilitando
        il comando.
        """
        if not self.has(capability):
            name = capability.value if isinstance(capability, Capability) else capability
            raise MissingCapabilityError(
                f"Il backend non dichiara la capability '{name}'"
            )

    @property
    def granted(self) -> frozenset[str]:
        """Capability note e disponibili."""
        with self._lock:
            return self._granted

    @property
    def unknown(self) -> frozenset[str]:
        """Capability dichiarate dal backend ma sconosciute a questa build.

        Non sono un errore: sono il segnale che il backend e' piu' avanti della
        GUI. Compaiono nella diagnostica come suggerimento di aggiornamento.
        """
        with self._lock:
            return self._unknown

    @property
    def protocol_version(self) -> int:
        """Versione di protocollo concordata; ``0`` prima dell'handshake."""
        with self._lock:
            return self._protocol_version

    @property
    def client_capabilities(self) -> frozenset[str]:
        """Capability offerte dalla GUI, inviate nell'handshake."""
        return CLIENT_CAPABILITIES

    # ------------------------------------------------------------------ #
    # Aggiornamento
    # ------------------------------------------------------------------ #

    def apply(self, declared: Iterable[str], *, protocol_version: int) -> CapabilitySet:
        """Registra le capability dichiarate dal backend.

        :param declared: elenco grezzo ricevuto in ``server.hello``.
        :param protocol_version: versione dichiarata dal backend.
        :returns: l'insieme risultante, gia' suddiviso fra note e sconosciute.
        """
        known = {c.value for c in Capability}
        received = {str(c) for c in declared}
        granted = frozenset(received & known)
        unknown = frozenset(received - known)

        with self._lock:
            previous = self._granted
            self._granted = granted
            self._unknown = unknown
            self._protocol_version = protocol_version

        if granted:
            _log.info("Capability disponibili: %s", ", ".join(sorted(granted)))
        else:
            _log.warning("Il backend non ha dichiarato alcuna capability nota")
        if unknown:
            _log.info(
                "Capability dichiarate ma non supportate da questa versione: %s",
                ", ".join(sorted(unknown)),
            )

        missing = CLIENT_CAPABILITIES - granted
        if missing:
            _log.debug(
                "Funzioni della GUI senza corrispondenza nel backend: %s",
                ", ".join(sorted(missing)),
            )

        result = CapabilitySet(
            granted=granted, protocol_version=protocol_version, unknown=unknown
        )
        if granted != previous:
            self._bus.publish(EventType.CAPABILITIES_UPDATED, result, source="capabilities")
            self._notify(granted)
        return result

    def clear(self) -> None:
        """Svuota l'insieme alla caduta del canale."""
        with self._lock:
            if not self._granted and not self._unknown:
                return
            self._granted = frozenset()
            self._unknown = frozenset()
            self._protocol_version = 0

        _log.info("Capability azzerate: nessun backend connesso")
        self._bus.publish(
            EventType.CAPABILITIES_UPDATED, CapabilitySet(), source="capabilities"
        )
        self._notify(frozenset())

    # ------------------------------------------------------------------ #
    # Reazione ai cambiamenti
    # ------------------------------------------------------------------ #

    def on_change(self, listener: Callable[[frozenset[str]], None]) -> None:
        """Registra una callback invocata a ogni variazione dell'insieme.

        Comodo per i widget che devono abilitarsi o disabilitarsi: evita di far
        sottoscrivere ogni pulsante al bus per un dato che ha un solo
        proprietario.
        """
        with self._lock:
            self._listeners.append(listener)

    def bind_enabled(
        self, widget: object, capability: Capability | str
    ) -> Subscription:
        """Lega l'abilitazione di un widget alla presenza di una capability.

        Il widget deve esporre ``setEnabled``. La sottoscrizione restituita va
        conservata dal chiamante; alla distruzione del widget il bus rimuove da
        solo il riferimento, essendo debole sui metodi legati.
        """
        setter = getattr(widget, "setEnabled", None)
        if not callable(setter):
            raise TypeError(f"{type(widget).__name__} non espone setEnabled()")

        setter(self.has(capability))

        def _on_event(_: object) -> None:
            setter(self.has(capability))

        return self._bus.subscribe(EventType.CAPABILITIES_UPDATED, _on_event)

    def _notify(self, granted: frozenset[str]) -> None:
        """Invoca le callback registrate, isolandone i guasti."""
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(granted)
            except Exception:  # noqa: BLE001 - un ascoltatore rotto non blocca gli altri
                _log.exception("Ascoltatore di capability fallito")
