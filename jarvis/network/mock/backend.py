"""Backend simulato: riferimento eseguibile di JCP 1.0.

Non è un accessorio. Senza, la GUI non è sviluppabile né testabile a backend
spento, e non si possono riprodurre in modo deterministico i casi in cui
un'interfaccia si comporta male: latenza, handshake omesso, caduta a metà
risposta, payload malformato, versione di protocollo incompatibile,
autenticazione rifiutata. Con un backend reale, quei casi non si sanno
provocare a comando.

Parla JCP nativamente e implementa i sei punti di conformità della specifica
(§10), quindi funziona con :class:`~network.adapters.native.NativeJcpAdapter`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import random
import struct
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.errors import TransportError
from core.jcp.capabilities import Capability
from core.jcp.envelope import Envelope
from core.jcp.errors import ErrorCode
from core.jcp.messages import MessageType
from core.jcp.version import PROTOCOL_VERSION
from core.logging_setup import LogCategory, get_logger

__all__ = ["MockScenario", "MockTransport"]

_log = get_logger(LogCategory.NETWORK, "mock")

#: Risposte pronte del backend simulato.
_REPLIES: tuple[str, ...] = (
    "Certo. Ho controllato lo stato dei sistemi: tutto nella norma.",
    "Ho trovato tre riferimenti pertinenti. Vuoi che li riassuma?",
    "Procedo. Ti avviso appena l'operazione è completata.",
    "Non ho abbastanza contesto per rispondere con precisione. Puoi specificare?",
)


@dataclass(slots=True)
class MockScenario:
    """Parametri di simulazione.

    Ogni campo riproduce un caso limite reale.
    """

    handshake_delay: float = 0.4
    """Ritardo prima di ``session.welcome``. Alzarlo mostra "Connessione a
    Jarvis…" abbastanza a lungo da poterlo valutare."""

    latency: float = 0.05
    capabilities: tuple[str, ...] = (
        Capability.CHAT_STREAM.value,
        Capability.CHAT_CANCEL.value,
        Capability.TTS_STREAM.value,
        Capability.TASKS.value,
        Capability.IDENTITY.value,
    )

    protocol_major: int = PROTOCOL_VERSION.major
    protocol_minor: int = PROTOCOL_VERSION.minor
    """Cambiare ``major`` verifica il rifiuto pulito; cambiare ``minor``
    verifica che una differenza additiva **non** interrompa la sessione."""

    require_auth: bool = False
    accepted_token: str = "segreto-di-prova"
    """Con ``require_auth`` attivo, un token diverso produce ``session.denied``."""

    refuse_handshake: bool = False
    """Il backend accetta la connessione ma non si presenta mai: verifica il
    timeout dell'handshake, distinto da quello di connessione."""

    drop_after: float | None = None
    fail_connect: bool = False
    malformed_every: int = 0
    """Ogni quanti messaggi inviarne uno non conforme (0 = mai)."""

    emit_audio: bool = True
    emit_unknown: bool = False
    """Invia anche un messaggio di tipo sconosciuto e un ``ext.*``: verifica che
    la GUI li ignori invece di inciampare."""

    seed: int = 7
    _rng: random.Random | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._rng is None:
            self._rng = random.Random(self.seed)

    @property
    def rng(self) -> random.Random:
        assert self._rng is not None
        return self._rng

    @classmethod
    def from_file(cls, path: Path) -> MockScenario:
        """Carica uno scenario da JSON.

        JSON e non YAML per non aggiungere una dipendenza a un componente di
        sola diagnostica: le chiavi sono i campi di questa classe.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Scenario '%s' non leggibile (%s): si usa il default", path, exc)
            return cls()

        known = {f for f in cls.__slots__ if not f.startswith("_")}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class MockTransport:
    """Backend JCP simulato, sul contratto di :class:`ITransport`."""

    def __init__(self, scenario: MockScenario | None = None) -> None:
        self._scenario = scenario or MockScenario()
        self._outbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._connected = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._sent_count = 0
        self._stream_seq = 0

    # ------------------------------------------------------------------ #
    # Contratto del trasporto
    # ------------------------------------------------------------------ #

    @property
    def endpoint(self) -> str:
        return "mock://jcp-simulato"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if self._scenario.fail_connect:
            raise TransportError("Backend simulato: connessione rifiutata (scenario)")
        self._connected = True
        _log.info("Backend simulato connesso (%s)", self._describe_scenario())
        if self._scenario.drop_after is not None:
            self._spawn(self._drop_later(self._scenario.drop_after))

    async def close(self) -> None:
        self._connected = False
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        await self._outbox.put(None)  # sblocca il ciclo di lettura

    async def send(self, message: dict[str, Any]) -> None:
        """Riceve un messaggio dalla GUI e programma la risposta."""
        if not self._connected:
            raise TransportError("Backend simulato: canale non aperto")

        try:
            envelope = Envelope.from_wire(message)
        except Exception:
            _log.warning("Messaggio in ingresso non conforme: ignorato")
            return

        handlers = {
            MessageType.SESSION_HELLO: self._handshake,
            MessageType.PING: self._pong,
            MessageType.CHAT_SEND: self._converse,
        }
        handler = handlers.get(envelope.type)
        if handler is not None:
            self._spawn(handler(envelope))
        elif envelope.type == MessageType.VOICE_START:
            self._spawn(self._emit_state("listening"))
        elif envelope.type == MessageType.VOICE_STOP:
            self._spawn(self._emit_state("thinking"))
        elif envelope.type == MessageType.CHAT_CANCEL:
            self._spawn(self._emit_state("idle"))
        else:
            _log.debug("Messaggio ignorato dal simulatore: %s", envelope.type)

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            message = await self._outbox.get()
            if message is None:
                return
            yield message

    # ------------------------------------------------------------------ #
    # Simulazione
    # ------------------------------------------------------------------ #

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Avvia un compito trattenendone il riferimento.

        Senza il riferimento forte, asyncio può raccogliere il task a metà
        esecuzione: è un modo classico di perdere risposte in modo
        intermittente e apparentemente inspiegabile.
        """
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _emit(
        self, type_: str, payload: dict[str, Any] | None = None, corr: str | None = None
    ) -> None:
        """Accoda un messaggio verso la GUI, applicando la latenza simulata."""
        if not self._connected:
            return
        await asyncio.sleep(self._scenario.latency)

        self._sent_count += 1
        every = self._scenario.malformed_every
        if every and self._sent_count % every == 0:
            # Busta valida, payload della forma sbagliata: verifica che il
            # dispatcher scarti invece di propagare.
            await self._outbox.put(
                Envelope.make(type_, {"__malformato__": True}).to_wire()
            )
            return

        await self._outbox.put(Envelope.make(type_, payload or {}, corr=corr).to_wire())

    async def _handshake(self, request: Envelope) -> None:
        if self._scenario.refuse_handshake:
            _log.info("Backend simulato: handshake volutamente omesso")
            return

        await asyncio.sleep(self._scenario.handshake_delay)

        if self._scenario.require_auth:
            auth = request.payload.get("auth", {})
            token = auth.get("token") if isinstance(auth, dict) else None
            if token != self._scenario.accepted_token:
                await self._emit(
                    MessageType.SESSION_DENIED,
                    {
                        "code": ErrorCode.AUTH_DENIED.value,
                        "message": "Token non valido",
                        "retryable": False,
                    },
                    corr=request.id,
                )
                self._connected = False
                await self._outbox.put(None)
                return

        await self._emit(
            MessageType.SESSION_WELCOME,
            {
                "protocol": {
                    "major": self._scenario.protocol_major,
                    "minor": self._scenario.protocol_minor,
                },
                "server": {
                    "name": "OpenClaw",
                    "version": "0.0.0-simulato",
                    "assistant_name": "J.A.R.V.I.S.",
                    "model": "jcp-mock",
                    "persona": "assistente personale",
                },
                "capabilities": list(self._scenario.capabilities),
                "session_id": f"mock-{self._scenario.seed}",
                "limits": {"max_message_bytes": 4 * 1024 * 1024},
            },
            corr=request.id,
        )
        await self._emit(MessageType.AGENT_STATE, {"state": "idle"})

        if self._scenario.emit_unknown:
            # Un tipo del futuro e un'estensione non negoziata: entrambi devono
            # essere ignorati senza conseguenze.
            await self._emit("funzione.del.futuro", {"x": 1})
            await self._emit("ext.acme.telemetria", {"y": 2})

    async def _pong(self, request: Envelope) -> None:
        await self._emit(MessageType.PONG, {}, corr=request.id)

    async def _emit_state(self, state: str) -> None:
        await self._emit(MessageType.AGENT_STATE, {"state": state})

    async def _converse(self, request: Envelope) -> None:
        """Ciclo completo: elaborazione, eventuale task, risposta, voce."""
        message_id = str(request.payload.get("message_id", "?"))

        await self._emit_state("thinking")
        await asyncio.sleep(0.35)

        if self._scenario.rng.random() < 0.25:
            await self._run_task()

        reply = self._scenario.rng.choice(_REPLIES)
        await self._emit_state("speaking")

        # Streaming parola per parola: è ciò che rende viva la chat, ed è anche
        # ciò che mette in luce i difetti di scorrimento.
        for word in reply.split(" "):
            await asyncio.sleep(0.045)
            await self._emit(
                MessageType.CHAT_DELTA, {"text": word + " ", "message_id": message_id}
            )

        if self._scenario.emit_audio:
            await self._stream_audio(reply, message_id)

        await self._emit(MessageType.CHAT_DONE, {"message_id": message_id})
        await self._emit_state("idle")

    async def _run_task(self) -> None:
        task_id = f"t-{self._sent_count}"
        label = "Consultazione del calendario"
        await self._emit_state("executing")
        await self._emit(
            MessageType.TASK_UPDATE, {"task_id": task_id, "label": label, "progress": 0.0}
        )
        for progress in (0.4, 0.8, 1.0):
            await asyncio.sleep(0.2)
            await self._emit(
                MessageType.TASK_UPDATE,
                {
                    "task_id": task_id,
                    "label": label,
                    "progress": progress,
                    "status": "done" if progress >= 1.0 else "running",
                },
            )

    async def _stream_audio(self, text: str, message_id: str) -> None:
        """Genera uno stream PCM sintetico con ampiezza variabile.

        Non è voce vera, ma ha un **inviluppo plausibile**: serve a verificare
        che l'equalizzatore del nucleo segua l'ampiezza reale invece di muoversi
        per conto proprio. Con un flusso a volume costante quel difetto
        resterebbe invisibile fino al primo collegamento al backend reale.
        """
        self._stream_seq += 1
        stream_id = f"a-{self._stream_seq}"
        sample_rate = 24000
        samples_per_chunk = sample_rate * 60 // 1000  # blocchi da 60 ms
        chunks = max(4, min(60, len(text) // 3))

        await self._emit(
            MessageType.STREAM_OPEN,
            {
                "stream_id": stream_id,
                "kind": "audio",
                "encoding": "pcm_s16le",
                "sample_rate": sample_rate,
                "channels": 1,
                "related_id": message_id,
            },
        )

        phase = 0.0
        for index in range(chunks):
            # Inviluppo a sillabe più dissolvenza finale: sale e scende come
            # farebbe una voce, invece di restare piatto.
            syllable = 0.5 + 0.5 * math.sin(index * 1.7)
            fade = min(1.0, (chunks - index) / 6.0)
            amplitude = 0.28 * syllable * fade

            samples = bytearray()
            for _ in range(samples_per_chunk):
                phase += 2 * math.pi * 140.0 / sample_rate
                samples += struct.pack("<h", int(math.sin(phase) * amplitude * 32767))

            await self._emit(
                MessageType.STREAM_DATA,
                {
                    "stream_id": stream_id,
                    "seq": index,
                    "data": base64.b64encode(bytes(samples)).decode("ascii"),
                },
            )

        await self._emit(MessageType.STREAM_CLOSE, {"stream_id": stream_id})

    async def _drop_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        _log.info("Backend simulato: caduta programmata del canale")
        self._connected = False
        await self._outbox.put(None)

    def _describe_scenario(self) -> str:
        s = self._scenario
        parts = [f"latenza {s.latency * 1000:.0f} ms"]
        if s.drop_after:
            parts.append(f"caduta a {s.drop_after:.0f}s")
        if s.refuse_handshake:
            parts.append("handshake omesso")
        if s.require_auth:
            parts.append("autenticazione richiesta")
        if s.malformed_every:
            parts.append(f"1 messaggio su {s.malformed_every} malformato")
        if (s.protocol_major, s.protocol_minor) != (
            PROTOCOL_VERSION.major,
            PROTOCOL_VERSION.minor,
        ):
            parts.append(f"protocollo {s.protocol_major}.{s.protocol_minor}")
        return ", ".join(parts)
