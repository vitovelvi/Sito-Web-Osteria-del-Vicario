"""Developer Console: timeline, ispettore, servizi, diagnostica, traffico.

È uno strumento di sviluppo e manutenzione, non una funzione per l'utente
finale: finestra separata, richiamata con **F12**, chiusa senza conseguenze.

Due scelte deliberate:

* **non è modale e non è figlia della finestra principale** — deve poter stare
  su un secondo monitor mentre si usa Jarvis sul primo;
* **si aggiorna solo quando è visibile**. Una console di diagnostica che
  consuma CPU mentre è chiusa contraddirebbe il lavoro fatto sul budget di
  frame, e sarebbe il primo posto in cui cercare un rallentamento misterioso.
"""

from __future__ import annotations

from typing import Any, Final

from core.errors import safe_slot
from core.eventbus import EventBus
from core.frameclock import FrameClock
from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from core.registry import ServiceRegistry
from core.state.manager import StateManager
from ui.devtools.monitors import DiagnosticsPanel, ServiceMonitor
from ui.devtools.session import SessionPanel
from ui.devtools.timeline import EventInspector, EventTimeline
from ui.devtools.traffic import TrafficView
from ui.ops import MetricsDashboard, ToolInspector
from ui.theme.theme import Theme

__all__ = ["DeveloperConsole"]

_log = get_logger(LogCategory.UI, "devtools")

#: Frequenza di aggiornamento dei pannelli periodici.
_REFRESH_MS: Final[int] = 1000


class DeveloperConsole(QtWidgets.QWidget):
    """Finestra degli strumenti di sviluppo."""

    def __init__(
        self,
        bus: EventBus,
        state: StateManager,
        clock: FrameClock,
        registry: ServiceRegistry,
        theme: Theme,
        network: Any | None = None,
        missions: Any | None = None,
    ) -> None:
        super().__init__(None)
        self._theme = theme
        self.setWindowTitle("J.A.R.V.I.S. — Developer Console")
        self.setObjectName("rootSurface")
        self.resize(1080, 680)

        self._timeline = EventTimeline(bus, theme, self)
        self._inspector = EventInspector(theme, self)
        self._timeline.selected.connect(self._inspector.show_event)

        self._services = ServiceMonitor(registry, bus, theme, self)
        self._diagnostics = DiagnosticsPanel(bus, state, clock, theme, network, self)
        self._traffic = TrafficView(network, theme, self) if network is not None else None

        events_page = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
        events_page.addWidget(self._wrap(self._timeline, "Timeline"))
        events_page.addWidget(self._wrap(self._inspector, "Event Inspector"))
        events_page.setStretchFactor(0, 3)
        events_page.setStretchFactor(1, 2)

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.addTab(events_page, "Eventi")
        self._tabs.addTab(self._wrap(self._services, "Servizi"), "Servizi")
        self._tabs.addTab(self._wrap(self._diagnostics, "Diagnostica"), "Diagnostica")

        # Tool Inspector e Metrics Dashboard sono strumenti di osservazione del
        # backend: stanno accanto alla diagnostica, non nella finestra
        # principale, dove l'utente vuole vedere cosa succede, non misurarlo.
        self._tools = ToolInspector(bus, missions, theme, self) if missions else None
        self._metrics = MetricsDashboard(bus, missions, theme, self) if missions else None
        if self._tools is not None:
            self._tabs.addTab(self._wrap(self._tools, "Tool Inspector"), "Strumenti")
        if self._metrics is not None:
            self._tabs.addTab(self._wrap(self._metrics, "Metrics Dashboard"), "Metriche")

        # Sessione: registrazione, replay, conformita'. Richiede la rete —
        # senza canale non c'e' nulla da registrare ne' da verificare.
        self._session = SessionPanel(network, theme, self) if network is not None else None
        if self._session is not None:
            self._tabs.addTab(self._wrap(self._session, "Sessione"), "Sessione")
        if self._traffic is not None:
            self._tabs.addTab(self._wrap(self._traffic, "Traffico JCP"), "Traffico JCP")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._tabs)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)

    # ------------------------------------------------------------------ #

    def _wrap(self, widget: QtWidgets.QWidget, title: str) -> QtWidgets.QWidget:
        """Incornicia un pannello con il proprio titolo."""
        frame = QtWidgets.QFrame()
        frame.setProperty("role", "panel")

        label = QtWidgets.QLabel(title)
        label.setProperty("role", "hud")

        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return frame

    @safe_slot("devtools.console")
    def _refresh(self) -> None:
        """Aggiorna solo il pannello effettivamente in vista.

        Ricalcolare tutti i pannelli a ogni tick sprecherebbe lavoro su quelli
        nascosti dietro le schede.
        """
        current = self._tabs.currentIndex()
        if self._tabs.tabText(current) == "Servizi":
            self._services.refresh()
        elif self._tabs.tabText(current) == "Diagnostica":
            self._diagnostics.refresh()

    # ------------------------------------------------------------------ #
    # Visibilità
    # ------------------------------------------------------------------ #

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._timer.start()
        self._services.refresh()
        self._diagnostics.refresh()
        _log.info("Developer Console aperta")
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def toggle(self) -> None:
        """Apre o chiude la console."""
        if self.isVisible():
            self.hide()
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Esc e F12 chiudono la console."""
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F12):
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)
