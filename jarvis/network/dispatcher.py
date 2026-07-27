"""Traduzione dal protocollo agli eventi di dominio.

È l'unico punto dell'applicazione che conosce i tipi di messaggio. Tutto ciò
che sta sopra vede solo eventi del bus e stati: cambiare protocollo significa
riscrivere questo file, non cercare `MessageType` in trenta moduli.

Regola di robustezza: **nessun messaggio in arrivo può interrompere il ciclo**.
Tipo sconosciuto, payload malformato, stato inesistente — tutto viene loggato e
scartato. Un backend più recente o momentaneamente buggato deve poter parlare
senza spegnere l'interfaccia.
"""

from __future__ import annotations

import base64
import binascii
import time
from collections.abc import Callable
from typing import ClassVar

from core.capabilities import CapabilityManager
from core.errors import ErrorCondition, ErrorSeverity
from core.eventbus import EventBus
from core.events import (
    AudioChunk,
    Empty,
    EventType,
    ResponseChunk,
    TaskInfo,
)
from core.identity import IdentityService
from core.logging_setup import LogCategory, get_logger
from core.protocol.envelope import Envelope
from core.protocol.messages import (
    AgentStatePayload,
    AudioChunkPayload,
    AudioEndPayload,
    AudioStartPayload,
    ChatDeltaPayload,
    ErrorPayload,
    MessageType,
    ServerHelloPayload,
    TaskUpdatePayload,
    parse_payload,
)
from core.state.machines import AgentState
from core.state.manager import StateManager

__all__ = ["MessageDispatcher"]

_log = get_logger(LogCategory.PROTOCOL, "dispatcher")

#: Durata di una condizione d'errore segnalata dal backend, in secondi.
_BACKEND_ERROR_TTL = 30.0

#: Gravità dichiarata dal backend → gravità interna.
_SEVERITY = {
    "info": ErrorSeverity.INFO,
    "warning": ErrorSeverity.WARNING,
    "error": ErrorSeverity.ERROR,
    "critical": ErrorSeverity.CRITICAL,
}


