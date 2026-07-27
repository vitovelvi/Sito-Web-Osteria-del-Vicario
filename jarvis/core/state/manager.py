"""State manager: unico proprietario dello stato globale.

Nessun altro modulo tiene una copia degli stati. Chi ha bisogno di sapere si
sottoscrive agli eventi; chi ha bisogno di cambiare chiama questi metodi. E' la
regola che impedisce alle GUI di sviluppare, negli anni, cinque verita' parallele
su "cosa sta facendo l'assistente".

Due meccanismi meritano attenzione:

**Autorita' del backend.** La fonte di verita' di :class:`AgentState` e'
OpenClaw. La GUI puo' anticipare (``authoritative=False``) per far sembrare
istantanea la reazione a un gesto — premo il microfono e il nucleo reagisce
subito — ma deve **riconciliarsi**: se il backend non conferma entro il timeout,
si torna indietro e lo si dice. Senza questa regola scritta, GUI e backend
divergono e nessuno sa chi ha ragione.

**Errore come condizione.** Gli errori non sono stati: sono fatti sovrapposti,
uno per sorgente, ciascuno con la propria gravita' e scadenza.
"""

from __future__ import annotations

import threading
import time
from typing import Final

from core.errors import ErrorCondition, ErrorSeverity
from core.eventbus import EventBus
from core.events import (
    ErrorRaised,
    EventType,
    NotificationRequest,
    RejectedTransition,
    StateChange,
    VisualModeChange,
)
from core.logging_setup import LogCategory, get_logger
from core.qtcompat import QtCore
from core.state.machines import AgentState, AppState, LinkState, VisualMode
from core.state.resolver import StateSnapshot, resolve_visual_mode, transition_duration
from core.state.transitions import (
    AGENT_TRANSITIONS,
    APP_TRANSITIONS,
    LINK_TRANSITIONS,
    is_allowed,
)

__all__ = ["StateManager"]

_log = get_logger(LogCategory.STATE)

#: Tempo entro cui il backend deve confermare uno stato anticipato dalla GUI.
_DEFAULT_RECONCILE_MS: Final[int] = 2500

#: Durata del lampo di conferma dopo un'operazione riuscita.
_SUCCESS_FLASH_S: Final[float] = 0.9

#: Frequenza con cui si ripuliscono le condizioni d'errore scadute.
_SWEEP_INTERVAL_MS: Final[int] = 1000


