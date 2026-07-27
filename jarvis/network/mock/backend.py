"""Backend OpenClaw simulato.

Non è un accessorio: senza, la GUI non è sviluppabile né testabile a backend
spento, e non si possono riprodurre in modo deterministico latenza,
disconnessioni a metà risposta, payload malformati o versioni di protocollo
incompatibili. Sono esattamente i casi in cui un'interfaccia si comporta male,
e sono quelli che con un backend reale non si sanno provocare a comando.

Implementa :class:`~network.transport.base.ITransport`, quindi il resto
dell'applicazione non distingue questo oggetto da una connessione vera.
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
from core.logging_setup import LogCategory, get_logger
from core.protocol.capabilities import Capability
from core.protocol.envelope import PROTOCOL_VERSION, Envelope
from core.protocol.messages import MessageType

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

    Ogni campo esiste per riprodurre un caso limite osservato con backend reali.
    """

    handshake_delay: float = 0.4
    """Ritardo prima di ``server.hello``. Alzarlo mostra "Connessione a Jarvis…"
    abbastanza a lungo da poterlo valutare."""

    latency: float = 0.05
    """Ritardo applicato a ogni risposta."""

    capabilities: tuple[str, ...] = (
        Capability.CHAT_STREAM.value,
        Capability.CHAT_CANCEL.value,
        Capability.TTS_STREAM.value,
        Capability.TASKS.value,
        Capability.IDENTITY.value,
    )

    protocol_version: int = PROTOCOL_VERSION
    """Portarlo fuori dalla finestra supportata verifica il rifiuto pulito."""

    refuse_handshake: bool = False
    """Il backend accetta la connessione ma non si presenta mai: verifica il
    timeout dell'handshake, che è diverso dal timeout di connessione."""

    drop_after: float | None = None
    """Secondi dopo i quali il canale cade, anche a metà risposta."""

    fail_connect: bool = False
    """La connessione fallisce: verifica il backoff."""

    malformed_every: int = 0
    """Ogni quanti messaggi inviarne uno non conforme (0 = mai)."""

    emit_audio: bool = True
    """Se generare uno stream audio sintetico dopo ogni risposta."""

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

        Formato JSON e non YAML per non aggiungere una dipendenza a un
        componente di sola diagnostica: le chiavi sono i campi di questa classe.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Scenario '%s' non leggibile (%s): si usa quello di default", path, exc)
            return cls()

        known = {f for f in cls.__slots__ if not f.startswith("_")}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class MockTransport:
    """Backend simulato che parla il dialetto canonico."""

    def __init__(self, scenario: MockScenario | None = None) -> None:
        self._scenario = scenario or MockScenario()
        self._outbox: asyncio.Queue[Envelope | None] = asyncio.Queue()
        self._connected = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._sent_count = 0
        self._audio_stream = 0

    # ------------------------------------------------------------------ #
    # Contratto del trasporto
    # ------------------------------------------------------------------ #

    @property
    def endpoint(self) -> str:
        return "mock://openclaw-simulato"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if self._scenario.fail_connect:
            raise TransportError("Backend simulato: connessione rifiutata (scenario)")
        self._connected = True
        _log.info("Backend simulato connesso (scenario: %s)", self._describe_scenario())

        if self._scenario.drop_after is not None:
            self._spawn(self._drop_later(self._scenario.drop_after))

    async def close(self) -> None:
        self._connected = False
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        await self._outbox.put(None)  # sblocca il ciclo di lettura

    async def send(self, envelope: Envelope) -> None:
        """Riceve una busta dalla GUI e programma la risposta."""
        if not self._connected:
            raise TransportError("Backend simulato: canale non aperto")

        if envelope.type == MessageType.CLIENT_HELLO:
            self._spawn(self._handshake(envelope))
        elif envelope.type == MessageType.PING:
            self._spawn(self._pong(envelope))
        elif envelope.type == MessageType.CHAT_SEND:
            self._spawn(self._converse(envelope))
        elif envelope.type == MessageType.VOICE_START:
            self._spawn(self._emit_state("listening"))
        elif envelope.type == MessageType.VOICE_STOP:
            self._spawn(self._emit_state("thinking"))
        elif envelope.type == MessageType.CHAT_CANCEL:
            self._spawn(self._emit_state("idle"))
        else:
            _log.debug("Messaggio ignorato dal simulatore: %s", envelope.type)

    async def receive(self) -> AsyncIterator[Envelope]:
        while True:
            envelope = await self._outbox.get()
            if envelope is None:
                return
            yield envelope

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

    async def _emit(self, type_: str, payload: dict | None = None, corr: str | None = None) -> None:
        """Accoda un messaggio verso la GUI, applicando la latenza simulata."""
        if not self._connected:
            return
        await asyncio.sleep(self._scenario.latency)

        self._sent_count += 1
        every = self._scenario.malformed_every
        if every and self._sent_count % every == 0:
            # Busta valida ma payload della forma sbagliata: verifica che il
            # dispatcher scarti invece di propagare.
            await self._outbox.put(Envelope(type=type_, payload={"__malformato__": True}))
            return

        await self._outbox.put(Envelope(type=type_, payload=payload or {}, corr=corr))

    async def _handshake(self, request: Envelope) -> None:
        if self._scenario.refuse_handshake:
            _log.info("Backend simulato: handshake volutamente omesso")
            return

        await asyncio.sleep(self._scenario.handshake_delay)
        await self._emit(
            MessageType.SERVER_HELLO,
            {
                "protocol_version": self._scenario.protocol_version,
                "backend_name": "OpenClaw",
                "backend_version": "0.0.0-simulato",
                "assistant_name": "J.A.R.V.I.S.",
                "model": "openclaw-mock",
                "persona": "assistente personale",
                "capabilities": list(self._scenario.capabilities),
                "session_id": f"mock-{self._scenario.seed}",
            },
            corr=request.id,
        )
        await self._emit(MessageType.AGENT_STATE, {"state": "idle"})

    async def _pong(self, request: Envelope) -> None:
        await self._emit(MessageType.PONG, {}, corr=request.id)

    async def _emit_state(self, state: str) -> None:
        await self._emit(MessageType.AGENT_STATE, {"state": state})

    async def _converse(self, request: Envelope) -> None:
        """Simula il ciclo completo: elaborazione, risposta, voce."""
        message_id = str(request.payload.get("message_id", "?"))

        await self._emit_state("thinking")
        await asyncio.sleep(0.35)

        if self._scenario.rng.random() < 0.25:
            task_id = f"t-{self._sent_count}"
            await self._emit_state("executing")
            await self._emit(
                MessageType.TASK_UPDATE,
                {"task_id": task_id, "label": "Consultazione del calendario", "progress": 0.0},
            )
            for progress in (0.4, 0.8, 1.0):
                await asyncio.sleep(0.2)
                await self._emit(
                    MessageType.TASK_UPDATE,
                    {
                        "task_id": task_id,
                        "label": "Consultazione del calendario",
                        "progress": progress,
                        "status": "done" if progress >= 1.0 else "running",
                    },
                )

        reply = self._scenario.rng.choice(_REPLIES)
        await self._emit_state("speaking")

        # Streaming parola per parola: è il comportamento che rende la chat
        # viva, ed è anche quello che mette in luce i difetti di scorrimento.
        for word in reply.split(" "):
            await asyncio.sleep(0.045)
            await self._emit(
                MessageType.CHAT_DELTA, {"text": word + " ", "message_id": message_id}
            )

        if self._scenario.emit_audio:
            await self._stream_audio(reply, message_id)

        await self._emit(
            MessageType.CHAT_DONE, {"text": "", "message_id": message_id, "final": True}
        )
        await self._emit_state("idle")

    async def _stream_audio(self, text: str, message_id: str) -> None:
        """Genera uno stream PCM sintetico con ampiezza variabile.

        Non è voce vera, ma ha un **inviluppo plausibile**: serve a verificare
        che l'equalizzatore del nucleo segua l'ampiezza reale invece di
        muoversi per conto proprio. Con un flusso a volume costante quel difetto
        resterebbe invisibile fino al primo collegamento al backend reale.
        """
        self._audio_stream += 1
        stream_id = f"a-{self._audio_stream}"
        sample_rate = 24000
        chunk_ms = 60
        samples_per_chunk = sample_rate * chunk_ms // 1000
        chunks = max(4, min(60, len(text) // 3))

        await self._emit(
            MessageType.AUDIO_START,
            {
                "stream_id": stream_id,
                "sample_rate": sample_rate,
                "channels": 1,
                "encoding": "pcm_s16le",
                "message_id": message_id,
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
                MessageType.AUDIO_CHUNK,
                {
                    "stream_id": stream_id,
                    "sequence": index,
                    "data": base64.b64encode(bytes(samples)).decode("ascii"),
                },
            )

        await self._emit(MessageType.AUDIO_END, {"stream_id": stream_id})

    async def _drop_later(self, delay: float) -> None:
        """Fa cadere il canale dopo un tempo dato."""
        await asyncio.sleep(delay)
        _log.info("Backend simulato: caduta programmata del canale")
        self._connected = False
        await self._outbox.put(None)

    def _describe_scenario(self) -> str:
        parts = [f"latenza {self._scenario.latency * 1000:.0f} ms"]
        if self._scenario.drop_after:
            parts.append(f"caduta a {self._scenario.drop_after:.0f}s")
        if self._scenario.refuse_handshake:
            parts.append("handshake omesso")
        if self._scenario.malformed_every:
            parts.append(f"1 messaggio su {self._scenario.malformed_every} malformato")
        return ", ".join(parts)