class MessageDispatcher:
    """Applica un messaggio in arrivo allo stato e al bus."""

    def __init__(
        self,
        bus: EventBus,
        state: StateManager,
        identity: IdentityService,
        capabilities: CapabilityManager,
    ) -> None:
        self._bus = bus
        self._state = state
        self._identity = identity
        self._capabilities = capabilities
        #: Formato dello stream audio in corso, dichiarato in ``audio.start``.
        self._audio_format: dict[str, tuple[int, int, str]] = {}

    # ------------------------------------------------------------------ #
    # Handshake
    # ------------------------------------------------------------------ #

    def apply_server_hello(self, envelope: Envelope) -> ServerHelloPayload | None:
        """Applica la presentazione del backend.

        :returns: il payload se valido, ``None`` se va rifiutato. Il chiamante
            in quel caso chiude il canale: senza handshake non c'è sessione.
        """
        payload = parse_payload(MessageType.SERVER_HELLO, envelope.payload)
        if not isinstance(payload, ServerHelloPayload):
            _log.error("Presentazione del backend non conforme: handshake rifiutato")
            return None

        if not envelope.is_supported:
            _log.error(
                "Versione di protocollo %d non supportata da questa build", envelope.v
            )
            self._state.raise_error(
                ErrorCondition(
                    source="protocol",
                    message=f"Versione di protocollo {envelope.v} non supportata",
                    detail="Aggiornare l'interfaccia oppure il backend.",
                    severity=ErrorSeverity.CRITICAL,
                )
            )
            return None

        self._identity.apply_server_hello(payload)
        self._capabilities.apply(
            payload.capabilities, protocol_version=payload.protocol_version
        )
        self._bus.publish(
            EventType.HANDSHAKE_COMPLETED, self._identity.backend, source="network"
        )
        self._state.clear_error("protocol")
        return payload

    # ------------------------------------------------------------------ #
    # Messaggi di sessione
    # ------------------------------------------------------------------ #

    def dispatch(self, envelope: Envelope) -> None:
        """Applica un messaggio. Non solleva mai."""
        try:
            handler = self._handlers.get(envelope.type)
            if handler is None:
                # Non è un errore: un backend più recente ha il diritto di
                # inviare messaggi che questa versione non sa interpretare.
                _log.debug("Messaggio ignorato: %s", envelope.type)
                return
            handler(self, envelope)
        except Exception:
            _log.exception("Messaggio '%s' non applicato", envelope.type)

    # -- singoli gestori --------------------------------------------------- #

    def _on_agent_state(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.AGENT_STATE, envelope.payload)
        if not isinstance(payload, AgentStatePayload):
            _log.warning("Stato dell'assistente non conforme: scartato")
            return
        try:
            target = AgentState(payload.state)
        except ValueError:
            _log.warning("Stato dell'assistente sconosciuto: '%s'", payload.state)
            return
        # Autorevole: viene dal backend, che è la fonte di verità.
        self._state.set_agent_state(target, authoritative=True, reason=payload.reason)

    def _on_chat_delta(self, envelope: Envelope) -> None:
        payload = parse_payload(envelope.type, envelope.payload)
        if not isinstance(payload, ChatDeltaPayload):
            _log.warning("Frammento di risposta non conforme: scartato")
            return
        self._bus.publish(
            EventType.AI_RESPONSE,
            ResponseChunk(
                text=payload.text,
                message_id=payload.message_id,
                final=payload.final or envelope.type == MessageType.CHAT_DONE,
            ),
            source="network",
        )

    def _on_task_update(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.TASK_UPDATE, envelope.payload)
        if not isinstance(payload, TaskUpdatePayload):
            return

        info = TaskInfo(
            task_id=payload.task_id,
            label=payload.label,
            progress=payload.progress,
            status=payload.status,
        )
        if payload.status in ("done", "failed", "cancelled"):
            event = EventType.TASK_FINISHED
        elif payload.progress in (None, 0.0):
            event = EventType.TASK_STARTED
        else:
            event = EventType.TASK_PROGRESS
        self._bus.publish(event, info, source="network")

    def _on_audio_start(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.AUDIO_START, envelope.payload)
        if not isinstance(payload, AudioStartPayload):
            return
        self._audio_format[payload.stream_id] = (
            payload.sample_rate,
            payload.channels,
            payload.encoding,
        )
        self._bus.publish(EventType.AUDIO_PLAYING, Empty(), source="network")

    def _on_audio_chunk(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.AUDIO_CHUNK, envelope.payload)
        if not isinstance(payload, AudioChunkPayload):
            return

        try:
            pcm = base64.b64decode(payload.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            _log.warning("Blocco audio non decodificabile (%s): scartato", exc)
            return

        rate, channels, encoding = self._audio_format.get(
            payload.stream_id, (24000, 1, "pcm_s16le")
        )
        self._bus.publish(
            EventType.AUDIO_STREAM_CHUNK,
            AudioChunk(
                stream_id=payload.stream_id,
                sequence=payload.sequence,
                pcm=pcm,
                sample_rate=rate,
                channels=channels,
                encoding=encoding,
            ),
            source="network",
        )

    def _on_audio_end(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.AUDIO_END, envelope.payload)
        if isinstance(payload, AudioEndPayload):
            self._audio_format.pop(payload.stream_id, None)
        self._bus.publish(EventType.AUDIO_FINISHED, Empty(), source="network")

    def _on_error(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.ERROR, envelope.payload)
        if not isinstance(payload, ErrorPayload):
            return

        severity = _SEVERITY.get(payload.severity, ErrorSeverity.ERROR)
        # Il protocollo non prevede un messaggio "errore risolto": senza scadenza
        # una condizione resterebbe in HUD per sempre. Le condizioni critiche
        # fanno eccezione — vanno risolte esplicitamente, non dimenticate.
        ttl = None if severity >= ErrorSeverity.CRITICAL else _BACKEND_ERROR_TTL

        self._state.raise_error(
            ErrorCondition(
                source=f"backend.{payload.code}",
                message=payload.message,
                detail=payload.detail,
                severity=severity,
                expires_at=None if ttl is None else time.monotonic() + ttl,
            )
        )

    #: Tabella dei gestori. Dichiarativa per la stessa ragione delle tabelle di
    #: transizione: si legge in dieci secondi e si estende con una riga.
    _handlers: ClassVar[dict[str, Callable[[MessageDispatcher, Envelope], None]]] = {
        MessageType.AGENT_STATE: _on_agent_state,
        MessageType.CHAT_DELTA: _on_chat_delta,
        MessageType.CHAT_DONE: _on_chat_delta,
        MessageType.TASK_UPDATE: _on_task_update,
        MessageType.AUDIO_START: _on_audio_start,
        MessageType.AUDIO_CHUNK: _on_audio_chunk,
        MessageType.AUDIO_END: _on_audio_end,
        MessageType.ERROR: _on_error,
    }