class StateManager(QtCore.QObject):
    """Detiene e fa evolvere lo stato globale, pubblicando ogni cambiamento."""

    def __init__(
        self,
        bus: EventBus,
        parent: QtCore.QObject | None = None,
        *,
        strict: bool = False,
    ) -> None:
        """
        :param bus: bus su cui pubblicare i cambiamenti.
        :param strict: in sviluppo, solleva su transizione illegale invece di
            limitarsi a rifiutarla. In produzione resta sempre disattivo: un
            backend che sbaglia non deve poter chiudere l'interfaccia.
        """
        super().__init__(parent)
        self._bus = bus
        self._strict = strict
        self._lock = threading.RLock()

        self._app = AppState.BOOTING
        self._link = LinkState.OFFLINE
        self._agent = AgentState.IDLE
        self._errors: dict[str, ErrorCondition] = {}
        self._success_until = 0.0

        self._visual = VisualMode.BOOT

        # Riconciliazione dello stato anticipato.
        self._pending_agent: AgentState | None = None
        self._agent_before_optimistic: AgentState | None = None
        self._reconcile_timer = QtCore.QTimer(self)
        self._reconcile_timer.setSingleShot(True)
        self._reconcile_timer.timeout.connect(self._on_reconcile_timeout)

        # Scadenza automatica delle condizioni d'errore con TTL.
        self._sweep_timer = QtCore.QTimer(self)
        self._sweep_timer.setInterval(_SWEEP_INTERVAL_MS)
        self._sweep_timer.timeout.connect(self._sweep_errors)
        self._sweep_timer.start()

    # ------------------------------------------------------------------ #
    # Lettura
    # ------------------------------------------------------------------ #

    @property
    def snapshot(self) -> StateSnapshot:
        """Fotografia coerente e immutabile dello stato corrente."""
        with self._lock:
            return StateSnapshot(
                app=self._app,
                link=self._link,
                agent=self._agent,
                error=self._dominant_error(),
                success_until=self._success_until,
            )

    @property
    def visual_mode(self) -> VisualMode:
        """Modalita' visiva attualmente risolta."""
        with self._lock:
            return self._visual

    @property
    def app_state(self) -> AppState:
        with self._lock:
            return self._app

    @property
    def link_state(self) -> LinkState:
        with self._lock:
            return self._link

    @property
    def agent_state(self) -> AgentState:
        with self._lock:
            return self._agent

    def active_errors(self) -> tuple[ErrorCondition, ...]:
        """Condizioni d'errore attive, dalla piu' grave alla meno grave."""
        with self._lock:
            now = time.monotonic()
            active = [c for c in self._errors.values() if not c.is_expired(now)]
        return tuple(sorted(active, key=lambda c: c.severity, reverse=True))

    # ------------------------------------------------------------------ #
    # Scrittura
    # ------------------------------------------------------------------ #

    def set_app_state(self, target: AppState, *, reason: str | None = None) -> bool:
        """Aggiorna il ciclo di vita dell'applicazione."""
        return self._transition("app", target, reason=reason)

    def set_link_state(self, target: LinkState, *, reason: str | None = None) -> bool:
        """Aggiorna lo stato del canale verso il backend."""
        return self._transition("link", target, reason=reason)

    def set_agent_state(
        self,
        target: AgentState,
        *,
        authoritative: bool = True,
        reason: str | None = None,
        reconcile_ms: int = _DEFAULT_RECONCILE_MS,
    ) -> bool:
        """Aggiorna lo stato dell'assistente.

        :param authoritative: ``True`` per gli eventi provenienti da OpenClaw,
            che sono verita'. ``False`` per l'anticipazione locale a un gesto
            dell'utente, che va confermata.
        :param reconcile_ms: finestra entro cui attendere la conferma quando
            l'aggiornamento non e' autorevole.
        """
        with self._lock:
            previous = self._agent

        # La conferma del backend va elaborata **prima** di sapere se lo stato
        # cambia: il caso piu' frequente e' proprio quello in cui il backend
        # conferma uno stato che la GUI aveva gia' anticipato, quindi non c'e'
        # alcuna transizione da applicare ma l'attesa va comunque chiusa.
        # Senza questo ordine, l'anticipazione verrebbe annullata dal timeout
        # nonostante la conferma sia arrivata.
        if authoritative:
            self._reconcile_timer.stop()
            with self._lock:
                self._pending_agent = None
                self._agent_before_optimistic = None
            return self._transition("agent", target, reason=reason)

        if not self._transition("agent", target, reason=reason):
            return False

        with self._lock:
            self._pending_agent = target
            self._agent_before_optimistic = previous
        _log.debug("Stato '%s' anticipato localmente, attesa conferma", target.value)
        self._reconcile_timer.start(reconcile_ms)
        return True

    def _on_reconcile_timeout(self) -> None:
        """Il backend non ha confermato: si annulla l'anticipazione."""
        with self._lock:
            pending = self._pending_agent
            fallback = self._agent_before_optimistic
            self._pending_agent = None
            self._agent_before_optimistic = None

        if pending is None or fallback is None:
            return

        _log.warning(
            "Stato '%s' non confermato dal backend entro il timeout: ripristino '%s'",
            pending.value,
            fallback.value,
        )
        self._transition("agent", fallback, reason="riconciliazione: nessuna conferma")
        self._bus.publish(
            EventType.NOTIFICATION_REQUESTED,
            NotificationRequest(
                title="Nessuna risposta da Jarvis",
                body="Il comando non è stato confermato dal backend.",
                kind="warning",
            ),
            source="state",
        )

    def _transition(
        self, machine: str, target: object, *, reason: str | None = None
    ) -> bool:
        """Applica una transizione se la tabella la consente.

        :returns: ``True`` se lo stato e' effettivamente cambiato.
        """
        with self._lock:
            if machine == "app":
                current, table = self._app, APP_TRANSITIONS
            elif machine == "link":
                current, table = self._link, LINK_TRANSITIONS
            else:
                current, table = self._agent, AGENT_TRANSITIONS

            if not is_allowed(table, current, target):  # type: ignore[arg-type]
                message = (
                    f"Transizione non consentita su '{machine}': "
                    f"{current.value} → {target.value}"  # type: ignore[attr-defined]
                )
                if self._strict:
                    raise ValueError(message)
                _log.warning("%s", message)
                self._bus.publish(
                    EventType.STATE_TRANSITION_REJECTED,
                    RejectedTransition(
                        machine=machine,
                        current=current.value,
                        requested=target.value,  # type: ignore[attr-defined]
                        reason=message,
                    ),
                    source="state",
                )
                return False

            if current == target:
                return False

            if machine == "app":
                self._app = target  # type: ignore[assignment]
            elif machine == "link":
                self._link = target  # type: ignore[assignment]
            else:
                self._agent = target  # type: ignore[assignment]

        change = StateChange(
            machine=machine,
            previous=current.value,
            current=target.value,  # type: ignore[attr-defined]
            reason=reason,
        )
        _log.info("%s: %s → %s", machine, change.previous, change.current)

        event_type = {
            "app": EventType.APP_STATE_CHANGED,
            "link": EventType.LINK_STATE_CHANGED,
            "agent": EventType.AGENT_STATE_CHANGED,
        }[machine]

        # Il payload di LINK_STATE_CHANGED e' LinkStatus, non StateChange: il
        # canale porta con se' endpoint e tentativo, che a chi ascolta servono.
        if machine == "link":
            from core.events import LinkStatus

            self._bus.publish(
                event_type,
                LinkStatus(state=change.current, reason=reason),
                source="state",
            )
        else:
            self._bus.publish(event_type, change, source="state")

        self._recompute_visual()
        return True

    # ------------------------------------------------------------------ #
    # Condizioni d'errore
    # ------------------------------------------------------------------ #

    def raise_error(self, condition: ErrorCondition) -> None:
        """Registra o aggiorna la condizione d'errore di una sorgente.

        Una sorgente ha al massimo una condizione attiva: un servizio che
        fallisce ripetutamente aggiorna la propria, non ne accumula centinaia.
        """
        with self._lock:
            self._errors[condition.source] = condition

        _log.log(
            {
                ErrorSeverity.INFO: 20,
                ErrorSeverity.WARNING: 30,
                ErrorSeverity.ERROR: 40,
                ErrorSeverity.CRITICAL: 50,
            }[condition.severity],
            "Condizione da '%s': %s",
            condition.source,
            condition.message,
        )
        self._bus.publish(EventType.ERROR, ErrorRaised(condition), source="state")
        self._recompute_visual()

    def clear_error(self, source: str) -> None:
        """Rimuove la condizione di una sorgente, se presente."""
        with self._lock:
            condition = self._errors.pop(source, None)
        if condition is None:
            return
        _log.info("Condizione risolta su '%s'", source)
        self._bus.publish(EventType.ERROR_CLEARED, ErrorRaised(condition), source="state")
        self._recompute_visual()

    def _sweep_errors(self) -> None:
        """Rimuove periodicamente le condizioni scadute."""
        now = time.monotonic()
        with self._lock:
            expired = [s for s, c in self._errors.items() if c.is_expired(now)]
        for source in expired:
            self.clear_error(source)
        # Anche senza scadenze, il lampo di conferma va spento a tempo.
        if self._success_until and now >= self._success_until:
            with self._lock:
                self._success_until = 0.0
            self._recompute_visual()

    def _dominant_error(self) -> ErrorCondition | None:
        """Condizione attiva piu' grave, o ``None``."""
        now = time.monotonic()
        active = [c for c in self._errors.values() if not c.is_expired(now)]
        if not active:
            return None
        return max(active, key=lambda c: (c.severity, c.created_at))

    # ------------------------------------------------------------------ #
    # Conferma visiva
    # ------------------------------------------------------------------ #

    def flash_success(self, duration: float = _SUCCESS_FLASH_S) -> None:
        """Mostra il lampo azzurro di conferma per una durata breve."""
        with self._lock:
            self._success_until = time.monotonic() + duration
        self._recompute_visual()

    # ------------------------------------------------------------------ #
    # Risoluzione visiva
    # ------------------------------------------------------------------ #

    def _recompute_visual(self) -> None:
        """Ricalcola la modalita' visiva e la pubblica se e' cambiata."""
        resolved = resolve_visual_mode(self.snapshot)
        with self._lock:
            previous = self._visual
            if resolved is previous:
                return
            self._visual = resolved

        duration = transition_duration(previous, resolved)
        _log.debug("Modalità visiva: %s → %s (%d ms)", previous.value, resolved.value, duration)
        self._bus.publish(
            EventType.VISUAL_MODE_CHANGED,
            VisualModeChange(
                mode=resolved.value, previous=previous.value, transition_ms=duration
            ),
            source="state",
        )

    def shutdown(self) -> None:
        """Ferma i timer interni. Va chiamata alla chiusura dell'applicazione."""
        self._reconcile_timer.stop()
        self._sweep_timer.stop()
