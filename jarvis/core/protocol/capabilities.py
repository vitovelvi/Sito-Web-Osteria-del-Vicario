"""Vocabolario delle capability negoziate nell'handshake.

Una capability e' una funzione che il backend **dichiara di saper fare**. La GUI
non la deduce e non la presume: se OpenClaw non dichiara ``vision.ingest``, il
pulsante per inviare i frame non esiste — non esiste e fallisce.

E' il meccanismo che rende l'interfaccia utilizzabile negli anni: una GUI nuova
davanti a un backend vecchio **degrada**, invece di mostrare funzioni morte;
una GUI vecchia davanti a un backend nuovo ignora cio' che non conosce.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["CLIENT_CAPABILITIES", "Capability"]


class Capability(str, Enum):
    """Capability note a questa versione della GUI.

    Le stringhe non presenti qui non sono un errore: vengono conservate come
    "sconosciute" dal :class:`~core.capabilities.CapabilityManager`, perche' un
    backend piu' recente ha il diritto di dichiarare cose che questa build non
    sa ancora usare.
    """

    CHAT_STREAM = "chat.stream"
    """Risposte in streaming token-per-token."""

    CHAT_CANCEL = "chat.cancel"
    """Interruzione di una risposta in corso."""

    TTS_STREAM = "tts.stream"
    """Il backend sintetizza la voce e ne streamma l'audio (modalita' scelta:
    la GUI riproduce e basta, senza chiavi API)."""

    STT_STREAM = "stt.stream"
    """Il backend accetta audio in ingresso per la trascrizione."""

    VISION_INGEST = "vision.ingest"
    """Il backend accetta frame video."""

    TASKS = "tasks"
    """Il backend emette eventi di avanzamento delle azioni in corso."""

    IDENTITY = "identity"
    """Il backend dichiara nome, modello e persona (vedi core.identity)."""

    SYSTEM_METRICS = "system.metrics"
    """Il backend puo' ricevere le metriche della macchina locale."""

    WAKE_WORD = "wake_word"
    """Il backend gestisce l'attivazione vocale."""


#: Capability offerte dalla GUI al backend nell'handshake. La negoziazione e'
#: bidirezionale: il backend deve sapere cosa questa interfaccia sa mostrare,
#: altrimenti invierebbe flussi che nessuno consuma.
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
