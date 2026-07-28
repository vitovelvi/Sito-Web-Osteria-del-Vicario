"""Vista del traffico JCP: le buste effettivamente scambiate.

È il pannello che distingue "l'evento non è arrivato alla GUI" da "il backend
non l'ha mai inviato" — la prima domanda che ci si pone quando qualcosa non
funziona, e quella a cui senza questo strumento si risponde per congetture.

Mostra il **JCP dopo l'adapter**, non il dialetto grezzo del backend: è il
livello a cui il resto dell'applicazione ragiona. Per verificare la traduzione
in sé ci sono i test dell'adapter.
"""

from __future__ import annotations

from typing import Any, Final

from jarvis_protocol.envelope import Envelope

from core.errors import safe_slot
from core.qtcompat import Qt, QtGui, QtWidgets
from ui.theme.theme import Theme

__all__ = ["TrafficView"]

_MAX_ROWS: Final[int] = 1000

#: I messaggi di stream sono numerosissimi e raramente interessanti uno per uno.
_NOISY_PREFIXES: Final[tuple[str, ...]] = ("stream.data", "link.ping", "link.pong")


class TrafficView(QtWidgets.QWidget):
    """Elenco delle buste JCP in ingresso e in uscita."""

    def __init__(
        self,
        network: Any,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._network = network
        self._theme = theme
        self._show_noise = False

        self._noise = QtWidgets.QCheckBox("Mostra stream e heartbeat")
        self._noise.setToolTip(
            "I blocchi di stream e i ping sono decine al secondo: nascosti per "
            "default, perché coprirebbero tutto il resto."
        )
        self._noise.toggled.connect(self._on_noise_toggled)

        self._list = QtWidgets.QListWidget()
        self._list.setUniformItemSizes(True)
        self._list.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))
        self._list.currentItemChanged.connect(self._on_current_changed)

        self._detail = QtWidgets.QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))
        self._detail.setMaximumHeight(190)
        self._detail.setPlaceholderText("Seleziona una busta per vederne il JSON.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._noise)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._detail)

        self.reload()
        # Il segnale può mancare o essere nullo (servizi ridotti, doppioni nei
        # test): si verifica che sia davvero connettibile invece di fidarsi del
        # solo nome dell'attributo.
        signal = getattr(network, "traffic", None)
        if signal is not None and callable(getattr(signal, "connect", None)):
            signal.connect(self._on_traffic)

    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        """Ricostruisce la vista dallo storico del servizio di rete."""
        self._list.clear()
        if self._network is None:
            return
        for _, direction, envelope in self._network.traffic_history():
            self._append(direction, envelope)

    @safe_slot("devtools.traffic")
    def _on_traffic(self, direction: str, envelope: object) -> None:
        if isinstance(envelope, Envelope):
            self._append(direction, envelope)

    def _append(self, direction: str, envelope: Envelope) -> None:
        if not self._show_noise and envelope.type.startswith(_NOISY_PREFIXES):
            return

        arrow = "→" if direction == ">" else "←"
        item = QtWidgets.QListWidgetItem(
            f"{arrow}  {envelope.type:<22} {envelope.id[-8:]}"
            + (f"  ↩{envelope.corr[-8:]}" if envelope.corr else "")
        )
        item.setData(Qt.ItemDataRole.UserRole, envelope)
        token = "accent.core" if direction == ">" else "state.success"
        item.setForeground(QtGui.QBrush(self._theme.color(token)))
        self._list.addItem(item)

        while self._list.count() > _MAX_ROWS:
            self._list.takeItem(0)

        scrollbar = self._list.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 4:
            self._list.scrollToBottom()

    @safe_slot("devtools.traffic")
    def _on_noise_toggled(self, checked: bool) -> None:
        self._show_noise = checked
        self.reload()

    @safe_slot("devtools.traffic")
    def _on_current_changed(self, current: QtWidgets.QListWidgetItem | None) -> None:
        if current is None:
            return
        envelope = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(envelope, Envelope):
            import json

            self._detail.setPlainText(
                json.dumps(envelope.to_wire(), indent=2, ensure_ascii=False)
            )
