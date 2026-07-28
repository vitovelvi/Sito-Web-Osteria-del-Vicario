"""Monitor dei servizi e diagnostica in tempo reale.

Entrambi i pannelli si aggiornano a **1 Hz e solo quando la console è
visibile**: una finestra di diagnostica che consuma CPU per disegnare numeri che
nessuno guarda contraddirebbe il lavoro fatto sul budget di frame.
"""

from __future__ import annotations

from typing import Any, Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType, ServiceStatus
from core.frameclock import FrameClock
from core.qtcompat import Qt, QtGui, QtWidgets
from core.registry import ServiceRegistry
from core.service import ServiceState
from core.state.manager import StateManager
from ui.theme.theme import Theme

__all__ = ["DiagnosticsPanel", "ServiceMonitor"]

#: Colore per stato di servizio.
_STATE_COLOR: Final[dict[str, str]] = {
    ServiceState.RUNNING.value: "state.success",
    ServiceState.STARTING.value: "state.connecting",
    ServiceState.DEGRADED.value: "state.warning",
    ServiceState.FAILED.value: "state.error",
    ServiceState.STOPPED.value: "text.muted",
    ServiceState.DISABLED.value: "text.muted",
}

_STATE_LABEL: Final[dict[str, str]] = {
    ServiceState.RUNNING.value: "operativo",
    ServiceState.STARTING.value: "in avvio",
    ServiceState.DEGRADED.value: "degradato",
    ServiceState.FAILED.value: "guasto",
    ServiceState.STOPPED.value: "fermo",
    ServiceState.DISABLED.value: "disattivato",
}


class ServiceMonitor(QtWidgets.QWidget):
    """Stato di salute dei servizi registrati."""

    def __init__(
        self,
        registry: ServiceRegistry,
        bus: EventBus,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._theme = theme

        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Servizio", "Stato", "Riavvii", "Dettaglio"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Stretch)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._table)

        # L'aggiornamento a evento è immediato; il periodico copre i servizi che
        # degradano senza pubblicare nulla (un thread che si ferma in silenzio).
        self._subscription: Subscription = bus.subscribe(
            EventType.SERVICE_STATUS_CHANGED, self._on_status
        )
        self.refresh()

    @safe_slot("devtools.services")
    def _on_status(self, _: Event[ServiceStatus]) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Ricostruisce la tabella dallo stato reale dei servizi."""
        report = self._registry.health_report()
        self._table.setRowCount(len(report))

        for row, (name, health) in enumerate(sorted(report.items())):
            state = health.state.value
            self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))

            status = QtWidgets.QTableWidgetItem(_STATE_LABEL.get(state, state))
            status.setForeground(
                QtGui.QBrush(self._theme.color(_STATE_COLOR.get(state, "text.secondary")))
            )
            self._table.setItem(row, 1, status)

            restarts = QtWidgets.QTableWidgetItem(str(self._registry.restart_count(name)))
            restarts.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 2, restarts)

            self._table.setItem(row, 3, QtWidgets.QTableWidgetItem(health.detail or "—"))


class DiagnosticsPanel(QtWidgets.QWidget):
    """Metriche di rendering, bus, stato e rete, in tempo reale."""

    def __init__(
        self,
        bus: EventBus,
        state: StateManager,
        clock: FrameClock,
        theme: Theme,
        network: Any | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._state = state
        self._clock = clock
        self._network = network

        self._text = QtWidgets.QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._text)

    def refresh(self) -> None:
        """Ricalcola e ridisegna le metriche."""
        # La posizione della barra si conserva: senza, ogni aggiornamento
        # riporterebbe la vista in cima mentre si sta leggendo il fondo.
        scroll = self._text.verticalScrollBar().value()
        self._text.setPlainText("\n".join(self._sections()))
        self._text.verticalScrollBar().setValue(scroll)

    def _sections(self) -> list[str]:
        lines: list[str] = []

        clock = self._clock.metrics()
        lines.append("── Rendering ──")
        lines.append(f"  FPS effettivi      {clock['fps']:.1f} / {clock['target_fps']:.0f}")
        lines.append(f"  Tempo per frame    {clock['frame_ms']:.2f} ms")
        lines.append(
            f"  Carico             {clock['load']:.2f}"
            + ("   ⚠ sopra il budget" if clock["load"] > 1.1 else "")
        )
        lines.append(f"  Frame disegnati    {clock['frames']:.0f}")
        lines.append(f"  Blocchi (hitch)    {clock['hitches']:.0f}")

        snapshot = self._state.snapshot
        lines.append("")
        lines.append("── Stato ──")
        lines.append(f"  Applicazione       {snapshot.app.value}")
        lines.append(f"  Canale             {snapshot.link.value}")
        lines.append(f"  Assistente         {snapshot.agent.value}")
        lines.append(f"  Modalità visiva    {self._state.visual_mode.value}")
        errors = self._state.active_errors()
        if errors:
            lines.append(f"  Condizioni attive  {len(errors)}")
            for condition in errors[:5]:
                lines.append(
                    f"    [{condition.severity.name}] "
                    f"{condition.source}: {condition.message}"
                )
        else:
            lines.append("  Condizioni attive  nessuna")

        metrics = self._bus.metrics()
        lines.append("")
        lines.append("── Event bus ──")
        lines.append(f"  Pubblicati         {metrics['published']}")
        lines.append(f"  Consegnati         {metrics['delivered']}")
        lines.append(f"  Sottoscrizioni     {metrics['subscriptions']}")
        lines.append(
            f"  Errori negli handler {metrics['handler_errors']}"
            + ("   ⚠" if metrics["handler_errors"] else "")
        )
        dead = metrics["dead_letters"]
        if dead:
            # Un evento che nessuno ascolta è quasi sempre un sintomo, non una
            # scelta: vale la pena vederlo in cima alla diagnostica.
            lines.append("  Eventi senza ascoltatori:")
            for key, count in sorted(dead.items(), key=lambda kv: -kv[1])[:8]:
                lines.append(f"    {key:<34} {count}")
        else:
            lines.append("  Eventi senza ascoltatori  nessuno")

        if self._network is not None:
            lines.append("")
            lines.append("── Rete ──")
            try:
                for key, value in self._network.diagnostics().items():
                    lines.append(f"  {key:<18} {self._render(value)}")
            except Exception as exc:
                lines.append(f"  (non disponibile: {exc})")

        return lines

    @staticmethod
    def _render(value: Any) -> str:
        if isinstance(value, dict):
            return ", ".join(f"{k}={v}" for k, v in value.items()) or "—"
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "sì" if value else "no"
        return str(value)
