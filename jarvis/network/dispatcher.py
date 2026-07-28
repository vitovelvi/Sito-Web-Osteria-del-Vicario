"""Traduzione da JCP agli eventi di dominio.

È l'unico punto dell'applicazione che conosce i tipi di messaggio. Tutto ciò che
sta sopra vede solo eventi del bus e stati.

Regola di robustezza: **nessun messaggio in arrivo può interrompere il ciclo**.
Tipo sconosciuto, payload malformato, stato inesistente, estensione non
negoziata — tutto viene loggato e scartato.
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
from core.jcp.envelope import Envelope
from core.jcp.errors import is_retryable
from core.jcp.messages import (
    AgentStatePayload,
    ChatDeltaPayload,
    ChatDonePayload,
    ErrorPayload,
    MessageType,
    SessionWelcomePayload,
    StreamClosePayload,
    StreamDataPayload,
    StreamOpenPayload,
    TaskUpdatePayload,
    is_extension,
    parse_payload,
)
from core.jcp.version import PROTOCOL_VERSION
from core.logging_setup import LogCategory, get_logger
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


class HandshakeResult:
    """Esito dell'handshake, con il motivo in caso di rifiuto."""

    __slots__ = ("accepted", "payload", "reason", "retryable")

    def __init__(
        self,
        accepted: bool,
        *,
        reason: str = "",
        retryable: bool = True,
        payload: SessionWelcomePayload | None = None,
    ) -> None:
        self.accepted = accepted
        self.reason = reason
        self.retryable = retryable
        self.payload = payload


