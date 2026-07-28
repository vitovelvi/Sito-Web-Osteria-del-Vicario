#!/usr/bin/env python3
"""Verifica la conformità di un backend a JCP 1.0.

Esegue i controlli della specifica contro un backend reale (WebSocket) o
contro uno scenario simulato, e restituisce un codice d'uscita utilizzabile in
integrazione continua.

::

    python tools/jcp_validate.py --url ws://127.0.0.1:8765
    python tools/jcp_validate.py --scenario nominale
    python tools/jcp_validate.py --url ws://host:8765 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict

from jarvis_sdk.conformance import run_conformance


def _websocket_factory(url: str, timeout: float):
    """Costruisce trasporti WebSocket nuovi, uno per controllo."""

    class _Transport:
        def __init__(self) -> None:
            self._socket = None

        @property
        def is_connected(self) -> bool:
            return self._socket is not None

        async def connect(self) -> None:
            import websockets

            self._socket = await asyncio.wait_for(
                websockets.connect(url, ping_interval=None), timeout=timeout
            )

        async def close(self) -> None:
            socket, self._socket = self._socket, None
            if socket is not None:
                await socket.close()

        async def send(self, message: dict) -> None:
            if self._socket is None:
                return
            await self._socket.send(json.dumps(message, separators=(",", ":")))

        async def receive(self):
            if self._socket is None:
                return
            try:
                async for grezzo in self._socket:
                    try:
                        decodificato = json.loads(grezzo)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(decodificato, dict):
                        yield decodificato
            except Exception:
                return

    return _Transport


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jcp-validate", description="Verifica di conformità a JCP 1.0"
    )
    sorgente = parser.add_mutually_exclusive_group(required=True)
    sorgente.add_argument("--url", help="Backend WebSocket da verificare.")
    sorgente.add_argument("--scenario", help="Scenario simulato incluso.")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--json", action="store_true", help="Esito in JSON.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    if args.url:
        factory = _websocket_factory(args.url, args.timeout)
        bersaglio = args.url
    else:
        try:
            from jarvis_sim import SimTransport, by_name

            scenario = by_name(args.scenario)
        except (ImportError, KeyError) as exc:
            print(f"Errore: {exc}", file=sys.stderr)
            return 2
        factory = lambda: SimTransport(scenario)  # noqa: E731 - factory di una riga
        bersaglio = f"sim://{args.scenario}"

    report = asyncio.run(run_conformance(factory, timeout=args.timeout))

    if args.json:
        print(
            json.dumps(
                {
                    "target": bersaglio,
                    "conforms": report.conforms,
                    "results": [asdict(r) for r in report.results],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(report.as_text())

    # Codice d'uscita: 0 conforme, 1 non conforme. Utilizzabile in CI senza
    # dover interpretare l'output.
    return 0 if report.conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())
