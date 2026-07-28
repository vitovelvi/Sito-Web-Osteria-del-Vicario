"""Barra laterale operativa: missioni sopra, coda sotto.

Compare **solo quando il backend dichiara le capability corrispondenti**. Una
barra vuota accanto a un backend che non gestisce missioni occuperebbe un terzo
della finestra per non dire nulla.
"""

from __future__ import annotations

from jarvis_protocol.capabilities import Capability

from core.capabilities import CapabilityManager
from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtWidgets
from ui.ops.action_queue import ActionQueue
from ui.ops.mission_panel import MissionPanel
from ui.theme.theme import Theme

__all__ = ["OperationsSidebar"]


class OperationsSidebar(QtWidgets.QWidget):
    """Missioni e coda delle azioni, affiancate al nucleo."""

    def __init__(
        self,
        bus: EventBus,
        engine: MissionEngine,
        capabilities: CapabilityManager,
        theme: Theme,
        sender=None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._capabilities = capabilities
        # 400 px: sotto questa soglia le etichette di stato e le durate
        # venivano troncate, e una colonna troncata e' peggio di una assente
        # perche' sembra un dato completo.
        self.setFixedWidth(400)

        self._missions = MissionPanel(bus, engine, theme, self)
        self._queue = ActionQueue(bus, engine, capabilities, theme, sender, self)

        titolo = QtWidgets.QLabel("OPERAZIONI")
        titolo.setProperty("role", "hud")

        coda = QtWidgets.QLabel("CODA DI ESECUZIONE")
        coda.setProperty("role", "hud")

        splitter = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._wrap(titolo, self._missions))
        splitter.addWidget(self._wrap(coda, self._queue))
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 14, 0)
        layout.addWidget(splitter)

        self._subscription: Subscription = bus.subscribe(
            EventType.CAPABILITIES_UPDATED, self._on_capabilities, replay_last=True
        )
        self._apply_visibility()

    @staticmethod
    def _wrap(label: QtWidgets.QLabel, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        frame = QtWidgets.QFrame()
        frame.setProperty("role", "panel")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return frame

    @safe_slot("ui.ops")
    def _on_capabilities(self, _: Event[object]) -> None:
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        """Mostra la barra solo se il backend dichiara missioni o azioni."""
        supportata = self._capabilities.has(Capability.MISSIONS) or self._capabilities.has(
            Capability.ACTIONS
        )
        self.setVisible(supportata and self._wanted)

    _wanted = True

    def set_wanted(self, wanted: bool) -> None:
        """Preferenza dell'utente, indipendente dal supporto del backend."""
        self._wanted = wanted
        self._apply_visibility()

    @property
    def is_wanted(self) -> bool:
        """Cosa ha chiesto l'utente, a prescindere da cosa si vede.

        Distinta dalla visibilita': una barra nascosta perche' il backend non
        dichiara missioni non e' una barra che l'utente ha chiuso, e alla
        connessione con un backend che le dichiara deve tornare come l'aveva
        lasciata.
        """
        return self._wanted

    @property
    def is_supported(self) -> bool:
        return self._capabilities.has(Capability.MISSIONS) or self._capabilities.has(
            Capability.ACTIONS
        )
