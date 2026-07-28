"""Verifica di conformità a JCP 1.0.

I sei punti di §10 della specifica sono affermazioni verificabili. Finché
restano prosa, "conforme a JCP" significa "l'autore crede di esserlo". Qui
diventano una suite eseguibile contro un backend reale o simulato.

Ogni controllo è **indipendente**: un backend che fallisce l'handshake ottiene
comunque il verdetto sugli altri punti, perché sapere quante cose sono rotte
vale più che sapere quale si è rotta per prima.

I controlli sono deliberatamente **tolleranti sui tempi** e severi sulla
semantica: un backend lento è conforme, un backend che chiude il canale davanti
a un messaggio sconosciuto non lo è.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jarvis_protocol.capabilities import CLIENT_CAPABILITIES
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.messages import MessageType
from jarvis_protocol.version import PROTOCOL_VERSION

__all__ = ["CheckResult", "ConformanceReport", "Outcome", "run_conformance"]


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    """Il controllo non era applicabile: una capability non dichiarata non è
    una violazione."""


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Esito di un singolo controllo."""

    id: str
    title: str
    outcome: Outcome
    detail: str = ""
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.outcome is not Outcome.FAIL


@dataclass
class ConformanceReport:
    """Esito complessivo."""

    results: list[CheckResult] = field(default_factory=list)
    backend: str = "sconosciuto"

    @property
    def conforms(self) -> bool:
        """Vero se nessun controllo è fallito."""
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.outcome is Outcome.FAIL]

    def summary(self) -> str:
        superati = sum(1 for r in self.results if r.outcome is Outcome.PASS)
        saltati = sum(1 for r in self.results if r.outcome is Outcome.SKIP)
        falliti = len(self.failures)
        parti = [f"{superati} superati"]
        if saltati:
            parti.append(f"{saltati} non applicabili")
        if falliti:
            parti.append(f"{falliti} FALLITI")
        return " · ".join(parti)

    def as_text(self) -> str:
        """Rapporto leggibile, adatto a un terminale o a un pannello."""
        righe = [f"Conformità JCP {PROTOCOL_VERSION} — backend: {self.backend}", ""]
        # Il trattino lungo per "non applicabile" e' voluto: distingue a colpo
        # d'occhio un controllo saltato da un segno di spunta o di errore.
        simboli = {Outcome.PASS: "✓", Outcome.FAIL: "✗", Outcome.SKIP: "–"}  # noqa: RUF001
        for risultato in self.results:
            righe.append(
                f" {simboli[risultato.outcome]} {risultato.id}  {risultato.title}"
                + (f"\n     {risultato.detail}" if risultato.detail else "")
            )
        righe += ["", self.summary()]
        return "\n".join(righe)


