"""Tipi di messaggio e schemi dei payload.

Il dialetto qui definito e' quello **canonico interno**. Se il protocollo reale
di OpenClaw differisce — probabile — la traduzione avviene in
``network/adapters/openclaw.py`` e nient'altro nell'applicazione se ne accorge.
E' la ragione per cui questo file esiste separato dal trasporto.
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AgentStatePayload",
    "AudioChunkPayload",
    "ChatDeltaPayload",
    "ChatSendPayload",
    "ClientHelloPayload",
    "ErrorPayload",
    "MessageType",
    "ServerHelloPayload",
    "TaskUpdatePayload",
    "parse_payload",
]


class MessageType:
    """Tipi di messaggio del protocollo.

    Sono costanti stringa e non un ``Enum`` deliberatamente: un tipo
    sconosciuto in arrivo va **ignorato**, non deve sollevare. Un ``Enum``
    inviterebbe a convertire subito, e la conversione fallirebbe proprio nel
    caso che si vuole tollerare.
    """

    # --- GUI → backend ---
    CLIENT_HELLO: Final = "client.hello"
    CHAT_SEND: Final = "chat.send"
    CHAT_CANCEL: Final = "chat.cancel"
    VOICE_START: Final = "voice.start"
    VOICE_STOP: Final = "voice.stop"
    AUDIO_INPUT: Final = "audio.input"
    VISION_FRAME: Final = "vision.frame"
    SYSTEM_METRICS: Final = "system.metrics"
    PING: Final = "ping"

    # --- backend → GUI ---
    SERVER_HELLO: Final = "server.hello"
    AGENT_STATE: Final = "agent.state"
    CHAT_DELTA: Final = "chat.delta"
    CHAT_DONE: Final = "chat.done"
    AUDIO_START: Final = "audio.start"
    AUDIO_CHUNK: Final = "audio.chunk"
    AUDIO_END: Final = "audio.end"
    TASK_UPDATE: Final = "task.update"
    IDENTITY: Final = "identity"
    ERROR: Final = "error"
    PONG: Final = "pong"


class _Payload(BaseModel):
    """Base dei payload: tollerante in ingresso, immutabile in uscita.

    ``extra="ignore"`` e' una scelta di compatibilita': un backend piu' recente
    che aggiunge un campo non deve rompere una GUI piu' vecchia.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)


# --------------------------------------------------------------------------- #
# Handshake
# --------------------------------------------------------------------------- #


class ClientHelloPayload(_Payload):
    """Presentazione della GUI. Primo messaggio dopo l'apertura del canale."""

    protocol_version: int
    client_name: str = "jarvis-desktop"
    client_version: str
    instance_id: str
    device_name: str
    platform: str
    capabilities: list[str] = Field(default_factory=list)
    locale: str = "it"


class ServerHelloPayload(_Payload):
    """Risposta di OpenClaw: identita' e capability effettivamente disponibili."""

    protocol_version: int
    backend_name: str = "OpenClaw"
    backend_version: str | None = None
    assistant_name: str = "J.A.R.V.I.S."
    model: str | None = None
    persona: str | None = None
    accent_color: str | None = None
    instance_id: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    session_id: str | None = None


# --------------------------------------------------------------------------- #
# Conversazione
# --------------------------------------------------------------------------- #


class ChatSendPayload(_Payload):
    """Messaggio dell'utente verso il backend."""

    text: str
    message_id: str
    attachments: list[str] = Field(default_factory=list)


class ChatDeltaPayload(_Payload):
    """Frammento di risposta in streaming."""

    text: str
    message_id: str
    final: bool = False


class AgentStatePayload(_Payload):
    """Stato autorevole dell'assistente, deciso dal backend."""

    state: str
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #


class AudioStartPayload(_Payload):
    """Inizio di uno stream vocale sintetizzato dal backend."""

    stream_id: str
    sample_rate: int = 24000
    channels: int = 1
    encoding: str = "pcm_s16le"
    message_id: str | None = None


class AudioChunkPayload(_Payload):
    """Blocco audio.

    ``data`` e' base64: il protocollo e' testuale per semplicita' di debug. Se
    il volume di traffico lo richiedera', il trasporto potra' passare ai frame
    binari di WebSocket senza cambiare questo schema — l'envelope resta uguale
    e cambia solo la codifica del campo.
    """

    stream_id: str
    sequence: int
    data: str


class AudioEndPayload(_Payload):
    """Fine di uno stream vocale."""

    stream_id: str
    truncated: bool = False


# --------------------------------------------------------------------------- #
# Task ed errori
# --------------------------------------------------------------------------- #


class TaskUpdatePayload(_Payload):
    """Avanzamento di un'azione in corso lato backend."""

    task_id: str
    label: str
    status: str = "running"
    progress: float | None = None


class ErrorPayload(_Payload):
    """Errore riportato dal backend."""

    code: str = "unknown"
    message: str
    severity: str = "error"
    detail: str | None = None


#: Schema atteso per ciascun tipo. I tipi assenti non sono errori: sono
#: messaggi che questa build non sa interpretare e che ignora.
_SCHEMAS: Final[dict[str, type[_Payload]]] = {
    MessageType.CLIENT_HELLO: ClientHelloPayload,
    MessageType.SERVER_HELLO: ServerHelloPayload,
    MessageType.CHAT_SEND: ChatSendPayload,
    MessageType.CHAT_DELTA: ChatDeltaPayload,
    MessageType.CHAT_DONE: ChatDeltaPayload,
    MessageType.AGENT_STATE: AgentStatePayload,
    MessageType.AUDIO_START: AudioStartPayload,
    MessageType.AUDIO_CHUNK: AudioChunkPayload,
    MessageType.AUDIO_END: AudioEndPayload,
    MessageType.TASK_UPDATE: TaskUpdatePayload,
    MessageType.ERROR: ErrorPayload,
}


def parse_payload(message_type: str, payload: dict[str, Any]) -> _Payload | None:
    """Valida il payload contro lo schema del tipo.

    :returns: il modello tipizzato; ``None`` se il tipo e' sconosciuto (caso
        legittimo con un backend piu' recente) oppure se il payload non e'
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
