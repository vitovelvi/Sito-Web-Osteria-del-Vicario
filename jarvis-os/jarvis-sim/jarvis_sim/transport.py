"""Esecutore di scenari: un backend JCP simulato, sul contratto del trasporto.

**La simulazione reagisce.** A differenza del replay, risponde a ciò che il
client fa: se si autorizza una conferma l'azione procede, se la si nega no, se
si annulla un'azione questa si interrompe davvero. È ciò che la rende adatta a
provare l'interfaccia, non solo a guardarla.

Determinismo: tutto il caso deriva da un unico generatore inizializzato con il
seme dello scenario. Stesso seme, stessa sessione — anche le durate simulate.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import random
import struct
from collections.abc import AsyncIterator, Coroutine
from typing import Any

from jarvis_protocol.envelope import Envelope
from jarvis_protocol.errors import ErrorCode, TransportError
from jarvis_protocol.messages import MessageType
from jarvis_protocol.missions import MissionType

from jarvis_sim.scenario import Scenario

__all__ = ["SimTransport", "SimulationError"]

_log = logging.getLogger("jarvis_sim.transport")

_REPLIES: tuple[str, ...] = (
    "Certo. Ho controllato lo stato dei sistemi: tutto nella norma.",
    "Ho trovato tre riferimenti pertinenti. Vuoi che li riassuma?",
    "Procedo. Ti avviso appena l'operazione è completata.",
    "Non ho abbastanza contesto per rispondere con precisione. Puoi specificare?",
)


class SimulationError(TransportError):
    """Guasto simulato del canale.

    Deriva da :class:`~jarvis_protocol.errors.TransportError` perche' un guasto
    simulato deve essere **indistinguibile** da uno reale per chi lo riceve. Se
    fosse un'eccezione a se', il codice di riconnessione non lo catturerebbe e
    la simulazione proverebbe qualcosa di diverso dalla realta' — cioe' non
    proverebbe nulla.
    """


class SimTransport:
    """Backend JCP guidato da uno :class:`~jarvis_sim.scenario.Scenario`."""

    def __init__(self, scenario: Scenario | None = None) -> None:
        from jarvis_sim.library import NOMINAL

        self._scenario = scenario or NOMINAL
        self._rng = random.Random(self._scenario.seed)
        self._outbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()
        self._connected = False
        self._sent = 0
        self._counter = 0
        self._confirms: dict[str, bool] = {}
        self._cancelled: set[str] = set()

    # ------------------------------------------------------------------ #
    # Contratto del trasporto
    # ------------------------------------------------------------------ #

    @property
    def scenario(self) -> Scenario:
        return self._scenario

    @property
    def endpoint(self) -> str:
        return f"sim://{self._scenario.name}"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if self._scenario.channel.fail_connect:
            raise SimulationError(f"Simulazione '{self._scenario.name}': connessione rifiutata")
        self._connected = True
        _log.info("Scenario attivo — %s", self._scenario.describe())
        if self._scenario.channel.drop_after is not None:
            self._spawn(self._drop_later(self._scenario.channel.drop_after))

    async def close(self) -> None:
        self._connected = False
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        await self._outbox.put(None)

    async def send(self, message: dict[str, Any]) -> None:
        if not self._connected:
            raise SimulationError("Canale non aperto")
        try:
            envelope = Envelope.from_wire(message)
        except Exception:
            _log.warning("Messaggio in ingresso non conforme: ignorato")
            return
        self._handle(envelope)

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            messaggio = await self._outbox.get()
            if messaggio is None:
                return
            yield messaggio

    # ------------------------------------------------------------------ #
    # Reazioni
    # ------------------------------------------------------------------ #

    def _handle(self, envelope: Envelope) -> None:
        """Reagisce a un messaggio del client."""
        if envelope.type == MessageType.SESSION_HELLO:
            self._spawn(self._handshake(envelope))
        elif envelope.type == MessageType.PING:
            self._spawn(self._emit(MessageType.PONG, {}, corr=envelope.id))
        elif envelope.type == MessageType.CHAT_SEND:
            self._spawn(self._converse(envelope))
        elif envelope.type == MessageType.VOICE_START:
            self._spawn(self._emit(MessageType.AGENT_STATE, {"state": "listening"}))
        elif envelope.type == MessageType.VOICE_STOP:
            self._spawn(self._emit(MessageType.AGENT_STATE, {"state": "thinking"}))
        elif envelope.type == MessageType.CHAT_CANCEL:
            self._spawn(self._emit(MessageType.AGENT_STATE, {"state": "idle"}))
        elif envelope.type == MissionType.ACTION_CONFIRM_REPLY:
            self._confirms[str(envelope.payload.get("request_id"))] = bool(
                envelope.payload.get("approved")
            )
        elif envelope.type in (MissionType.ACTION_CANCEL, MissionType.MISSION_CANCEL):
            chiave = envelope.payload.get("action_id") or envelope.payload.get("mission_id")
            self._cancelled.add(str(chiave))
        else:
            _log.debug("Messaggio ignorato dalla simulazione: %s", envelope.type)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        """Avvia un compito trattenendone il riferimento.

        Senza il riferimento forte, asyncio può raccogliere il task a metà
        esecuzione: è un modo classico di perdere risposte in modo
        intermittente e apparentemente inspiegabile.
        """
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------------ #
    # Emissione
    # ------------------------------------------------------------------ #

    async def _emit(
        self, type_: str, payload: dict[str, Any] | None = None, corr: str | None = None
    ) -> None:
        if not self._connected:
            return

        canale = self._scenario.channel
        attesa = canale.latency
        if canale.jitter:
            attesa *= 1.0 + self._rng.uniform(-canale.jitter, canale.jitter)
        if attesa > 0:
            await asyncio.sleep(max(0.0, attesa))

        self._sent += 1
        if canale.malformed_every and self._sent % canale.malformed_every == 0:
            # Busta valida, payload della forma sbagliata: verifica che il
            # destinatario scarti invece di propagare.
            await self._outbox.put(Envelope.make(type_, {"__malformato__": True}).to_wire())
            return

        await self._outbox.put(Envelope.make(type_, payload or {}, corr=corr).to_wire())

    async def _handshake(self, request: Envelope) -> None:
        canale = self._scenario.channel
        if canale.refuse_handshake:
            _log.info("Handshake volutamente omesso")
            return

        await asyncio.sleep(canale.handshake_delay)

        if canale.require_auth:
            auth = request.payload.get("auth", {})
            token = auth.get("token") if isinstance(auth, dict) else None
            if token != canale.accepted_token:
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
                "protocol": {"major": canale.protocol_major, "minor": canale.protocol_minor},
                "server": {
                    "name": self._scenario.backend_name,
                    "version": self._scenario.backend_version,
                    "assistant_name": self._scenario.assistant_name,
                    "model": self._scenario.model,
                    "persona": "assistente personale",
                },
                "capabilities": list(self._scenario.capabilities),
                "session_id": f"{self._scenario.name}-{self._scenario.seed}",
                "limits": {"max_message_bytes": 4 * 1024 * 1024},
            },
            corr=request.id,
        )
        await self._emit(MessageType.AGENT_STATE, {"state": "idle"})

        if self._scenario.behaviour.emit_missions and self._scenario.tools:
            await self._emit(
                MissionType.TOOL_REGISTRY,
                {"tools": [t.to_payload() for t in self._scenario.tools]},
            )

        if canale.emit_unknown:
            await self._emit("funzione.del.futuro", {"x": 1})
            await self._emit("ext.acme.telemetria", {"y": 2})

    # ------------------------------------------------------------------ #
    # Conversazione
    # ------------------------------------------------------------------ #

    async def _converse(self, request: Envelope) -> None:
        message_id = str(request.payload.get("message_id", "?"))
        comportamento = self._scenario.behaviour

        await self._emit(MessageType.AGENT_STATE, {"state": "thinking"})
        await asyncio.sleep(0.3)

        if comportamento.emit_missions:
            await self._run_mission(message_id)
        elif self._rng.random() < comportamento.task_probability:
            await self._run_legacy_task()

        risposta = self._rng.choice(_REPLIES)
        await self._emit(MessageType.AGENT_STATE, {"state": "speaking"})

        if comportamento.reply_streaming:
            for parola in risposta.split(" "):
                await asyncio.sleep(0.04)
                await self._emit(
                    MessageType.CHAT_DELTA, {"text": parola + " ", "message_id": message_id}
                )
        else:
            await self._emit(
                MessageType.CHAT_DELTA, {"text": risposta, "message_id": message_id}
            )

        if comportamento.emit_audio:
            await self._stream_audio(risposta, message_id)

        await self._emit(MessageType.CHAT_DONE, {"message_id": message_id})
        await self._emit(MessageType.AGENT_STATE, {"state": "idle"})

    async def _run_mission(self, message_id: str) -> None:
        b = self._scenario.behaviour
        self._counter += 1
        mission_id = f"m-{self._counter}"

        await self._emit(
            MissionType.MISSION_STARTED,
            {
                "mission_id": mission_id,
                "title": "Verifica dello stato dei sistemi",
                "goal": "Raccogliere le informazioni richieste dall'utente",
                "related_message_id": message_id,
            },
        )
        await self._emit(MessageType.AGENT_STATE, {"state": "executing"})

        quante = min(len(self._scenario.plan), self._rng.randint(b.actions_min, b.actions_max))
        piano = self._rng.sample(list(self._scenario.plan), quante)

        for posizione, (tool, titolo, args) in enumerate(piano):
            await self._run_action(mission_id, tool, titolo, args, posizione)

        annullata = mission_id in self._cancelled
        await self._emit(
            MissionType.MISSION_FINISHED,
            {
                "mission_id": mission_id,
                "status": "cancelled" if annullata else "completed",
                "summary": "Interrotta." if annullata else "Informazioni raccolte.",
            },
        )

    async def _run_action(
        self, mission_id: str, tool: str, titolo: str, args: str, posizione: int
    ) -> None:
        b = self._scenario.behaviour
        rischio = next((t.risk for t in self._scenario.tools if t.name == tool), "low")
        self._counter += 1
        action_id = f"a-{self._counter}"

        await self._emit(
            MissionType.ACTION_QUEUED,
            {
                "action_id": action_id,
                "tool": tool,
                "title": titolo,
                "mission_id": mission_id,
                "args_preview": args,
                "risk": rischio,
                "position": posizione,
            },
        )

        chiede_conferma = (
            rischio in ("high", "destructive")
            and self._rng.random() < b.confirm_probability
        )
        if chiede_conferma and not await self._ask_confirmation(action_id, titolo, rischio):
            await self._emit(
                MissionType.ACTION_FINISHED, {"action_id": action_id, "status": "denied"}
            )
            return

        await self._emit(MissionType.ACTION_STARTED, {"action_id": action_id})

        passi = self._rng.randint(b.action_steps_min, b.action_steps_max)
        for passo in range(1, passi + 1):
            await asyncio.sleep(b.step_delay)
            if action_id in self._cancelled or mission_id in self._cancelled:
                await self._emit(
                    MissionType.ACTION_FINISHED, {"action_id": action_id, "status": "cancelled"}
                )
                return
            await self._emit(
                MissionType.ACTION_PROGRESS, {"action_id": action_id, "progress": passo / passi}
            )

        fallita = self._rng.random() < b.failure_rate
        await self._emit(
            MissionType.ACTION_FINISHED,
            {
                "action_id": action_id,
                "status": "error" if fallita else "ok",
                "result_preview": None if fallita else "operazione completata",
                "error": "Risorsa non disponibile" if fallita else None,
                "duration_ms": self._rng.uniform(80, 1400),
            },
        )

    async def _ask_confirmation(self, action_id: str, titolo: str, rischio: str) -> bool:
        """Chiede conferma e **attende davvero** la risposta dell'utente."""
        b = self._scenario.behaviour
        self._counter += 1
        request_id = f"c-{self._counter}"

        await self._emit(
            MissionType.ACTION_CONFIRM_REQUEST,
            {
                "request_id": request_id,
                "action_id": action_id,
                "title": f"Autorizzi: {titolo}?",
                "detail": "L'operazione modifica lo stato della macchina.",
                "risk": rischio,
                "expires_in_s": b.confirm_timeout_s,
            },
        )

        loop = asyncio.get_running_loop()
        scadenza = loop.time() + b.confirm_timeout_s
        while loop.time() < scadenza:
            if request_id in self._confirms:
                return self._confirms.pop(request_id)
            if not self._connected:
                return False
            await asyncio.sleep(0.05)
        return False

    async def _run_legacy_task(self) -> None:
        """Forma semplice ``task.update``, per verificarne la retrocompatibilità."""
        self._counter += 1
        task_id = f"t-{self._counter}"
        etichetta = "Consultazione del calendario"
        await self._emit(
            MessageType.TASK_UPDATE, {"task_id": task_id, "label": etichetta, "progress": 0.0}
        )
        for progresso in (0.5, 1.0):
            await asyncio.sleep(0.15)
            await self._emit(
                MessageType.TASK_UPDATE,
                {
                    "task_id": task_id,
                    "label": etichetta,
                    "progress": progresso,
                    "status": "done" if progresso >= 1.0 else "running",
                },
            )

    # ------------------------------------------------------------------ #
    # Audio
    # ------------------------------------------------------------------ #

    async def _stream_audio(self, testo: str, message_id: str) -> None:
        """Stream PCM sintetico con inviluppo plausibile.

        Non è voce vera, ma sale e scende come farebbe: serve a verificare che
        l'equalizzatore segua l'ampiezza reale invece di muoversi per conto
        proprio. Con un flusso a volume costante quel difetto resterebbe
        invisibile fino al primo collegamento a un backend reale.
        """
        self._counter += 1
        stream_id = f"s-{self._counter}"
        frequenza = 24000
        campioni_per_blocco = frequenza * 60 // 1000
        blocchi = max(4, min(40, len(testo) // 4))

        await self._emit(
            MessageType.STREAM_OPEN,
            {
                "stream_id": stream_id,
                "kind": "audio",
                "encoding": "pcm_s16le",
                "sample_rate": frequenza,
                "channels": 1,
                "related_id": message_id,
            },
        )

        fase = 0.0
        for indice in range(blocchi):
            sillaba = 0.5 + 0.5 * math.sin(indice * 1.7)
            dissolvenza = min(1.0, (blocchi - indice) / 6.0)
            ampiezza = 0.28 * sillaba * dissolvenza

            campioni = bytearray()
            for _ in range(campioni_per_blocco):
                fase += 2 * math.pi * 140.0 / frequenza
                campioni += struct.pack("<h", int(math.sin(fase) * ampiezza * 32767))

            await self._emit(
                MessageType.STREAM_DATA,
                {
                    "stream_id": stream_id,
                    "seq": indice,
                    "data": base64.b64encode(bytes(campioni)).decode("ascii"),
                },
            )

        await self._emit(MessageType.STREAM_CLOSE, {"stream_id": stream_id})

    async def _drop_later(self, delay: float) -> None:
        await asyncio.sleep(delay)
        _log.info("Caduta programmata del canale")
        self._connected = False
        await self._outbox.put(None)
