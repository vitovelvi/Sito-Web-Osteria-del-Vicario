"""Missioni e azioni: il livello operativo di JCP.

Il protocollo aveva già ``task.update``, sufficiente per una barra di
avanzamento ma non per rappresentare cosa un assistente **fa** davvero: una
richiesta dell'utente diventa una missione, la missione produce azioni, le
azioni usano strumenti, alcune richiedono conferma, tutte hanno un esito.

Modello a tre livelli:

* **Missione** — un obiettivo, di solito nato da un messaggio dell'utente.
  Può contenere sotto-missioni (``parent_id``).
* **Azione** — una singola invocazione di uno strumento dentro una missione.
  Ha una coda, uno stato, una durata e un esito.
* **Strumento** — ciò che l'azione usa. Il backend ne dichiara il registro,
  così la GUI può mostrare nomi leggibili e livelli di rischio invece di
  identificatori grezzi.

**Nessuna decisione sta qui.** Il backend decide cosa fare; la GUI riceve i
fatti e li mostra. L'unico messaggio che va nella direzione opposta è la
risposta a una richiesta di conferma — che è una decisione dell'**utente**, non
dell'interfaccia, e per questo il protocollo la trasporta esplicitamente invece
di lasciarla implicita.

Retrocompatibilità: ``task.update`` resta valido e viene proiettato come
un'azione senza missione. Due sistemi paralleli nella GUI sarebbero il modo
più rapido per farli divergere.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ActionCancelPayload",
    "ActionConfirmReplyPayload",
    "ActionConfirmRequestPayload",
    "ActionFinishedPayload",
    "ActionProgressPayload",
    "ActionQueuedPayload",
    "ActionStartedPayload",
    "ActionStatus",
    "MissionFinishedPayload",
    "MissionStartedPayload",
    "MissionStatus",
    "MissionType",
    "MissionUpdatedPayload",
    "RiskLevel",
    "ToolDescriptor",
    "ToolRegistryPayload",
]


class MissionType:
    """Tipi di messaggio del livello operativo."""

    # --- missioni: backend → GUI ---
    MISSION_STARTED: Final = "mission.started"
    MISSION_UPDATED: Final = "mission.updated"
    MISSION_FINISHED: Final = "mission.finished"

    # --- azioni: backend → GUI ---
    ACTION_QUEUED: Final = "action.queued"
    ACTION_STARTED: Final = "action.started"
    ACTION_PROGRESS: Final = "action.progress"
    ACTION_FINISHED: Final = "action.finished"
    ACTION_CONFIRM_REQUEST: Final = "action.confirm_request"

    # --- azioni: GUI → backend (le uniche due) ---
    ACTION_CONFIRM_REPLY: Final = "action.confirm_reply"
    ACTION_CANCEL: Final = "action.cancel"
    MISSION_CANCEL: Final = "mission.cancel"

    # --- strumenti ---
    TOOL_REGISTRY: Final = "tool.registry"


class MissionStatus(StrEnum):
    """Stato di una missione."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"
    """Il canale è caduto mentre la missione era in corso.

    Non è un esito dichiarato dal backend: è l'ammissione che la GUI **non sa
    più** come sia finita. Segnarla arbitrariamente come fallita sarebbe
    inventare; lasciarla "in corso" per sempre sarebbe mentire.
    """


class ActionStatus(StrEnum):
    """Stato di un'azione."""

    QUEUED = "queued"
    WAITING_CONFIRMATION = "waiting_confirmation"
    RUNNING = "running"
    OK = "ok"
    ERROR = "error"
    CANCELLED = "cancelled"
    DENIED = "denied"
    """Conferma negata dall'utente."""

    UNKNOWN = "unknown"
    """Canale caduto durante l'esecuzione (vedi :attr:`MissionStatus.UNKNOWN`)."""

    @property
    def is_terminal(self) -> bool:
        """Vero se lo stato non evolverà più."""
        return self in (
            ActionStatus.OK,
            ActionStatus.ERROR,
            ActionStatus.CANCELLED,
            ActionStatus.DENIED,
            ActionStatus.UNKNOWN,
        )

    @property
    def is_active(self) -> bool:
        """Vero se l'azione occupa la coda."""
        return not self.is_terminal


