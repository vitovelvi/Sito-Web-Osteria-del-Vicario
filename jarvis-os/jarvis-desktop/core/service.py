"""Contratto comune dei servizi.

Un "servizio" e' un sottosistema con un ciclo di vita: rete, audio, visione,
monitor di sistema. Averne uno **solo** contratto permette al registry di
avviarli in ordine, al supervisor di sorvegliarli e all'HUD di mostrarne lo
stato senza sapere nulla di cosa facciano.

E' anche cio' che rende concreta la richiesta del brief "se un modulo fallisce,
mostrane lo stato e continua": senza uno stato di salute uniforme, quella frase
resta un'intenzione.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

__all__ = ["BaseService", "Health", "IService", "ServiceState"]


class ServiceState(StrEnum):
    """Stato di salute di un servizio."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    """Funziona parzialmente: es. webcam attiva ma a frame rate ridotto."""

    FAILED = "failed"
    """Si e' interrotto. Il supervisor puo' tentare il riavvio."""

    DISABLED = "disabled"
    """Spento da configurazione o per capability mancante: non e' un guasto."""


@dataclass(frozen=True, slots=True)
class Health:
    """Esito di un controllo di salute."""

    state: ServiceState
    detail: str | None = None
    checked_at: float = field(default_factory=time.monotonic)

    @property
    def is_usable(self) -> bool:
        """Vero se il servizio puo' essere usato, anche se non al meglio."""
        return self.state in (ServiceState.RUNNING, ServiceState.DEGRADED)


@runtime_checkable
class IService(Protocol):
    """Interfaccia minima di un sottosistema sorvegliato.

    Deliberatamente piccola: piu' e' larga, piu' e' difficile sostituire
    un'implementazione — che e' esattamente cio' che il progetto deve permettere
    negli anni.
    """

    name: str

    def start(self) -> None:
        """Avvia il servizio. Deve tornare in fretta: il lavoro lungo va in un
        thread. Bloccare qui significa bloccare l'avvio dell'interfaccia."""
        ...

    def stop(self) -> None:
        """Ferma il servizio e ne rilascia le risorse. Deve essere idempotente."""
        ...

    def health(self) -> Health:
        """Stato corrente. Non deve mai sollevare eccezioni."""
        ...


class BaseService(ABC):
    """Implementazione di comodo con la contabilita' di stato gia' pronta.

    Le sottoclassi implementano :meth:`_on_start` e :meth:`_on_stop`; il resto
    (idempotenza, transizioni di stato, cattura delle eccezioni) e' qui perche'
    ripeterlo in ogni servizio e' il modo piu' rapido per sbagliarlo in uno.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._state = ServiceState.STOPPED
        self._detail: str | None = None

    # -- da implementare nelle sottoclassi -------------------------------- #

    @abstractmethod
    def _on_start(self) -> None:
        """Avvio effettivo. Sollevare un'eccezione porta lo stato a ``FAILED``."""

    def _on_stop(self) -> None:  # noqa: B027 - volutamente non astratto
        """Arresto effettivo.

        Vuoto di proposito e **non** astratto: molti servizi non hanno risorse
        da rilasciare, e obbligarli a scrivere un metodo vuoto sarebbe rumore.
        """

    # -- ciclo di vita ---------------------------------------------------- #

    def start(self) -> None:
        if self._state in (ServiceState.RUNNING, ServiceState.STARTING):
            return
        self._state = ServiceState.STARTING
        try:
            self._on_start()
        except Exception as exc:
            self._state = ServiceState.FAILED
            self._detail = f"{type(exc).__name__}: {exc}"
            raise
        else:
            self._state = ServiceState.RUNNING
            self._detail = None

    def stop(self) -> None:
        if self._state is ServiceState.STOPPED:
            return
        try:
            self._on_stop()
        finally:
            self._state = ServiceState.STOPPED

    def health(self) -> Health:
        return Health(state=self._state, detail=self._detail)

    # -- utilita' per le sottoclassi -------------------------------------- #

    def mark_degraded(self, detail: str) -> None:
        """Segnala funzionamento parziale senza interrompere il servizio."""
        self._state = ServiceState.DEGRADED
        self._detail = detail

    def mark_running(self) -> None:
        """Segnala il ritorno alla piena operativita'."""
        self._state = ServiceState.RUNNING
        self._detail = None

    def mark_disabled(self, detail: str) -> None:
        """Segnala che il servizio e' spento per scelta, non per guasto.

        Distinguere ``DISABLED`` da ``FAILED`` conta: il supervisor non tenta di
        riavviare cio' che e' stato disattivato, e l'HUD non mostra un allarme
        per una funzione che l'utente non ha chiesto.
        """
        self._state = ServiceState.DISABLED
        self._detail = detail

    def __repr__(self) -> str:  # pragma: no cover - diagnostica
        return f"<{type(self).__name__} name={self.name!r} state={self._state.value}>"
