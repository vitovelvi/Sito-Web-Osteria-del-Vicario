"""Vocabolario delle capability JCP."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["CLIENT_CAPABILITIES", "Capability"]


class Capability(StrEnum):
    """Capability definite da JCP 1.0.

    Le stringhe non presenti qui non sono un errore: vengono conservate come
    "sconosciute" dal :class:`~core.capabilities.CapabilityManager`, perché un
    backend più recente ha il diritto di dichiarare cose che questa build non
    sa ancora usare.
    """

    CHAT_STREAM = "chat.stream"
    CHAT_CANCEL = "chat.cancel"
    TTS_STREAM = "tts.stream"
    STT_STREAM = "stt.stream"
    VISION_INGEST = "vision.ingest"
    TASKS = "tasks"
    IDENTITY = "identity"
    SYSTEM_METRICS = "telemetry.system"
    STREAM_BINARY = "stream.binary"
    """Frame binari per ``stream.data``: evita il 33% di sovraccarico del
    base64. Facoltativa e negoziata — chi non la dichiara riceve JSON."""

    AUTH_TOKEN = "auth.token"
    WAKE_WORD = "wake_word"


#: Capability offerte dalla GUI nell'handshake. La negoziazione è bidirezionale:
#: anche il backend deve sapere cosa questa interfaccia sa mostrare, altrimenti
#: invierebbe flussi che nessuno consuma.
CLIENT_CAPABILITIES: frozenset[str] = frozenset(
    {
        Capability.CHAT_STREAM.value,
        Capability.CHAT_CANCEL.value,
        Capability.TTS_STREAM.value,
        Capability.IDENTITY.value,
        Capability.TASKS.value,
        Capability.SYSTEM_METRICS.value,
    }
)
