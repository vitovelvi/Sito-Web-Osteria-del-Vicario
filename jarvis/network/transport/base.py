"""Contratto del trasporto verso il backend.

Il trasporto sposta buste. Non le interpreta, non conosce l'handshake, non sa
cosa sia una capability. Questa povertà è deliberata: è ciò che permette di
sostituire WebSocket con il backend simulato — o domani con una pipe locale o
gRPC — senza che nulla sopra se ne accorga.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from core.protocol.envelope import Envelope

__all__ = ["ITransport"]


@runtime_checkable
class ITransport(Protocol):
    """Canale bidirezionale di buste."""

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
        """Chiude il canale. Deve essere idempotente e non sollevare."""
        ...

    async def send(self, envelope: Envelope) -> None:
        """Invia una busta.

        :raises TransportError: se il canale non è utilizzabile.
        """
        ...

    def receive(self) -> AsyncIterator[Envelope]:
        """Itera sulle buste in arrivo finché il canale resta aperto.

        Le buste malformate **non** compaiono qui: vengono scartate e loggate
        dal trasporto. Un backend che sbaglia non deve poter interrompere il
        ciclo di lettura.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Stato del canale dal punto di vista del trasporto."""
        ...
