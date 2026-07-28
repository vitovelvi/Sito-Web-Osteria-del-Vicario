"""Catalogo dei messaggi JCP e schemi dei payload.

I tipi sono costanti stringa e non un ``Enum``: un tipo sconosciuto in arrivo va
**ignorato**, non convertito. Un ``Enum`` inviterebbe a convertire subito, e la
conversione fallirebbe proprio nel caso che si vuole tollerare.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from jarvis_protocol.missions import OPERATIONS_SCHEMAS

__all__ = [
    "EXT_PREFIX",
    "AgentStatePayload",
    "ChatDeltaPayload",
    "ChatDonePayload",
    "ChatSendPayload",
    "ErrorPayload",
    "MessageType",
    "SessionDeniedPayload",
    "SessionHelloPayload",
    "SessionWelcomePayload",
    "StreamClosePayload",
    "StreamDataPayload",
    "StreamOpenPayload",
    "TaskUpdatePayload",
    "is_extension",
    "parse_payload",
]

#: Prefisso riservato alle estensioni. Il core non lo userà mai.
EXT_PREFIX: Final[str] = "ext."


class MessageType:
    """Tipi definiti da JCP 1.0."""

    # --- sessione e canale ---
    SESSION_HELLO: Final = "session.hello"
    SESSION_WELCOME: Final = "session.welcome"
    SESSION_DENIED: Final = "session.denied"
    SESSION_CLOSE: Final = "session.close"
    PING: Final = "link.ping"
    PONG: Final = "link.pong"

    # --- assistente e conversazione ---
    AGENT_STATE: Final = "agent.state"
    CHAT_SEND: Final = "chat.send"
    CHAT_DELTA: Final = "chat.delta"
    CHAT_DONE: Final = "chat.done"
    CHAT_CANCEL: Final = "chat.cancel"
    VOICE_START: Final = "voice.start"
    VOICE_STOP: Final = "voice.stop"

    # --- stream: un solo meccanismo per audio, video e file ---
    STREAM_OPEN: Final = "stream.open"
    STREAM_DATA: Final = "stream.data"
    STREAM_CLOSE: Final = "stream.close"

    # --- accessori ---
    TASK_UPDATE: Final = "task.update"
    TELEMETRY_SYSTEM: Final = "telemetry.system"
    ERROR: Final = "error"


def is_extension(message_type: str) -> bool:
    """Indica se un tipo appartiene allo spazio delle estensioni."""
    return message_type.startswith(EXT_PREFIX)


class _Payload(BaseModel):
    """Base dei payload: tollerante in ingresso, immutabile in uscita.

    ``extra="ignore"`` è una scelta di compatibilità: un backend più recente che
    aggiunge un campo non deve rompere una GUI più vecchia.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)


# --------------------------------------------------------------------------- #
# Sessione
# --------------------------------------------------------------------------- #


class ProtocolField(_Payload):
    major: int
    minor: int = 0


class ClientInfo(_Payload):
    name: str = "jarvis-desktop"
    version: str
    instance_id: str
    device: str = ""
    platform: str = ""
    locale: str = "it"


class AuthField(_Payload):
    scheme: str = "none"
    token: str | None = None


class SessionHelloPayload(_Payload):
    """Presentazione del client."""

    protocol: ProtocolField
    client: ClientInfo
    capabilities: list[str] = Field(default_factory=list)
    auth: AuthField = AuthField()


class ServerInfo(_Payload):
    name: str = "backend"
    version: str | None = None
    assistant_name: str = "J.A.R.V.I.S."
    model: str | None = None
    persona: str | None = None
    accent_color: str | None = None
    instance_id: str | None = None


class SessionLimits(_Payload):
    """Limiti dichiarati dal backend.

    Esistono perché la GUI possa rifiutare **prima dell'invio** ciò che il
    backend rifiuterebbe dopo: un allegato troppo grande va segnalato subito,
    non dopo trenta secondi di trasferimento.
    """

    max_message_bytes: int = 8 * 1024 * 1024
    max_stream_chunk_bytes: int = 64 * 1024


