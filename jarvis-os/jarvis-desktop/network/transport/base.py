"""Contratto del trasporto.

Il trasporto muove **dizionari già decodificati**, non buste JCP. È il confine
corretto: il trasporto sa di byte, frame e connessioni; l'adapter sa di
dialetti; solo sopra l'adapter si parla JCP.

Se il trasporto conoscesse JCP, un backend con un dialetto diverso richiederebbe
un trasporto diverso — e si perderebbe la possibilità di usare lo stesso
WebSocket con backend differenti, che è metà del valore dell'adapter layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

__all__ = ["ITransport"]


@runtime_checkable
class ITransport(Protocol):
    """Canale bidirezionale di messaggi decodificati."""

    @property
    def endpoint(self) -> str:
        """Descrizione leggibile della destinazione, per log e HUD."""
        ...

    async def connect(self) -> None:
        """Apre il canale.

        :raises TransportError: se la connessione non riesce. Il chiamante
            riprova secondo la propria politica di backoff — il trasporto non
            decide quando insistere.
        """
        ...

    async def close(self) -> None:
        """Chiude il canale. Idempotente, non solleva mai."""
        ...

    async def send(self, message: dict[str, Any]) -> None:
        """Invia un messaggio.

        :raises TransportError: se il canale non è utilizzabile.
        """
        ...

    def receive(self) -> AsyncIterator[dict[str, Any]]:
        """Itera sui messaggi in arrivo finché il canale resta aperto.

        I frame non decodificabili **non** compaiono qui: vengono scartati e
        loggati. Un backend che invia spazzatura non deve poter interrompere il
        ciclo di lettura.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Stato del canale dal punto di vista del trasporto."""
        ...