class RiskLevel(StrEnum):
    """Rischio dichiarato di uno strumento o di un'azione.

    Serve alla GUI per decidere **quanto insistere**: una conferma per
    un'operazione distruttiva non può avere lo stesso peso visivo di una
    lettura. Il livello è dichiarato dal backend, non dedotto dalla GUI.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"

    @property
    def requires_emphasis(self) -> bool:
        """Vero per i livelli che meritano un trattamento visivo forte."""
        return self in (RiskLevel.HIGH, RiskLevel.DESTRUCTIVE)


class _Payload(BaseModel):
    """Base tollerante in ingresso, immutabile in uscita."""

    model_config = ConfigDict(extra="ignore", frozen=True)


# --------------------------------------------------------------------------- #
# Missioni
# --------------------------------------------------------------------------- #


class MissionStartedPayload(_Payload):
    mission_id: str
    title: str
    goal: str | None = None
    parent_id: str | None = None
    """Missione padre, per gli obiettivi scomposti in sotto-obiettivi."""

    related_message_id: str | None = None
    """Messaggio dell'utente che l'ha originata: collega la conversazione alle
    operazioni, che è la domanda più frequente guardando una cronologia."""


class MissionUpdatedPayload(_Payload):
    mission_id: str
    status: str = MissionStatus.RUNNING.value
    progress: float | None = None
    summary: str | None = None


class MissionFinishedPayload(_Payload):
    mission_id: str
    status: str = MissionStatus.COMPLETED.value
    summary: str | None = None
    error: str | None = None


class MissionCancelPayload(_Payload):
    mission_id: str


# --------------------------------------------------------------------------- #
# Azioni
# --------------------------------------------------------------------------- #


class ActionQueuedPayload(_Payload):
    action_id: str
    tool: str
    title: str
    mission_id: str | None = None
    args_preview: str | None = None
    """Anteprima **già ridotta dal backend**. Il protocollo non trasporta gli
    argomenti completi: possono contenere segreti, e la GUI non ha motivo di
    riceverli per mostrarli."""

    risk: str = RiskLevel.LOW.value
    position: int | None = None
    """Posizione in coda, se il backend la espone."""


class ActionStartedPayload(_Payload):
    action_id: str


class ActionProgressPayload(_Payload):
    action_id: str
    progress: float | None = None
    note: str | None = None


class ActionFinishedPayload(_Payload):
    action_id: str
    status: str = ActionStatus.OK.value
    result_preview: str | None = None
    error: str | None = None
    duration_ms: float | None = None
    """Misurata dal **backend**. La GUI misura anche la propria, e le due
    insieme separano il tempo di esecuzione dal tempo di trasporto."""


class ActionCancelPayload(_Payload):
    action_id: str


# --------------------------------------------------------------------------- #
# Conferme
# --------------------------------------------------------------------------- #


class ActionConfirmRequestPayload(_Payload):
    """Richiesta di conferma prima di eseguire un'azione."""

    request_id: str
    action_id: str
    title: str
    detail: str | None = None
    risk: str = RiskLevel.MEDIUM.value
    expires_in_s: float | None = None
    """Scadenza dichiarata dal backend. Alla scadenza la GUI **smette di
    chiedere** e lo dice: una conferma che resta a schermo per un'operazione
    ormai abbandonata è peggio che nessuna conferma."""

    options: list[str] = Field(default_factory=list)
    """Alternative oltre a sì/no. Vuoto significa conferma binaria."""


class ActionConfirmReplyPayload(_Payload):
    """Risposta dell'utente. È l'unica decisione che viaggia verso il backend."""

    request_id: str
    approved: bool
    option: str | None = None
    remember: bool = False
    """L'utente chiede di non essere più interrogato per casi simili. La
    politica è del backend: la GUI trasmette la preferenza, non la applica."""


# --------------------------------------------------------------------------- #
# Strumenti
# --------------------------------------------------------------------------- #


class ToolDescriptor(_Payload):
    """Descrizione di uno strumento dichiarato dal backend."""

    name: str
    title: str | None = None
    description: str | None = None
    category: str | None = None
    risk: str = RiskLevel.LOW.value


class ToolRegistryPayload(_Payload):
    """Registro degli strumenti.

    Senza, la GUI mostrerebbe identificatori grezzi (``fs.write_file``) invece
    di nomi leggibili, e non saprebbe quali operazioni sono rischiose.
    """

    tools: list[ToolDescriptor] = Field(default_factory=list)
    replace: bool = True
    """Se il registro sostituisce quello precedente o lo integra."""


#: Schemi del livello operativo, uniti a quelli base da
#: :data:`jarvis_protocol.messages._SCHEMAS`.
OPERATIONS_SCHEMAS: Final[dict[str, type[_Payload]]] = {
    MissionType.MISSION_STARTED: MissionStartedPayload,
    MissionType.MISSION_UPDATED: MissionUpdatedPayload,
    MissionType.MISSION_FINISHED: MissionFinishedPayload,
    MissionType.MISSION_CANCEL: MissionCancelPayload,
    MissionType.ACTION_QUEUED: ActionQueuedPayload,
    MissionType.ACTION_STARTED: ActionStartedPayload,
    MissionType.ACTION_PROGRESS: ActionProgressPayload,
    MissionType.ACTION_FINISHED: ActionFinishedPayload,
    MissionType.ACTION_CONFIRM_REQUEST: ActionConfirmRequestPayload,
    MissionType.ACTION_CONFIRM_REPLY: ActionConfirmReplyPayload,
    MissionType.ACTION_CANCEL: ActionCancelPayload,
    MissionType.TOOL_REGISTRY: ToolRegistryPayload,
}


def coerce_status(raw: Any, enum: type[StrEnum], default: StrEnum) -> StrEnum:
    """Converte uno stato dichiarato dal backend, senza mai sollevare.

    Uno stato sconosciuto ricade sul default e viene mostrato per quello che è.
    Un backend più recente può introdurne di nuovi: ignorarli è previsto,
    esplodere no.
    """
    try:
        return enum(str(raw))
    except ValueError:
        return default