class MessageDispatcher:
    """Applica un messaggio JCP in arrivo allo stato e al bus."""

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
        #: Formato degli stream aperti, dichiarato in ``stream.open``.
        self._streams: dict[str, StreamOpenPayload] = {}
        #: Ultima sequenza vista per stream, per rilevare i buchi.
        self._stream_seq: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Handshake
    # ------------------------------------------------------------------ #

    def apply_welcome(self, envelope: Envelope) -> HandshakeResult:
        """Applica ``session.welcome``.

        :returns: esito. Se non accettato, il chiamante chiude il canale;
            ``retryable`` gli dice se ha senso riprovare.
        """
        payload = parse_payload(MessageType.SESSION_WELCOME, envelope.payload)
        if not isinstance(payload, SessionWelcomePayload):
            return HandshakeResult(False, reason="Presentazione del backend non conforme")

        declared = payload.protocol
        if declared.major != PROTOCOL_VERSION.major:
            message = (
                f"Versione di protocollo {declared.major}.{declared.minor} "
                f"incompatibile con JCP {PROTOCOL_VERSION}"
            )
            _log.error("%s", message)
            self._state.raise_error(
                ErrorCondition(
                    source="protocol",
                    message="Versione di protocollo incompatibile",
                    detail=f"{message}. Aggiornare l'interfaccia oppure il backend.",
                    severity=ErrorSeverity.CRITICAL,
                )
            )
            # Insistere non serve: la versione del backend non cambia da sola.
            return HandshakeResult(False, reason=message, retryable=False)

        if declared.minor != PROTOCOL_VERSION.minor:
            # Differenza additiva: si prosegue. È il caso che rende possibile
            # aggiornare GUI e backend in momenti diversi.
            _log.info(
                "Minor di protocollo diverso (backend %d.%d, GUI %s): sessione accettata",
                declared.major,
                declared.minor,
                PROTOCOL_VERSION,
            )

        self._identity.apply_welcome(payload)
        self._capabilities.apply(
            payload.capabilities,
            protocol_version=f"{declared.major}.{declared.minor}",
        )
        self._bus.publish(
            EventType.HANDSHAKE_COMPLETED, self._identity.backend, source="network"
        )
        self._state.clear_error("protocol")
        return HandshakeResult(True, payload=payload)

    def apply_denied(self, envelope: Envelope) -> HandshakeResult:
        """Applica ``session.denied``."""
        payload = parse_payload(MessageType.SESSION_DENIED, envelope.payload)
        code = payload.code if payload else "auth.denied"  # type: ignore[union-attr]
        message = payload.message if payload else "Connessione rifiutata"  # type: ignore[union-attr]
        retryable = payload.retryable if payload else False  # type: ignore[union-attr]

        _log.error("Handshake rifiutato dal backend [%s]: %s", code, message)
        self._state.raise_error(
            ErrorCondition(
                source="protocol",
                message=message or "Connessione rifiutata",
                detail=f"Codice: {code}",
                severity=ErrorSeverity.CRITICAL,
            )
        )
        return HandshakeResult(
            False, reason=message, retryable=retryable and is_retryable(code)
        )

    # ------------------------------------------------------------------ #
    # Messaggi di sessione
    # ------------------------------------------------------------------ #

    def dispatch(self, envelope: Envelope) -> None:
        """Applica un messaggio. Non solleva mai."""
        try:
            if is_extension(envelope.type):
                self._on_extension(envelope)
                return

            handler = self._handlers.get(envelope.type)
            if handler is None:
                # Non è un errore: un backend più recente ha il diritto di
                # inviare messaggi che questa versione non sa interpretare.
                _log.debug("Messaggio ignorato: %s", envelope.type)
                return
            handler(self, envelope)
        except Exception:
            _log.exception("Messaggio '%s' non applicato", envelope.type)

    def reset(self) -> None:
        """Azzera lo stato degli stream alla caduta della sessione."""
        self._streams.clear()
        self._stream_seq.clear()

    # -- gestori ----------------------------------------------------------- #

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
        payload = parse_payload(MessageType.CHAT_DELTA, envelope.payload)
        if not isinstance(payload, ChatDeltaPayload):
            _log.warning("Frammento di risposta non conforme: scartato")
            return
        self._bus.publish(
            EventType.AI_RESPONSE,
            ResponseChunk(text=payload.text, message_id=payload.message_id, final=False),
            source="network",
        )

    def _on_chat_done(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.CHAT_DONE, envelope.payload)
        if not isinstance(payload, ChatDonePayload):
            return
        self._bus.publish(
            EventType.AI_RESPONSE,
            ResponseChunk(text="", message_id=payload.message_id, final=True),
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

    # -- stream ------------------------------------------------------------ #

    def _on_stream_open(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.STREAM_OPEN, envelope.payload)
        if not isinstance(payload, StreamOpenPayload):
            return

        self._streams[payload.stream_id] = payload
        self._stream_seq.pop(payload.stream_id, None)

        if payload.kind == "audio":
            self._bus.publish(EventType.AUDIO_PLAYING, Empty(), source="network")
        else:
            # Video e file avranno consumatori propri nelle fasi successive; il
            # protocollo li supporta già e non andrà toccato.
            _log.debug("Stream '%s' di tipo '%s' aperto", payload.stream_id, payload.kind)

    def _on_stream_data(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.STREAM_DATA, envelope.payload)
        if not isinstance(payload, StreamDataPayload):
            return

        info = self._streams.get(payload.stream_id)
        if info is None:
            # Un blocco senza apertura è un errore del mittente. Si scarta: senza
            # il formato dichiarato non si saprebbe come interpretarlo.
            _log.warning("Blocco per lo stream '%s' mai aperto: scartato", payload.stream_id)
            return

        expected = self._stream_seq.get(payload.stream_id, -1) + 1
        if payload.seq != expected and expected > 0:
            # Un buco nella sequenza è rilevabile e va detto: nell'audio si
            # sente come uno scatto, e senza questo avviso si finirebbe a
            # cercare il difetto nel riproduttore invece che nel canale.
            _log.warning(
                "Stream '%s': attesa sequenza %d, ricevuta %d",
                payload.stream_id,
                expected,
                payload.seq,
            )
        self._stream_seq[payload.stream_id] = payload.seq

        if info.kind != "audio":
            return

        try:
            pcm = base64.b64decode(payload.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            _log.warning("Blocco audio non decodificabile (%s): scartato", exc)
            return

        self._bus.publish(
            EventType.AUDIO_STREAM_CHUNK,
            AudioChunk(
                stream_id=payload.stream_id,
                sequence=payload.seq,
                pcm=pcm,
                sample_rate=info.sample_rate or 24000,
                channels=info.channels or 1,
                encoding=info.encoding,
            ),
            source="network",
        )

    def _on_stream_close(self, envelope: Envelope) -> None:
        payload = parse_payload(MessageType.STREAM_CLOSE, envelope.payload)
        if not isinstance(payload, StreamClosePayload):
            return

        info = self._streams.pop(payload.stream_id, None)
        self._stream_seq.pop(payload.stream_id, None)
        if info is not None and info.kind == "audio":
            self._bus.publish(EventType.AUDIO_FINISHED, Empty(), source="network")

    # -- errori ed estensioni ---------------------------------------------- #

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

    def _on_extension(self, envelope: Envelope) -> None:
        """Inoltra un messaggio ``ext.*`` ai plugin.

        Il core non interpreta le estensioni: le ripubblica nello spazio dei
        plugin. È il meccanismo che permette di estendere il protocollo senza
        toccare il core — cioè il punto dell'intera sezione §6 della specifica.
        """
        name = envelope.type[len("ext.") :]
        if not self._capabilities.has(envelope.type):
            # Usare un'estensione non negoziata è un errore del mittente. Si
            # logga e si prosegue: il canale resta valido.
            _log.warning("Estensione '%s' non negoziata: ignorata", envelope.type)
            return
        self._bus.publish(f"plugin.{name}", envelope.payload, source="network")

    _handlers: ClassVar[dict[str, Callable[[MessageDispatcher, Envelope], None]]] = {
        MessageType.AGENT_STATE: _on_agent_state,
        MessageType.CHAT_DELTA: _on_chat_delta,
        MessageType.CHAT_DONE: _on_chat_done,
        MessageType.TASK_UPDATE: _on_task_update,
        MessageType.STREAM_OPEN: _on_stream_open,
        MessageType.STREAM_DATA: _on_stream_data,
        MessageType.STREAM_CLOSE: _on_stream_close,
        MessageType.ERROR: _on_error,
    }