class SessionWelcomePayload(_Payload):
    """Risposta del backend all'handshake."""

    protocol: ProtocolField
    server: ServerInfo = ServerInfo()
    capabilities: list[str] = Field(default_factory=list)
    session_id: str | None = None
    limits: SessionLimits = SessionLimits()


class SessionDeniedPayload(_Payload):
    """Handshake rifiutato."""

    code: str = "auth.denied"
    message: str = ""
    retryable: bool = False


class SessionClosePayload(_Payload):
    code: str = "closed"
    message: str = ""


# --------------------------------------------------------------------------- #
# Conversazione
# --------------------------------------------------------------------------- #


class AgentStatePayload(_Payload):
    state: str
    reason: str | None = None


class ChatSendPayload(_Payload):
    text: str
    message_id: str
    attachments: list[str] = Field(default_factory=list)


class ChatDeltaPayload(_Payload):
    text: str
    message_id: str


class ChatDonePayload(_Payload):
    message_id: str
    reason: str | None = None


class ChatCancelPayload(_Payload):
    message_id: str | None = None


# --------------------------------------------------------------------------- #
# Stream
# --------------------------------------------------------------------------- #


class StreamOpenPayload(_Payload):
    """Apertura di un flusso continuo.

    ``kind`` distingue audio, video e file: un unico meccanismo invece di tre
    famiglie di messaggi quasi identiche da mantenere in parallelo.
    """

    stream_id: str
    kind: str = "audio"
    encoding: str = "pcm_s16le"
    sample_rate: int | None = None
    channels: int | None = None
    mime: str | None = None
    filename: str | None = None
    related_id: str | None = None
    """Messaggio che ha generato lo stream: permette di sapere **quale**
    risposta si sta ascoltando."""


class StreamDataPayload(_Payload):
    stream_id: str
    seq: int
    data: str
    """Base64, oppure vuoto quando il blocco viaggia come frame binario."""


class StreamClosePayload(_Payload):
    stream_id: str
    truncated: bool = False


# --------------------------------------------------------------------------- #
# Accessori
# --------------------------------------------------------------------------- #


class TaskUpdatePayload(_Payload):
    task_id: str
    label: str
    status: str = "running"
    progress: float | None = None


class ErrorPayload(_Payload):
    code: str = "internal"
    message: str
    severity: str = "error"
    detail: str | None = None
    retryable: bool = True


#: Schema atteso per ciascun tipo. I tipi assenti non sono errori: sono messaggi
#: che questa build non sa interpretare e che ignora.
_SCHEMAS: Final[dict[str, type[_Payload]]] = {
    MessageType.SESSION_HELLO: SessionHelloPayload,
    MessageType.SESSION_WELCOME: SessionWelcomePayload,
    MessageType.SESSION_DENIED: SessionDeniedPayload,
    MessageType.SESSION_CLOSE: SessionClosePayload,
    MessageType.AGENT_STATE: AgentStatePayload,
    MessageType.CHAT_SEND: ChatSendPayload,
    MessageType.CHAT_DELTA: ChatDeltaPayload,
    MessageType.CHAT_DONE: ChatDonePayload,
    MessageType.CHAT_CANCEL: ChatCancelPayload,
    MessageType.STREAM_OPEN: StreamOpenPayload,
    MessageType.STREAM_DATA: StreamDataPayload,
    MessageType.STREAM_CLOSE: StreamClosePayload,
    MessageType.TASK_UPDATE: TaskUpdatePayload,
    MessageType.ERROR: ErrorPayload,
    # Livello operativo: missioni, azioni, conferme, strumenti.
    **OPERATIONS_SCHEMAS,
}


def parse_payload(message_type: str, payload: dict[str, Any]) -> _Payload | None:
    """Valida il payload contro lo schema del tipo.

    :returns: il modello tipizzato; ``None`` se il tipo è sconosciuto (caso
        legittimo con un backend più recente) oppure se il payload non è
        conforme — in quest'ultimo caso il chiamante logga e scarta, senza
        interrompere il flusso.
    """
    schema = _SCHEMAS.get(message_type)
    if schema is None:
        return None
    try:
        return schema.model_validate(payload)
    except Exception:
        return None
