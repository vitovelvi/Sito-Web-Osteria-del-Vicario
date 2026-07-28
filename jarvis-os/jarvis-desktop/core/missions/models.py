"""Modelli del livello operativo: missioni, azioni, conferme, strumenti.

Sono oggetti **mutabili**, a differenza dei payload del protocollo e degli
eventi del bus. La differenza è voluta: un payload attraversa i thread e non
deve poter essere modificato da chi lo riceve, mentre una missione vive per
minuti e viene aggiornata decine di volte. Copiarla a ogni aggiornamento
sarebbe spreco senza vantaggi, perché ha un solo proprietario — il
:class:`~core.missions.engine.MissionEngine`, che vive nel thread GUI.

Ciò che i widget ricevono sono **istantanee immutabili** (:meth:`Mission.snapshot`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from jarvis_protocol.missions import ActionStatus, MissionStatus, RiskLevel

__all__ = ["Action", "ConfirmRequest", "Mission", "ToolInfo"]


@dataclass(slots=True)
class Action:
    """Una singola invocazione di uno strumento."""

    action_id: str
    tool: str
    title: str
    mission_id: str | None = None
    status: ActionStatus = ActionStatus.QUEUED
    risk: RiskLevel = RiskLevel.LOW
    args_preview: str | None = None
    result_preview: str | None = None
    error: str | None = None
    progress: float | None = None
    note: str | None = None

    queued_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    backend_duration_ms: float | None = None
    """Durata misurata dal backend."""

    confirm_request_id: str | None = None

    @property
    def wall_duration_ms(self) -> float | None:
        """Durata misurata dall'interfaccia, dall'avvio alla fine.

        Confrontata con :attr:`backend_duration_ms` separa il tempo di
        esecuzione dal tempo di trasporto: se le due divergono molto, il
        problema è il canale, non lo strumento.
        """
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return (end - self.started_at) * 1000.0

    @property
    def queue_wait_ms(self) -> float | None:
        """Tempo trascorso in coda prima dell'avvio."""
        if self.started_at is None:
            return None
        return (self.started_at - self.queued_at) * 1000.0

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    @property
    def succeeded(self) -> bool:
        return self.status is ActionStatus.OK


@dataclass(slots=True)
class Mission:
    """Un obiettivo in corso o concluso."""

    mission_id: str
    title: str
    goal: str | None = None
    parent_id: str | None = None
    related_message_id: str | None = None
    status: MissionStatus = MissionStatus.RUNNING
    progress: float | None = None
    summary: str | None = None
    error: str | None = None

    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    action_ids: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return end - self.started_at

    @property
    def is_active(self) -> bool:
        return self.status is MissionStatus.RUNNING

    def derived_progress(self, active_actions: dict[str, Action]) -> float | None:
        """Avanzamento dichiarato, oppure dedotto dalle azioni concluse.

        La deduzione è esplicitamente **secondaria**: se il backend dichiara un
        progresso, quello vince sempre. Contare le azioni è un'approssimazione
        utile solo quando non c'è di meglio, e l'interfaccia deve poterla
        distinguere da un dato reale — per questo il metodo è separato dal
        campo, invece di scriverci dentro.

        :param active_actions: azioni **ancora attive**, indicizzate per id.
            La conclusione si deduce dall'assenza: un'azione conclusa esce
            dall'insieme delle attive. Cercarla invece nell'insieme delle
            attive la farebbe sparire dal conteggio, e l'avanzamento
            *scenderebbe* a ogni azione completata.
        """
        if self.progress is not None:
            return self.progress
        if not self.action_ids:
            return None
        concluse = sum(1 for action_id in self.action_ids if action_id not in active_actions)
        return concluse / len(self.action_ids)


@dataclass(slots=True)
class ConfirmRequest:
    """Richiesta di conferma in attesa di risposta dell'utente."""

    request_id: str
    action_id: str
    title: str
    detail: str | None = None
    risk: RiskLevel = RiskLevel.MEDIUM
    options: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.monotonic)
    expires_at: float | None = None
    resolved: bool = False
    approved: bool | None = None

    @property
    def seconds_left(self) -> float | None:
        """Secondi rimasti prima della scadenza, o ``None`` se non scade."""
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.monotonic())

    @property
    def is_expired(self) -> bool:
        left = self.seconds_left
        return left is not None and left <= 0.0


@dataclass(slots=True)
class ToolInfo:
    """Strumento dichiarato dal backend, più le statistiche osservate.

    Le due parti hanno origine diversa e vanno tenute distinte: nome, titolo e
    rischio sono **dichiarati**; conteggi e durate sono **osservati**
    dall'interfaccia. Un Tool Inspector che li mescolasse impedirebbe di capire
    se uno strumento non compare perché non è dichiarato o perché non è mai
    stato usato.
    """

    name: str
    title: str | None = None
    description: str | None = None
    category: str | None = None
    risk: RiskLevel = RiskLevel.LOW
    declared: bool = False
    """Falso per gli strumenti visti in azione ma assenti dal registro."""

    invocations: int = 0
    succeeded: int = 0
    failed: int = 0
    denied: int = 0
    cancelled: int = 0
    durations_ms: list[float] = field(default_factory=list)
    last_used_at: float | None = None

    @property
    def display_name(self) -> str:
        return self.title or self.name

    @property
    def success_rate(self) -> float | None:
        """Frazione di successi sulle invocazioni concluse, o ``None``."""
        concluse = self.succeeded + self.failed + self.denied + self.cancelled
        return self.succeeded / concluse if concluse else None

    @property
    def average_ms(self) -> float | None:
        return sum(self.durations_ms) / len(self.durations_ms) if self.durations_ms else None

    @property
    def p95_ms(self) -> float | None:
        """Novantacinquesimo percentile delle durate.

        La media da sola nasconde le code lente, che sono esattamente il caso
        che rende un assistente frustrante da usare.
        """
        if not self.durations_ms:
            return None
        ordinate = sorted(self.durations_ms)
        indice = min(len(ordinate) - 1, int(len(ordinate) * 0.95))
        return ordinate[indice]

    def record(self, action: Action) -> None:
        """Aggiorna le statistiche con un'azione conclusa."""
        self.invocations += 1
        self.last_used_at = time.monotonic()

        if action.status is ActionStatus.OK:
            self.succeeded += 1
        elif action.status is ActionStatus.ERROR:
            self.failed += 1
        elif action.status is ActionStatus.DENIED:
            self.denied += 1
        elif action.status is ActionStatus.CANCELLED:
            self.cancelled += 1

        durata = action.backend_duration_ms or action.wall_duration_ms
        if durata is not None:
            self.durations_ms.append(durata)
            # Finestra mobile: le durate di un'ora fa non descrivono più il
            # comportamento attuale, e conservarle tutte fa crescere la memoria
            # per l'intera sessione.
            if len(self.durations_ms) > 200:
                del self.durations_ms[:-200]
