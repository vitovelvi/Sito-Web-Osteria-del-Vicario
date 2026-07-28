"""Mission Engine: proiezione degli eventi operativi del backend.

**Il motore non decide nulla.** È una proiezione: riceve fatti dichiarati dal
backend e ne mantiene la forma consultabile dall'interfaccia. Non avvia azioni,
non stabilisce esiti, non deduce fallimenti da un timeout. Se un giorno
iniziasse a farlo, la GUI avrebbe smesso di essere il volto di J.A.R.V.I.S. per
diventare un secondo cervello che dice cose diverse dal primo.

C'è **una sola eccezione, ed è deliberata**: alla caduta del canale, missioni e
azioni ancora attive passano a ``UNKNOWN``. Non è una deduzione sull'esito — è
l'affermazione esatta che l'interfaccia non sa più come siano finite. Le due
alternative sarebbero peggiori: marcarle fallite significherebbe inventare;
lasciarle "in corso" significherebbe mostrare per sempre un'attività che nessuno
sta più svolgendo.

L'unica cosa che viaggia verso il backend è la risposta a una richiesta di
conferma, che è una decisione dell'**utente**. Il motore la inoltra tramite un
mittente iniettato, senza conoscere la rete.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Final, Protocol

from jarvis_protocol.missions import (
    ActionStatus,
    MissionStatus,
    MissionType,
    RiskLevel,
    coerce_status,
)

from core.eventbus import EventBus
from core.events import (
    ActionSnapshot,
    ConfirmSnapshot,
    EventType,
    MissionSnapshot,
    NotificationRequest,
    OperationsMetrics,
    ToolsSnapshot,
)
from core.logging_setup import LogCategory, get_logger
from core.missions.models import Action, ConfirmRequest, Mission, ToolInfo

__all__ = ["ICommandSender", "MissionEngine"]

_log = get_logger(LogCategory.APP, "missions")

#: Missioni concluse conservate in cronologia.
_HISTORY_MISSIONS: Final[int] = 100

#: Azioni concluse conservate in cronologia.
_HISTORY_ACTIONS: Final[int] = 400

#: Finestra per il calcolo della produttività, in secondi.
_THROUGHPUT_WINDOW: Final[float] = 300.0


class ICommandSender(Protocol):
    """Ciò di cui il motore ha bisogno per rispondere al backend.

    Deliberatamente minimo: il motore non deve conoscere il servizio di rete,
    solo il fatto che qualcosa sappia inoltrare un messaggio JCP. È ciò che lo
    rende testabile senza connessione.
    """

    def send(self, message_type: str, payload: dict[str, Any] | None = None) -> bool: ...


class MissionEngine:
    """Mantiene lo stato operativo dichiarato dal backend."""

    def __init__(self, bus: EventBus, sender: ICommandSender | None = None) -> None:
        self._bus = bus
        self._sender = sender
        self._lock = threading.RLock()

        self._missions: dict[str, Mission] = {}
        self._actions: dict[str, Action] = {}
        self._confirms: dict[str, ConfirmRequest] = {}
        self._tools: dict[str, ToolInfo] = {}

        self._mission_history: deque[Mission] = deque(maxlen=_HISTORY_MISSIONS)
        self._action_history: deque[Action] = deque(maxlen=_HISTORY_ACTIONS)
        self._completions: deque[float] = deque(maxlen=1000)
        """Istanti di conclusione, per la produttività su finestra mobile."""

        self._handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            MissionType.MISSION_STARTED: self._on_mission_started,
            MissionType.MISSION_UPDATED: self._on_mission_updated,
            MissionType.MISSION_FINISHED: self._on_mission_finished,
            MissionType.ACTION_QUEUED: self._on_action_queued,
            MissionType.ACTION_STARTED: self._on_action_started,
            MissionType.ACTION_PROGRESS: self._on_action_progress,
            MissionType.ACTION_FINISHED: self._on_action_finished,
            MissionType.ACTION_CONFIRM_REQUEST: self._on_confirm_request,
            MissionType.TOOL_REGISTRY: self._on_tool_registry,
        }

    def attach_sender(self, sender: ICommandSender) -> None:
        """Collega il mittente dopo la costruzione.

        Serve al bootstrap: motore e servizio di rete si costruiscono in ordine
        e uno dei due deve poter arrivare dopo.
        """
        self._sender = sender

    # ------------------------------------------------------------------ #
    # Ingresso: fatti dichiarati dal backend
    # ------------------------------------------------------------------ #

    def apply(self, message_type: str, payload: Any) -> None:
        """Applica un messaggio operativo già validato dal dispatcher.

        Non solleva mai: un messaggio inatteso viene loggato e scartato.
        """
        handler = self._handlers.get(message_type)
        if handler is None:
            return
        try:
            handler(payload.model_dump() if hasattr(payload, "model_dump") else dict(payload))
        except Exception:
            _log.exception("Messaggio operativo '%s' non applicato", message_type)

    # -- missioni ---------------------------------------------------------- #

    def _on_mission_started(self, p: dict[str, Any]) -> None:
        mission = Mission(
            mission_id=str(p["mission_id"]),
            title=str(p.get("title") or "Operazione"),
            goal=p.get("goal"),
            parent_id=p.get("parent_id"),
            related_message_id=p.get("related_message_id"),
        )
        with self._lock:
            self._missions[mission.mission_id] = mission
        _log.info("Missione avviata: %s", mission.title)
        self._publish_mission(mission)

    def _on_mission_updated(self, p: dict[str, Any]) -> None:
        with self._lock:
            mission = self._missions.get(str(p["mission_id"]))
            if mission is None:
                return
            mission.status = coerce_status(
                p.get("status", mission.status), MissionStatus, mission.status
            )
            if p.get("progress") is not None:
                mission.progress = max(0.0, min(1.0, float(p["progress"])))
            if p.get("summary"):
                mission.summary = str(p["summary"])
        self._publish_mission(mission)

    def _on_mission_finished(self, p: dict[str, Any]) -> None:
        with self._lock:
            mission = self._missions.pop(str(p["mission_id"]), None)
            if mission is None:
                return
            mission.status = coerce_status(
                p.get("status"), MissionStatus, MissionStatus.COMPLETED
            )
            mission.summary = p.get("summary") or mission.summary
            mission.error = p.get("error")
            mission.finished_at = time.monotonic()
            self._mission_history.append(mission)

        _log.info(
            "Missione conclusa (%s): %s in %.1fs",
            mission.status.value,
            mission.title,
            mission.duration_s,
        )
        self._publish_mission(mission)
        self._publish_metrics()

    # -- azioni ------------------------------------------------------------ #

    def _on_action_queued(self, p: dict[str, Any]) -> None:
        action = Action(
            action_id=str(p["action_id"]),
            tool=str(p.get("tool") or "sconosciuto"),
            title=str(p.get("title") or p.get("tool") or "Azione"),
            mission_id=p.get("mission_id"),
            args_preview=p.get("args_preview"),
            risk=coerce_status(p.get("risk"), RiskLevel, RiskLevel.LOW),
        )
        with self._lock:
            self._actions[action.action_id] = action
            if action.mission_id and action.mission_id in self._missions:
                self._missions[action.mission_id].action_ids.append(action.action_id)
            # Uno strumento visto in azione ma assente dal registro viene
            # comunque registrato, marcato come non dichiarato: è
            # un'informazione utile, non un errore da nascondere.
            self._tools.setdefault(action.tool, ToolInfo(name=action.tool))
        self._publish_action(action)

    def _on_action_started(self, p: dict[str, Any]) -> None:
        with self._lock:
            action = self._actions.get(str(p["action_id"]))
            if action is None:
                return
            action.status = ActionStatus.RUNNING
            action.started_at = time.monotonic()
        self._publish_action(action)

    def _on_action_progress(self, p: dict[str, Any]) -> None:
        with self._lock:
            action = self._actions.get(str(p["action_id"]))
            if action is None:
                return
            if p.get("progress") is not None:
                action.progress = max(0.0, min(1.0, float(p["progress"])))
            if p.get("note"):
                action.note = str(p["note"])
        self._publish_action(action)

    def _on_action_finished(self, p: dict[str, Any]) -> None:
        with self._lock:
            action = self._actions.pop(str(p["action_id"]), None)
            if action is None:
                return
            action.status = coerce_status(p.get("status"), ActionStatus, ActionStatus.OK)
            action.result_preview = p.get("result_preview")
            action.error = p.get("error")
            action.backend_duration_ms = p.get("duration_ms")
            action.finished_at = time.monotonic()

            tool = self._tools.setdefault(action.tool, ToolInfo(name=action.tool))
            tool.record(action)
            self._action_history.append(action)
            self._completions.append(time.monotonic())

        if action.status is ActionStatus.ERROR:
            _log.warning("Azione fallita [%s]: %s", action.tool, action.error or "senza dettaglio")
        self._publish_action(action)
        self._publish_metrics()

    # -- conferme ---------------------------------------------------------- #

    def _on_confirm_request(self, p: dict[str, Any]) -> None:
        expires_in = p.get("expires_in_s")
        request = ConfirmRequest(
            request_id=str(p["request_id"]),
            action_id=str(p.get("action_id") or ""),
            title=str(p.get("title") or "Conferma richiesta"),
            detail=p.get("detail"),
            risk=coerce_status(p.get("risk"), RiskLevel, RiskLevel.MEDIUM),
            options=tuple(p.get("options") or ()),
            expires_at=None if expires_in is None else time.monotonic() + float(expires_in),
        )
        with self._lock:
            self._confirms[request.request_id] = request
            action = self._actions.get(request.action_id)
            if action is not None:
                action.status = ActionStatus.WAITING_CONFIRMATION
                action.confirm_request_id = request.request_id

        _log.info("Conferma richiesta [%s]: %s", request.risk.value, request.title)
        self._bus.publish(
            EventType.CONFIRM_REQUESTED, self._confirm_snapshot(request), source="missions"
        )
        if action is not None:
            self._publish_action(action)

    def resolve_confirmation(
        self,
        request_id: str,
        approved: bool,
        *,
        option: str | None = None,
        remember: bool = False,
    ) -> bool:
        """Inoltra al backend la decisione dell'utente.

        :returns: ``False`` se la richiesta non esiste, è già stata risolta o
            il canale non è disponibile. Non solleva: chi chiama è un widget.
        """
        with self._lock:
            request = self._confirms.get(request_id)
            if request is None or request.resolved:
                return False
            request.resolved = True
            request.approved = approved

        inviato = False
        if self._sender is not None:
            inviato = self._sender.send(
                MissionType.ACTION_CONFIRM_REPLY,
                {
                    "request_id": request_id,
                    "approved": approved,
                    "option": option,
                    "remember": remember,
                },
            )

        if not inviato:
            # La decisione dell'utente non è arrivata a destinazione: va detto,
            # perché altrimenti resterebbe convinto di aver autorizzato qualcosa.
            _log.error("Risposta alla conferma '%s' non inviata: canale assente", request_id)
            self._bus.publish(
                EventType.NOTIFICATION_REQUESTED,
                NotificationRequest(
                    title="Risposta non inviata",
                    body="Il canale verso il backend non è disponibile.",
                    kind="error",
                ),
                source="missions",
            )

        self._bus.publish(
            EventType.CONFIRM_RESOLVED, self._confirm_snapshot(request), source="missions"
        )
        return inviato

    def sweep_expired_confirmations(self) -> int:
        """Rimuove le richieste scadute.

        Alla scadenza la GUI **smette di chiedere**: una conferma a schermo per
        un'operazione che il backend ha già abbandonato è peggio di nessuna
        conferma, perché invita a un'azione senza effetto.
        """
        with self._lock:
            scadute = [r for r in self._confirms.values() if r.is_expired and not r.resolved]
            for request in scadute:
                request.resolved = True
                request.approved = None

        for request in scadute:
            _log.info("Conferma scaduta senza risposta: %s", request.title)
            self._bus.publish(
                EventType.CONFIRM_RESOLVED, self._confirm_snapshot(request), source="missions"
            )
        return len(scadute)

    # -- strumenti --------------------------------------------------------- #

    def _on_tool_registry(self, p: dict[str, Any]) -> None:
        descritti = p.get("tools") or []
        with self._lock:
            if p.get("replace", True):
                # Le statistiche osservate sopravvivono alla sostituzione del
                # registro: descrivono cosa è successo, non cosa è dichiarato.
                for tool in self._tools.values():
                    tool.declared = False

            for raw in descritti:
                nome = str(raw.get("name") or "")
                if not nome:
                    continue
                tool = self._tools.setdefault(nome, ToolInfo(name=nome))
                tool.title = raw.get("title")
                tool.description = raw.get("description")
                tool.category = raw.get("category")
                tool.risk = coerce_status(raw.get("risk"), RiskLevel, RiskLevel.LOW)
                tool.declared = True

        _log.info("Registro strumenti: %d dichiarati", len(descritti))
        self._publish_tools()

    # ------------------------------------------------------------------ #
    # Caduta del canale
    # ------------------------------------------------------------------ #

    def on_link_lost(self) -> None:
        """Segna come ignote le operazioni ancora attive.

        Vedi la nota in cima al modulo: non è una deduzione sull'esito, è
        l'ammissione che non lo si conosce più.
        """
        with self._lock:
            azioni = list(self._actions.values())
            missioni = list(self._missions.values())
            confirms = [r for r in self._confirms.values() if not r.resolved]

            for action in azioni:
                action.status = ActionStatus.UNKNOWN
                action.finished_at = time.monotonic()
                self._action_history.append(action)
            self._actions.clear()

            for mission in missioni:
                mission.status = MissionStatus.UNKNOWN
                mission.finished_at = time.monotonic()
                self._mission_history.append(mission)
            self._missions.clear()

            for request in confirms:
                request.resolved = True
            self._confirms.clear()

        if azioni or missioni:
            _log.warning(
                "Canale caduto: %d missioni e %d azioni di esito ignoto",
                len(missioni),
                len(azioni),
            )
        for mission in missioni:
            self._publish_mission(mission)
        for action in azioni:
            self._publish_action(action)
        if azioni or missioni:
            self._publish_metrics()

    def reset_tools(self) -> None:
        """Azzera i soli strumenti **dichiarati**, alla caduta del canale.

        Le statistiche osservate restano: descrivono la sessione, non il
        backend, e cancellarle renderebbe la Metrics Dashboard inutile proprio
        dopo una disconnessione — cioè quando la si guarda.
        """
        with self._lock:
            for tool in self._tools.values():
                tool.declared = False
        self._publish_tools()

    # ------------------------------------------------------------------ #
    # Consultazione
    # ------------------------------------------------------------------ #

    def active_missions(self) -> tuple[Mission, ...]:
        with self._lock:
            return tuple(self._missions.values())

    def mission_history(self) -> tuple[Mission, ...]:
        with self._lock:
            return tuple(reversed(self._mission_history))

    def active_actions(self) -> tuple[Action, ...]:
        """Azioni in coda, in attesa di conferma o in esecuzione, in ordine."""
        with self._lock:
            return tuple(sorted(self._actions.values(), key=lambda a: a.queued_at))

    def action_history(self) -> tuple[Action, ...]:
        with self._lock:
            return tuple(reversed(self._action_history))

    def actions_of(self, mission_id: str) -> tuple[Action, ...]:
        """Azioni di una missione, attive e concluse."""
        with self._lock:
            mission = self._missions.get(mission_id)
            ids = set(mission.action_ids) if mission else set()
            if not ids:
                for storica in self._mission_history:
                    if storica.mission_id == mission_id:
                        ids = set(storica.action_ids)
                        break
            attive = [a for a in self._actions.values() if a.action_id in ids]
            concluse = [a for a in self._action_history if a.action_id in ids]
        return tuple(sorted(attive + concluse, key=lambda a: a.queued_at))

    def pending_confirmations(self) -> tuple[ConfirmRequest, ...]:
        with self._lock:
            return tuple(r for r in self._confirms.values() if not r.resolved)

    def tools(self) -> tuple[ToolInfo, ...]:
        with self._lock:
            return tuple(sorted(self._tools.values(), key=lambda t: t.display_name.lower()))

    # ------------------------------------------------------------------ #
    # Metriche
    # ------------------------------------------------------------------ #

    def metrics(self) -> OperationsMetrics:
        """Metriche derivate, per la Metrics Dashboard."""
        now = time.monotonic()
        with self._lock:
            attive = list(self._actions.values())
            storiche = list(self._action_history)
            missioni_attive = len(self._missions)
            missioni_storiche = list(self._mission_history)
            recenti = [t for t in self._completions if now - t <= _THROUGHPUT_WINDOW]

        concluse = [a for a in storiche if a.status is not ActionStatus.UNKNOWN]
        riuscite = sum(1 for a in concluse if a.succeeded)
        durate = sorted(
            d for a in concluse if (d := a.backend_duration_ms or a.wall_duration_ms) is not None
        )
        attese = [w for a in storiche if (w := a.queue_wait_ms) is not None]

        return OperationsMetrics(
            missions_active=missioni_attive,
            missions_completed=sum(
                1 for m in missioni_storiche if m.status is MissionStatus.COMPLETED
            ),
            missions_failed=sum(1 for m in missioni_storiche if m.status is MissionStatus.FAILED),
            missions_unknown=sum(1 for m in missioni_storiche if m.status is MissionStatus.UNKNOWN),
            queue_depth=sum(1 for a in attive if a.status is ActionStatus.QUEUED),
            running=sum(1 for a in attive if a.status is ActionStatus.RUNNING),
            awaiting_confirmation=sum(
                1 for a in attive if a.status is ActionStatus.WAITING_CONFIRMATION
            ),
            actions_completed=len(concluse),
            success_rate=(riuscite / len(concluse)) if concluse else None,
            avg_duration_ms=(sum(durate) / len(durate)) if durate else None,
            p95_duration_ms=durate[min(len(durate) - 1, int(len(durate) * 0.95))]
            if durate
            else None,
            avg_queue_wait_ms=(sum(attese) / len(attese)) if attese else None,
            throughput_per_min=len(recenti) / (_THROUGHPUT_WINDOW / 60.0) if recenti else 0.0,
            tools_used=sum(1 for t in self._tools.values() if t.invocations),
            tools_declared=sum(1 for t in self._tools.values() if t.declared),
        )

    # ------------------------------------------------------------------ #
    # Pubblicazione
    # ------------------------------------------------------------------ #

    def _publish_mission(self, mission: Mission) -> None:
        with self._lock:
            azioni = dict(self._actions)
        self._bus.publish(
            EventType.MISSION_CHANGED,
            MissionSnapshot(
                mission_id=mission.mission_id,
                title=mission.title,
                goal=mission.goal,
                status=mission.status.value,
                progress=mission.derived_progress(azioni),
                progress_is_derived=mission.progress is None,
                summary=mission.summary,
                error=mission.error,
                parent_id=mission.parent_id,
                duration_s=mission.duration_s,
                action_count=len(mission.action_ids),
            ),
            source="missions",
        )

    def _publish_action(self, action: Action) -> None:
        self._bus.publish(
            EventType.ACTION_CHANGED,
            ActionSnapshot(
                action_id=action.action_id,
                mission_id=action.mission_id,
                tool=action.tool,
                title=action.title,
                status=action.status.value,
                risk=action.risk.value,
                progress=action.progress,
                note=action.note,
                args_preview=action.args_preview,
                result_preview=action.result_preview,
                error=action.error,
                duration_ms=action.backend_duration_ms or action.wall_duration_ms,
                queue_wait_ms=action.queue_wait_ms,
            ),
            source="missions",
        )

    def _publish_tools(self) -> None:
        self._bus.publish(
            EventType.TOOLS_UPDATED,
            ToolsSnapshot(
                declared=tuple(t.name for t in self._tools.values() if t.declared),
                observed=tuple(t.name for t in self._tools.values() if t.invocations),
            ),
            source="missions",
        )

    def _publish_metrics(self) -> None:
        self._bus.publish(EventType.OPERATIONS_METRICS, self.metrics(), source="missions")

    @staticmethod
    def _confirm_snapshot(request: ConfirmRequest) -> ConfirmSnapshot:
        return ConfirmSnapshot(
            request_id=request.request_id,
            action_id=request.action_id,
            title=request.title,
            detail=request.detail,
            risk=request.risk.value,
            options=request.options,
            seconds_left=request.seconds_left,
            resolved=request.resolved,
            approved=request.approved,
        )

    # ------------------------------------------------------------------ #

    def clear(self) -> None:
        """Azzera tutto. Usato nei test fra un caso e l'altro."""
        with self._lock:
            self._missions.clear()
            self._actions.clear()
            self._confirms.clear()
            self._tools.clear()
            self._mission_history.clear()
            self._action_history.clear()
            self._completions.clear()
