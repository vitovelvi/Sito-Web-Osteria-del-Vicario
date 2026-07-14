"""Punto d'ingresso di JARVIS.

Comandi:
    python -m jarvis run     — avvia il sistema completo (dashboard + REPL se in tty)
    python -m jarvis demo    — boot completo + richieste dimostrative end-to-end
    python -m jarvis status  — stampa lo snapshot di stato e termina
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys

from jarvis.config import load_config
from jarvis.core.kernel import Kernel
from jarvis.security import SecurityLevel


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="JARVIS — Cognitive Operating System"
    )
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "demo", "status"],
                        help="modalità di avvio (default: run)")
    parser.add_argument("--config", default=None,
                        help="percorso del file di configurazione")
    return parser


async def _console_confirmer(description: str, level: SecurityLevel) -> bool:
    """Canale di conferma da terminale per le operazioni di Livello 2-3."""
    prompt = f"\n⚠️  Conferma richiesta: {description}\nProcedere? [s/N] "
    answer = await asyncio.to_thread(input, prompt)
    return answer.strip().lower() in {"s", "si", "sì", "y", "yes"}


async def _repl(kernel: Kernel) -> None:
    """Prompt interattivo: ogni riga diventa una richiesta al sistema."""
    print(f"\n{kernel.identity.name} in ascolto. Comandi: 'stato', 'esci'.")
    while True:
        try:
            line = (await asyncio.to_thread(input, "\nvoi> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line.lower() in {"esci", "exit", "quit"}:
            break
        if line.lower() in {"stato", "status"}:
            print(json.dumps(kernel.state(), ensure_ascii=False,
                             indent=2, default=str)[:4000])
            continue
        try:
            response = await kernel.submit_and_wait(line)
            print(f"\n{kernel.identity.name}: {response.get('text', '')}")
        except asyncio.TimeoutError:
            print("(nessuna risposta entro il timeout)")


async def _run(kernel: Kernel) -> None:
    if sys.stdin.isatty():
        kernel.gate.set_confirmer(_console_confirmer)
    await kernel.start()
    try:
        if sys.stdin.isatty():
            await _repl(kernel)
        else:
            # Modalità servizio: resta in vita finché non viene interrotto.
            print(f"{kernel.identity.name} in esecuzione (Ctrl+C per uscire). "
                  + (f"Dashboard: {kernel.dashboard.url}" if kernel.dashboard else ""))
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.Event().wait()
    finally:
        await kernel.stop()


async def _demo(kernel: Kernel) -> None:
    """Dimostrazione end-to-end: boot, richieste, arresto ordinato."""
    await kernel.start()
    print(f"\n=== DEMO {kernel.identity.name} ===")
    if kernel.dashboard:
        print(f"Dashboard: {kernel.dashboard.url}\n")
    requests = [
        "Analizza lo stato del sistema e fammi un report",
        "Ricorda che preferisco report sintetici la mattina",
        "Elenca i file nella directory di lavoro",
    ]
    for text in requests:
        print(f"voi> {text}")
        try:
            response = await kernel.submit_and_wait(text, timeout=60)
            print(f"{kernel.identity.name}: {response.get('text', '')}\n")
        except asyncio.TimeoutError:
            print("(timeout)\n")
    await kernel.bus.drain()
    snapshot = kernel.state()
    print("--- Stato finale ---")
    print(f"Task: {snapshot['tasks']['by_state']}")
    print(f"Memoria: {snapshot['memory']}")
    print(f"Eventi pubblicati: {snapshot['bus']['published']}")
    await kernel.stop()


async def _status(kernel: Kernel) -> None:
    await kernel.start()
    await asyncio.sleep(0.2)  # lascia campionare il primo giro di osservazione
    print(json.dumps(kernel.state(), ensure_ascii=False, indent=2, default=str))
    await kernel.stop()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    kernel = Kernel(load_config(args.config))
    runner = {"run": _run, "demo": _demo, "status": _status}[args.command]
    try:
        asyncio.run(runner(kernel))
    except KeyboardInterrupt:
        print("\nArresto richiesto dall'utente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
