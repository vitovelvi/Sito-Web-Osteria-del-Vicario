"""Trasporto WebSocket verso OpenClaw."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from core.errors import ProtocolError, TransportError
from core.logging_setup import LogCategory, get_logger
from core.protocol.envelope import Envelope

__all__ = ["WebSocketTransport"]

_log = get_logger(LogCategory.NETWORK, "websocket")


class WebSocketTransport:
    """Canale WebSocket. Implementa :class:`~network.transport.base.ITransport`."""

    def __init__(self, url: str, *, connect_timeout: float = 5.0) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._socket: Any | None = None

    @property
    def endpoint(self) -> str:
        return self._url

    @property
    def is_connected(self) -> bool:
        return self._socket is not None

    async def connect(self) -> None:
        """Apre la connessione entro il timeout configurato.

        Il timeout è esplicito: senza, un host irraggiungibile lascerebbe il
        tentativo appeso per il tempo di default del sistema operativo — decine
        di secondi durante i quali l'HUD direbbe "connessione in corso" senza
        che nulla stia realmente accadendo.
        """
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - dipendenza dichiarata
            raise TransportError(
                "Il pacchetto 'websockets' non è installato: "
                "usa --transport mock oppure installa le dipendenze."
            ) from exc

        try:
            self._socket = await asyncio.wait_for(
                websockets.connect(
                    self._url,
                    # Il ping di protocollo è disattivato: l'heartbeat
                    # applicativo misura la latenza end-to-end, che è
                    # l'informazione utile. Due meccanismi sovrapposti darebbero
                    # numeri diversi e nessuno saprebbe quale credere.
                    ping_interval=None,
                    max_size=8 * 1024 * 1024,
                ),
                timeout=self._connect_timeout,
            )
        except TimeoutError as exc:
            raise TransportError(
                f"Nessuna risposta da {self._url} entro {self._connect_timeout:.0f}s"
            ) from exc
        except Exception as exc:
            raise TransportError(f"Connessione a {self._url} non riuscita: {exc}") from exc

        _log.info("Connesso a %s", self._url)

    async def close(self) -> None:
        """Chiude il canale senza mai sollevare."""
        socket, self._socket = self._socket, None
        if socket is None:
            return
        try:
            await socket.close()
        except Exception:
            _log.debug("Chiusura del socket non pulita", exc_info=True)

    async def send(self, envelope: Envelope) -> None:
        socket = self._socket
        if socket is None:
            raise TransportError("Canale non aperto")
        try:
            await socket.send(envelope.to_json())
        except Exception as exc:
            raise TransportError(f"Invio non riuscito: {exc}") from exc

    async def receive(self) -> AsyncIterator[Envelope]:
        """Itera sulle buste valide in arrivo.

        Un messaggio malformato viene loggato e **saltato**: il ciclo prosegue.
        Interrompere la connessione per un payload sbagliato darebbe a un bug
        del backend il potere di scollegare l'interfaccia.
        """
        socket = self._socket
        if socket is None:
            raise TransportError("Canale non aperto")

        try:
            async for raw in socket:
                try:
                    yield Envelope.from_json(raw)
                except ProtocolError as exc:
                    _log.warning("Messaggio scartato: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.info("Canale interrotto: %s", exc)
        finally:
            self._socket = None
