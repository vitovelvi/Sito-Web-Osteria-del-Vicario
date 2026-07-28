"""Catalogo degli eventi e relativi payload tipizzati.

Il brief propone un bus con eventi identificati da stringhe. E' il punto in cui
un progetto destinato a durare anni si degrada per primo: ``"VOICE_STARTED"``
scritto male fallisce in silenzio, nessun controllo statico lo intercetta e il
payload e' un dizionario di forma ignota.

Qui ogni evento e' una voce di :class:`EventType` con un **payload dataclass
dedicato**. Il beneficio non e' formale: ``mypy`` verifica i campi,
l'autocompletamento funziona, e la mappa :data:`PAYLOAD_TYPES` consente al bus
di rifiutare in sviluppo un payload della forma sbagliata prima che arrivi ai
sottoscrittori.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = ["PAYLOAD_TYPES", "EventType"]


class EventType(StrEnum):
    """Eventi pubblicabili sul bus.

    Convenzione dei nomi: ``dominio.fatto``, sempre al passato — un evento
    descrive qualcosa che **e' accaduto**, non un comando. I comandi viaggiano
    sul layer :mod:`core.commands`, che ha semantica di richiesta.
    """

    # --- Ciclo di vita dell'applicazione ---
    APP_READY = "app.ready"
    APP_SHUTDOWN = "app.shutdown"
    APP_STATE_CHANGED = "app.state_changed"
    CONFIG_CHANGED = "config.changed"

    # --- Connessione al backend ---
    CONNECTED = "link.connected"
    DISCONNECTED = "link.disconnected"
    LINK_STATE_CHANGED = "link.state_changed"
    TRANSPORT_LATENCY = "link.latency"
    HANDSHAKE_COMPLETED = "link.handshake_completed"

    # --- Identita' e capability ---
    IDENTITY_UPDATED = "identity.updated"
    CAPABILITIES_UPDATED = "capabilities.updated"

    # --- Assistente ---
    AGENT_STATE_CHANGED = "agent.state_changed"
    STATE_TRANSITION_REJECTED = "agent.transition_rejected"
    USER_MESSAGE = "chat.user_message"
    AI_RESPONSE = "chat.ai_response"

    # --- Voce e audio ---
    VOICE_STARTED = "voice.started"
    VOICE_STOPPED = "voice.stopped"
    WAKE_WORD_DETECTED = "voice.wake_word"
    AUDIO_PLAYING = "audio.playing"
    AUDIO_FINISHED = "audio.finished"
    AUDIO_LEVEL = "audio.level"
    AUDIO_STREAM_CHUNK = "audio.stream_chunk"

    # --- Visione ---
    VISION_UPDATED = "vision.updated"

    # --- Sistema e servizi ---
    SYSTEM_STATUS = "system.status"
    SERVICE_STATUS_CHANGED = "service.status_changed"
    ERROR = "error.raised"
    ERROR_CLEARED = "error.cleared"

    # --- Task in corso (forma semplice, retrocompatibile) ---
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"
    TASK_FINISHED = "task.finished"

    # --- Livello operativo: missioni, azioni, conferme, strumenti ---
    MISSION_CHANGED = "mission.changed"
    ACTION_CHANGED = "action.changed"
    CONFIRM_REQUESTED = "confirm.requested"
    CONFIRM_RESOLVED = "confirm.resolved"
    TOOLS_UPDATED = "tools.updated"
    OPERATIONS_METRICS = "operations.metrics"

    # --- Interfaccia ---
    NOTIFICATION_REQUESTED = "ui.notification"
    VISUAL_MODE_CHANGED = "ui.visual_mode_changed"

    def __str__(self) -> str:  # pragma: no cover - solo diagnostica
        return self.value


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #
#
# Sono dataclass immutabili: un payload che attraversa i thread non deve poter
# essere modificato da chi lo riceve.


@dataclass(frozen=True, slots=True)
class Empty:
    """Payload per gli eventi che non trasportano dati."""


@dataclass(frozen=True, slots=True)
class LinkStatus:
    """Stato del canale verso OpenClaw."""

    state: str
    endpoint: str | None = None
    attempt: int = 0
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LatencySample:
    """Misura di andata e ritorno dell'heartbeat."""

    rtt_ms: float
    average_ms: float | None = None


