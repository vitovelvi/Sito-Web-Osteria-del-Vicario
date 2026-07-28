"""Server JCP autonomo, guidato da uno scenario.

Serve a puntarci l'interfaccia reale — o qualunque altro client — senza avere
un backend vero. È la differenza fra "provare la GUI contro un finto interno" e
"provarla contro qualcosa che sta davvero dall'altra parte di un socket": la
seconda mette alla prova anche il trasporto, la serializzazione e la
riconnessione, che sono dove si nascondono i difetti più fastidiosi.

Uso::

    jarvis-sim --scenario rete-instabile --port 8765
    jarvis-sim --list
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from jarvis_sim.library import by_name, names
from jarvis_sim.scenario import Scenario
from jarvis_sim.transport import SimTransport

__all__ = ["main", "serve"]

_log = logging.getLogger("jarvis_sim.server")


async def _bridge(websocket, scenario: Scenario) -> None:
    """Collega un client al proprio esecutore di scenario.

    Ogni connessione riceve un'istanza nuova: due client non devono condividere
    stato, altrimenti gli scenari smettono di essere riproducibili appena se ne
    collega un secondo.
    """
    transport = SimTransport(scenario)
    await transport.connect()
    _log.info("Client connesso — %s", scenario.describe())

    async def verso_client() -> None:
        async for messaggio in transport.receive():
            await websocket.send(json.dumps(messaggio, separators=(",", ":")))

    async def verso_simulatore() -> None:
        async for grezzo in websocket:
            try:
                await transport.send(json.loads(grezzo))
            except (json.JSONDecodeError, TypeError):
                _log.warning("Frame non decodificabile dal client: ignorato")

    uscita = asyncio.create_task(verso_client())
    ingresso = asyncio.create_task(verso_simulatore())
    try:
        # Basta che uno dei due finisca: il canale è chiuso da entrambi i lati.
        await asyncio.wait({uscita, ingresso}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (uscita, ingresso):
            task.cancel()
        await transport.close()
        _log.info("Client disconnesso")


async def serve(scenario: Scenario, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Avvia il server fino a interruzione."""
    try:
        import websockets
    except ImportError:
        raise SystemExit(
            "Il pacchetto 'websockets' non è installato.\n"
            "Installa gli extra del server: pip install 'jarvis-sim[server]'"
        ) from None

    async def handler(websocket) -> None:
        await _bridge(websocket, scenario)

    async with websockets.serve(handler, host, port, ping_interval=None):
        _log.info("In ascolto su ws://%s:%d — scenario '%s'", host, port, scenario.name)
        _log.info("Per collegare l'interfaccia: --transport websocket --url ws://%s:%d", host, port)
        await asyncio.Future()  # fino a Ctrl+C


def main(argv: list[str] | None = None) -> int:
    """Punto d'ingresso da riga di comando."""
    parser = argparse.ArgumentParser(
        prog="jarvis-sim", description="Server JCP simulato con scenari riproducibili"
    )
    parser.add_argument("--scenario", default="nominale", help="Nome dello scenario incluso.")
    parser.add_argument("--file", type=Path, help="Scenario da file JSON, invece che incluso.")
    parser.add_argument("--seed", type=int, help="Sovrascrive il seme dello scenario.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--list", action="store_true", help="Elenca gli scenari e termina.")
    parser.add_argument("--export", type=Path, help="Salva lo scenario scelto in JSON e termina.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list:
        for nome in names():
            scenario = by_name(nome)
            print(f"  {nome:26} {scenario.description}")
        return 0

    try:
        scenario = Scenario.load(args.file) if args.file else by_name(args.scenario)
    except (KeyError, ValueError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2

    if args.seed is not None:
        scenario = Scenario.from_dict({**scenario.to_dict(), "seed": args.seed})

    if args.export:
        scenario.save(args.export)
        print(f"Scenario '{scenario.name}' salvato in {args.export}")
        return 0

    try:
        asyncio.run(serve(scenario, args.host, args.port))
    except KeyboardInterrupt:
        _log.info("Interrotto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