class _Transport(Protocol):
    """Ciò che serve alla verifica: il contratto minimo del trasporto."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def send(self, message: dict[str, Any]) -> None: ...
    def receive(self) -> AsyncIterator[dict[str, Any]]: ...


class _Session:
    """Sessione di prova: invia e raccoglie, con attese limitate."""

    def __init__(self, transport: _Transport, timeout: float) -> None:
        self._transport = transport
        self._timeout = timeout
        self._received: list[Envelope] = []
        self._pump: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _Session:
        await self._transport.connect()
        self._pump = asyncio.create_task(self._drain())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._pump is not None:
            self._pump.cancel()
        await self._transport.close()

    async def _drain(self) -> None:
        try:
            async for messaggio in self._transport.receive():
                try:
                    self._received.append(Envelope.from_wire(messaggio))
                except Exception:
                    # Un messaggio illeggibile è esso stesso un dato: si
                    # prosegue, sarà il controllo pertinente a giudicarlo.
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    async def send(self, envelope: Envelope) -> None:
        await self._transport.send(envelope.to_wire())

    async def wait_for(self, message_type: str, timeout: float | None = None) -> Envelope | None:
        """Attende un messaggio di un tipo, o restituisce ``None`` allo scadere."""
        limite = time.monotonic() + (timeout or self._timeout)
        while time.monotonic() < limite:
            for busta in self._received:
                if busta.type == message_type:
                    return busta
            await asyncio.sleep(0.02)
        return None

    @property
    def received(self) -> list[Envelope]:
        return list(self._received)

    def channel_alive(self) -> bool:
        """Vero se il trasporto risulta ancora aperto."""
        return bool(getattr(self._transport, "is_connected", True))


async def run_conformance(
    transport_factory: Any,
    *,
    timeout: float = 5.0,
) -> ConformanceReport:
    """Esegue la suite di conformità.

    :param transport_factory: callable che restituisce un trasporto **nuovo**.
        Serve una connessione pulita per controllo: riusarne una sola
        renderebbe ogni esito dipendente dai precedenti, e un fallimento
        iniziale nasconderebbe tutto il resto.
    :param timeout: attesa massima per ciascuna risposta.
    """
    report = ConformanceReport()

    for controllo in (
        _check_handshake,
        _check_capabilities,
        _check_heartbeat,
        _check_unknown_message,
        _check_malformed_message,
        _check_extension_space,
    ):
        avvio = time.monotonic()
        try:
            risultato = await controllo(transport_factory, timeout)
        except Exception as exc:
            risultato = CheckResult(
                id=controllo.__name__.removeprefix("_check_"),
                title="controllo interrotto",
                outcome=Outcome.FAIL,
                detail=f"{type(exc).__name__}: {exc}",
            )
        report.results.append(
            CheckResult(
                id=risultato.id,
                title=risultato.title,
                outcome=risultato.outcome,
                detail=risultato.detail,
                duration_ms=(time.monotonic() - avvio) * 1000,
            )
        )

    welcome = next(
        (r for r in report.results if r.id == "handshake" and r.outcome is Outcome.PASS), None
    )
    if welcome:
        report.backend = welcome.detail or "conforme"
    return report


def _hello() -> Envelope:
    return Envelope.make(
        MessageType.SESSION_HELLO,
        {
            "protocol": {"major": PROTOCOL_VERSION.major, "minor": PROTOCOL_VERSION.minor},
            "client": {
                "name": "jarvis-sdk-conformance",
                "version": "1.0.0",
                "instance_id": "conformance",
            },
            "capabilities": sorted(CLIENT_CAPABILITIES),
            "auth": {"scheme": "none"},
        },
    )


async def _check_handshake(factory: Any, timeout: float) -> CheckResult:
    """§10.1 — risponde a ``session.hello``."""
    async with _Session(factory(), timeout) as sessione:
        richiesta = _hello()
        await sessione.send(richiesta)

        benvenuto = await sessione.wait_for(MessageType.SESSION_WELCOME)
        if benvenuto is None:
            rifiuto = await sessione.wait_for(MessageType.SESSION_DENIED, timeout=0.5)
            if rifiuto is not None:
                return CheckResult(
                    "handshake",
                    "risponde all'handshake",
                    Outcome.PASS,
                    "connessione rifiutata, ma con session.denied: conforme",
                )
            return CheckResult(
                "handshake",
                "risponde all'handshake",
                Outcome.FAIL,
                f"nessun session.welcome entro {timeout:.0f}s",
            )

        server = benvenuto.payload.get("server", {})
        nome = server.get("name", "senza nome") if isinstance(server, dict) else "senza nome"
        return CheckResult("handshake", "risponde all'handshake", Outcome.PASS, str(nome))


async def _check_capabilities(factory: Any, timeout: float) -> CheckResult:
    """§10.2 — dichiara le proprie capability."""
    async with _Session(factory(), timeout) as sessione:
        await sessione.send(_hello())
        benvenuto = await sessione.wait_for(MessageType.SESSION_WELCOME)
        if benvenuto is None:
            return CheckResult(
                "capabilities", "dichiara le capability", Outcome.SKIP, "handshake non riuscito"
            )

        dichiarate = benvenuto.payload.get("capabilities")
        if not isinstance(dichiarate, list):
            return CheckResult(
                "capabilities",
                "dichiara le capability",
                Outcome.FAIL,
                "campo 'capabilities' assente o non una lista",
            )
        return CheckResult(
            "capabilities",
            "dichiara le capability",
            Outcome.PASS,
            f"{len(dichiarate)} dichiarate",
        )


async def _check_heartbeat(factory: Any, timeout: float) -> CheckResult:
    """§10.3 — risponde a ``link.ping`` con un ``link.pong`` correlato."""
    async with _Session(factory(), timeout) as sessione:
        await sessione.send(_hello())
        await sessione.wait_for(MessageType.SESSION_WELCOME)

        ping = Envelope.make(MessageType.PING)
        await sessione.send(ping)

        pong = await sessione.wait_for(MessageType.PONG)
        if pong is None:
            return CheckResult("heartbeat", "risponde al ping", Outcome.FAIL, "nessun pong")
        if pong.corr != ping.id:
            return CheckResult(
                "heartbeat",
                "risponde al ping",
                Outcome.FAIL,
                "pong non correlato: senza 'c' la latenza non è misurabile",
            )
        return CheckResult("heartbeat", "risponde al ping", Outcome.PASS)


async def _check_unknown_message(factory: Any, timeout: float) -> CheckResult:
    """§10.4 — non chiude il canale davanti a un tipo sconosciuto."""
    async with _Session(factory(), timeout) as sessione:
        await sessione.send(_hello())
        await sessione.wait_for(MessageType.SESSION_WELCOME)

        await sessione.send(Envelope.make("funzione.che.non.esiste", {"x": 1}))
        await asyncio.sleep(0.2)

        # Il canale deve reggere: si verifica che risponda ancora.
        ping = Envelope.make(MessageType.PING)
        await sessione.send(ping)
        if await sessione.wait_for(MessageType.PONG, timeout=timeout) is None:
            return CheckResult(
                "unknown",
                "tollera i messaggi sconosciuti",
                Outcome.FAIL,
                "il canale ha smesso di rispondere dopo un tipo ignoto",
            )
        return CheckResult("unknown", "tollera i messaggi sconosciuti", Outcome.PASS)


async def _check_malformed_message(factory: Any, timeout: float) -> CheckResult:
    """Estensione di §10.4 — regge anche un payload della forma sbagliata.

    Non è nei sei punti, ma è il caso che si verifica davvero: un tipo noto con
    un payload rotto è molto più frequente di un tipo inventato.
    """
    async with _Session(factory(), timeout) as sessione:
        await sessione.send(_hello())
        await sessione.wait_for(MessageType.SESSION_WELCOME)

        await sessione.send(Envelope.make(MessageType.CHAT_SEND, {"__rotto__": True}))
        await asyncio.sleep(0.2)

        ping = Envelope.make(MessageType.PING)
        await sessione.send(ping)
        if await sessione.wait_for(MessageType.PONG, timeout=timeout) is None:
            return CheckResult(
                "malformed",
                "tollera i payload malformati",
                Outcome.FAIL,
                "il canale ha smesso di rispondere dopo un payload non conforme",
            )
        return CheckResult("malformed", "tollera i payload malformati", Outcome.PASS)


async def _check_extension_space(factory: Any, timeout: float) -> CheckResult:
    """§10.6 — non usa il prefisso ``ext.`` per i messaggi del core."""
    async with _Session(factory(), timeout) as sessione:
        await sessione.send(_hello())
        await sessione.wait_for(MessageType.SESSION_WELCOME)
        await asyncio.sleep(0.4)

        benvenuto = next(
            (b for b in sessione.received if b.type == MessageType.SESSION_WELCOME), None
        )
        dichiarate = set()
        if benvenuto is not None:
            grezze = benvenuto.payload.get("capabilities")
            if isinstance(grezze, list):
                dichiarate = {str(c) for c in grezze}

        non_negoziate = [
            b.type
            for b in sessione.received
            if b.type.startswith("ext.") and b.type not in dichiarate
        ]
        if non_negoziate:
            return CheckResult(
                "extensions",
                "usa lo spazio ext. correttamente",
                Outcome.FAIL,
                f"estensioni inviate ma non dichiarate: {', '.join(sorted(set(non_negoziate)))}",
            )
        return CheckResult("extensions", "usa lo spazio ext. correttamente", Outcome.PASS)