@dataclass(frozen=True, slots=True)
class BackendIdentity:
    """Identita' dichiarata dal backend nell'handshake.

    E' cio' che la GUI mostra come "chi sono": nome, versione, modello attivo.
    L'interfaccia non lo deduce mai da sola — riflette quanto dichiarato.
    """

    assistant_name: str = "J.A.R.V.I.S."
    backend_name: str = "OpenClaw"
    backend_version: str | None = None
    model: str | None = None
    persona: str | None = None
    accent_color: str | None = None
    instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilitySet:
    """Insieme delle funzioni dichiarate disponibili dal backend."""

    granted: frozenset[str] = frozenset()
    protocol_version: str = ""
    """Versione JCP concordata, nella forma ``major.minor``. Vuota prima
    dell'handshake: mostrare ``0`` suggerirebbe una versione zero esistente."""

    unknown: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class StateChange:
    """Transizione di una delle macchine a stati."""

    machine: str
    previous: str
    current: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RejectedTransition:
    """Transizione rifiutata dalla tabella. Non e' un errore fatale: si logga."""

    machine: str
    current: str
    requested: str
    reason: str


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Messaggio utente inviato al backend."""

    text: str
    message_id: str
    attachments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResponseChunk:
    """Frammento di risposta in streaming.

    Lo streaming token-per-token e' il motivo per cui la chat sembra viva. Il
    campo ``final`` segnala l'ultimo frammento.
    """

    text: str
    message_id: str
    final: bool = False


@dataclass(frozen=True, slots=True)
class AudioLevel:
    """Inviluppo dell'audio in riproduzione o in ingresso.

    Alimenta l'equalizzatore del nucleo: l'animazione reagisce all'ampiezza
    reale, non a un moto finto. E' la differenza che si nota subito.
    """

    rms: float
    peak: float = 0.0
    spectrum: tuple[float, ...] = ()
    direction: str = "output"


@dataclass(frozen=True, slots=True)
class AudioChunk:
    """Blocco audio grezzo proveniente dal backend.

    Il livello di rete si limita a **decodificare la codifica di trasporto**
    (base64) e a pubblicare i byte. Analisi, buffering e riproduzione sono
    responsabilita' del servizio audio: se il dispatcher calcolasse qui
    l'inviluppo, la rete inizierebbe a fare elaborazione del segnale e il
    confine fra i due livelli sarebbe perso.
    """

    stream_id: str
    sequence: int
    pcm: bytes
    sample_rate: int = 24000
    channels: int = 1
    encoding: str = "pcm_s16le"


@dataclass(frozen=True, slots=True)
class VisionFrame:
    """Frame pronto per la visualizzazione.

    ``image`` e' una ``QImage`` gia' **copiata** dal buffer numpy: passare la
    vista originale e' la prima causa di crash nelle GUI con OpenCV, perche'
    ``QImage`` non possiede i dati (docs §6).
    """

    image: Any
    width: int
    height: int
    frame_index: int
    dropped: int = 0


@dataclass(frozen=True, slots=True)
class SystemStats:
    """Metriche di sistema. I campi opzionali sono ``None`` quando la piattaforma
    non li espone in modo affidabile — mai valori inventati (docs §9)."""

    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    gpu_percent: float | None = None
    gpu_memory_percent: float | None = None
    temperature_c: float | None = None
    net_sent_kbps: float = 0.0
    net_recv_kbps: float = 0.0


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """Stato di salute di un servizio registrato nel supervisor."""

    name: str
    status: str
    detail: str | None = None
    restarts: int = 0


@dataclass(frozen=True, slots=True)
class ErrorRaised:
    """Trasporta una :class:`~core.errors.ErrorCondition` sul bus."""

    condition: Any


@dataclass(frozen=True, slots=True)
class TaskInfo:
    """Azione in corso lato backend."""

    task_id: str
    label: str
    progress: float | None = None
    status: str = "running"


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    """Istantanea immutabile di una missione, per i widget."""

    mission_id: str
    title: str
    status: str
    goal: str | None = None
    progress: float | None = None
    progress_is_derived: bool = False
    """L'avanzamento e' dedotto dalle azioni concluse, non dichiarato dal
    backend. L'interfaccia deve poterlo distinguere da un dato reale."""

    summary: str | None = None
    error: str | None = None
    parent_id: str | None = None
    duration_s: float = 0.0
    action_count: int = 0


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    """Istantanea immutabile di un'azione."""

    action_id: str
    tool: str
    title: str
    status: str
    risk: str = "low"
    mission_id: str | None = None
    progress: float | None = None
    note: str | None = None
    args_preview: str | None = None
    result_preview: str | None = None
    error: str | None = None
    duration_ms: float | None = None
    queue_wait_ms: float | None = None


