#!/usr/bin/env python3
"""Il backend JCP più piccolo che supera la verifica di conformità.

Non fa nulla di intelligente: risponde all'handshake, al ping, e restituisce
una risposta fissa. Serve come **riferimento di ciò che è obbligatorio**: tutto
quello che c'è qui dentro è necessario, tutto ciò che manca è facoltativo.

Circa centoventi righe, senza dipendenze oltre a ``jarvis-protocol`` e
``websockets``.

::

    python examples/minimal-backend/backend.py
    python tools/jcp_validate.py --url ws://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from jarvis_protocol.capabilities import Capability
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.messages import MessageType
from jarvis_protocol.version import PROTOCOL_VERSION

_log = logging.getLogger("minimal-backend")

#: Ciò che questo backend dichiara di saper fare. Dichiarare meno del vero è
#: lecito; dichiarare più del vero no — il client costruirebbe interfacce per
#: funzioni che non esistono.
CAPABILITIES = [Capability.CHAT_STREAM.value, Capability.IDENTITY.value]


async def handle(websocket) -> None:
    """Serve una connessione fino alla chiusura."""

    async def invia(type_: str, payload: dict | None = None, corr: str | None = None) -> None:
        busta = Envelope.make(type_, payload or {}, corr=corr)
        await websocket.send(busta.to_json())

    async for grezzo in websocket:
        # Regola 4 della conformità: un messaggio illeggibile non chiude il
        # canale. Si scarta e si prosegue.
        try:
            busta = Envelope.from_json(grezzo)
        except Exception:
            _log.warning("Messaggio non decodificabile: ignorato")
            continue

        if busta.type == MessageType.SESSION_HELLO:
            await invia(
                MessageType.SESSION_WELCOME,
                {
                    "protocol": {
                        "major": PROTOCOL_VERSION.major,
                        "minor": PROTOCOL_VERSION.minor,
                    },
                    "server": {
                        "name": "minimal-backend",
                        "version": "1.0.0",
                        "assistant_name": "J.A.R.V.I.S.",
                        "model": "nessuno",
                    },
                    "capabilities": CAPABILITIES,
                    "session_id": "minimal",
                },
                corr=busta.id,
            )
            await invia(MessageType.AGENT_STATE, {"state": "idle"})

        elif busta.type == MessageType.PING:
            # Il 'corr' è obbligatorio: senza, il client non può misurare la
            # latenza e considera il backend non conforme.
            await invia(MessageType.PONG, {}, corr=busta.id)

        elif busta.type == MessageType.CHAT_SEND:
            message_id = str(busta.payload.get("message_id", "?"))
            await invia(MessageType.AGENT_STATE, {"state": "thinking"})
            await asyncio.sleep(0.2)
            await invia(MessageType.AGENT_STATE, {"state": "speaking"})

            for parola in ["Ricevuto.", "Non", "so", "fare", "altro,", "ma", "sono", "conforme."]:
                await invia(
                    MessageType.CHAT_DELTA, {"text": parola + " ", "message_id": message_id}
                )
                await asyncio.sleep(0.05)

            await invia(MessageType.CHAT_DONE, {"message_id": message_id})
            await invia(MessageType.AGENT_STATE, {"state": "idle"})

        else:
            # Un tipo sconosciuto si ignora. È la regola che permette a un
            # client più recente di parlare senza rompere questo backend.
            _log.debug("Tipo ignorato: %s", busta.type)


async def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    import websockets

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    async with websockets.serve(handle, host, port, ping_interval=None):
        _log.info("In ascolto su ws://%s:%d", host, port)
        await asyncio.Future()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
