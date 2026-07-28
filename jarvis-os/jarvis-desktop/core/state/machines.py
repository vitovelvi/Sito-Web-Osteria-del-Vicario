"""Le tre macchine a stati ortogonali e la modalita' visiva risultante.

Il brief elencava un unico insieme di stati (``BOOTING``, ``CONNECTING``,
``IDLE``, ``LISTENING``, ``THINKING``, ``EXECUTING``, ``SPEAKING``, ``ERROR``,
``STANDBY``). Contiene pero' tre assi indipendenti mescolati, e la conseguenza
non e' estetica ma funzionale: entrare in ``ERROR`` mentre Jarvis parla
**cancella l'informazione che stava parlando**, e all'uscita non si sa dove
tornare. Allo stesso modo la connessione puo' cadere mentre l'assistente e'
legittimamente inattivo: sono due fatti distinti, che l'HUD deve poter mostrare
insieme.

Qui gli assi sono separati:

* :class:`AppState` — ciclo di vita del processo;
* :class:`LinkState` — canale verso OpenClaw;
* :class:`AgentState` — cosa sta facendo l'assistente;

piu' :class:`~core.errors.ErrorCondition` come **condizione sovrapposta**, non
come stato. La combinazione dei tre assi produce una singola
:class:`VisualMode`, che e' l'unica cosa che l'interfaccia consuma.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AgentState", "AppState", "LinkState", "VisualMode"]


class AppState(StrEnum):
    """Ciclo di vita dell'applicazione."""

    BOOTING = "booting"
    """Avvio in corso: servizi non ancora pronti."""

    RUNNING = "running"
    """Operativa."""

    STANDBY = "standby"
    """Sospesa volontariamente: animazioni al minimo, sensori fermi.

    Stato importante per un'applicazione che parte al login e resta accesa tutto
    il giorno: non deve consumare CPU quando non serve.
    """

    SHUTTING_DOWN = "shutting_down"
    """Chiusura in corso: i servizi si stanno fermando in ordine."""


class LinkState(StrEnum):
    """Stato del canale verso il backend."""

    OFFLINE = "offline"
    """Nessuna connessione e nessun tentativo in corso."""

    CONNECTING = "connecting"
    """Tentativo in corso, incluse le riconnessioni con backoff."""

    ONLINE = "online"
    """Connesso e handshake completato."""

    DEGRADED = "degraded"
    """Connesso ma non sano: heartbeat in ritardo o latenza oltre soglia.

    Distinguere ``DEGRADED`` da ``OFFLINE`` evita di dichiarare Jarvis assente
    quando in realta' e' solo lento — la reazione dell'utente e' diversa.
    """


class AgentState(StrEnum):
    """Cosa sta facendo l'assistente.

    La fonte di verita' e' **OpenClaw**. La GUI puo' anticipare localmente un
    cambiamento per reattivita' percepita, ma deve riconciliarsi con l'evento
    del backend entro un timeout (vedi :class:`~core.state.manager.StateManager`).
    """

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"


class VisualMode(StrEnum):
    """Modalita' visiva risolta: cio' che nucleo, HUD e tema mostrano.

    E' l'unico enum che l'interfaccia consuma. I widget non leggono mai le tre
    macchine direttamente: se lo facessero, la logica di precedenza finirebbe
    duplicata in ogni pannello e in due anni sarebbe incoerente.
    """

    BOOT = "boot"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    SUCCESS = "success"
    ERROR = "error"
    STANDBY = "standby"