@dataclass(frozen=True, slots=True)
class ConfirmSnapshot:
    """Richiesta di conferma, o suo esito."""

    request_id: str
    action_id: str
    title: str
    detail: str | None = None
    risk: str = "medium"
    options: tuple[str, ...] = ()
    seconds_left: float | None = None
    resolved: bool = False
    approved: bool | None = None


@dataclass(frozen=True, slots=True)
class ToolsSnapshot:
    """Strumenti dichiarati e osservati.

    I due insiemi restano distinti: uno strumento assente dal registro ma visto
    in azione e' un'informazione, non un errore.
    """

    declared: tuple[str, ...] = ()
    observed: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OperationsMetrics:
    """Metriche derivate del livello operativo."""

    missions_active: int = 0
    missions_completed: int = 0
    missions_failed: int = 0
    missions_unknown: int = 0
    queue_depth: int = 0
    running: int = 0
    awaiting_confirmation: int = 0
    actions_completed: int = 0
    success_rate: float | None = None
    avg_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    avg_queue_wait_ms: float | None = None
    throughput_per_min: float = 0.0
    tools_used: int = 0
    tools_declared: int = 0


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """Richiesta di toast. La GUI decide come e dove mostrarlo."""

    title: str
    body: str = ""
    kind: str = "info"
    duration_ms: int = 4000


@dataclass(frozen=True, slots=True)
class VisualModeChange:
    """Modalita' visiva risolta dalle tre macchine a stati (docs §2.3)."""

    mode: str
    previous: str
    transition_ms: int = 320


@dataclass(frozen=True, slots=True)
class ConfigChange:
    """Chiavi di configurazione modificate a caldo."""

    keys: tuple[str, ...] = field(default_factory=tuple)


#: Payload atteso per ciascun evento. Il bus lo usa per validare in sviluppo:
#: un payload della forma sbagliata viene rifiutato subito, dove il bug e'
#: ancora leggibile, invece di esplodere dentro un widget tre livelli piu' in la'.
PAYLOAD_TYPES: dict[EventType, type] = {
    EventType.APP_READY: Empty,
    EventType.APP_SHUTDOWN: Empty,
    EventType.APP_STATE_CHANGED: StateChange,
    EventType.CONFIG_CHANGED: ConfigChange,
    EventType.CONNECTED: LinkStatus,
    EventType.DISCONNECTED: LinkStatus,
    EventType.LINK_STATE_CHANGED: LinkStatus,
    EventType.TRANSPORT_LATENCY: LatencySample,
    EventType.HANDSHAKE_COMPLETED: BackendIdentity,
    EventType.IDENTITY_UPDATED: BackendIdentity,
    EventType.CAPABILITIES_UPDATED: CapabilitySet,
    EventType.AGENT_STATE_CHANGED: StateChange,
    EventType.STATE_TRANSITION_REJECTED: RejectedTransition,
    EventType.USER_MESSAGE: ChatMessage,
    EventType.AI_RESPONSE: ResponseChunk,
    EventType.VOICE_STARTED: Empty,
    EventType.VOICE_STOPPED: Empty,
    EventType.WAKE_WORD_DETECTED: Empty,
    EventType.AUDIO_PLAYING: Empty,
    EventType.AUDIO_FINISHED: Empty,
    EventType.AUDIO_LEVEL: AudioLevel,
    EventType.AUDIO_STREAM_CHUNK: AudioChunk,
    EventType.VISION_UPDATED: VisionFrame,
    EventType.SYSTEM_STATUS: SystemStats,
    EventType.SERVICE_STATUS_CHANGED: ServiceStatus,
    EventType.ERROR: ErrorRaised,
    EventType.ERROR_CLEARED: ErrorRaised,
    EventType.TASK_STARTED: TaskInfo,
    EventType.TASK_PROGRESS: TaskInfo,
    EventType.TASK_FINISHED: TaskInfo,
    EventType.MISSION_CHANGED: MissionSnapshot,
    EventType.ACTION_CHANGED: ActionSnapshot,
    EventType.CONFIRM_REQUESTED: ConfirmSnapshot,
    EventType.CONFIRM_RESOLVED: ConfirmSnapshot,
    EventType.TOOLS_UPDATED: ToolsSnapshot,
    EventType.OPERATIONS_METRICS: OperationsMetrics,
    EventType.NOTIFICATION_REQUESTED: NotificationRequest,
    EventType.VISUAL_MODE_CHANGED: VisualModeChange,
}
