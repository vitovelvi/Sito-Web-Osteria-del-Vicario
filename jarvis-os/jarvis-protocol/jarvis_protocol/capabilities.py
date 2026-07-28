"""Vocabolario delle capability JCP."""

from __future__ import annotations

from enum import StrEnum

__all__ = ["CLIENT_CAPABILITIES", "Capability"]


class Capability(StrEnum):
    """Capability definite da JCP 1.0.

    Le stringhe non presenti qui non sono un errore: vengono conservate come
    "sconosciute" dal gestore delle capability del client, perché un
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

    # --- livello operativo ---
    MISSIONS = "missions"
    """Il backend dichiara missioni e sotto-missioni."""

    ACTIONS = "actions"
    """Il backend dichiara le singole azioni e i loro esiti."""

    ACTIONS_CANCEL = "actions.cancel"
    """Le azioni possono essere annullate dall'interfaccia."""

    ACTIONS_CONFIRM = "actions.confirm"
    """Il backend puo' chiedere conferma prima di eseguire."""

    TOOLS_REGISTRY = "tools.registry"
    """Il backend dichiara il registro degli strumenti."""


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
        # La GUI sa mostrare missioni, azioni e conferme: dichiararlo evita che
        # il backend invii un flusso che nessuno rappresenterebbe.
        Capability.MISSIONS.value,
        Capability.ACTIONS.value,
        Capability.ACTIONS_CANCEL.value,
        Capability.ACTIONS_CONFIRM.value,
        Capability.TOOLS_REGISTRY.value,
    }
)
