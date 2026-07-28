"""Tool Inspector: cosa il backend dichiara di saper fare, e cosa usa davvero.

Le due informazioni hanno origine diversa e restano distinte:

* **dichiarato** — arriva da ``tool.registry``. Uno strumento dichiarato e mai
  usato è normale;
* **osservato** — conteggi e durate misurati dall'interfaccia. Uno strumento
  usato ma **non dichiarato** è invece un segnale: o il registro è incompleto,
  o il backend sta facendo qualcosa che non ha annunciato. In entrambi i casi
  vale la pena vederlo, e per questo compare in evidenza invece di essere
  silenziosamente accorpato.
"""

from __future__ import annotations

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtGui, QtWidgets
from ui.ops.common import RISK_LABEL, RISK_TOKEN, format_duration
from ui.theme.theme import Theme

__all__ = ["ToolInspector"]


class ToolInspector(QtWidgets.QWidget):
    """Registro degli strumenti con le statistiche d'uso."""

    def __init__(
        self,
        bus: EventBus,
        engine: MissionEngine,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._theme = theme

        self._summary = QtWidgets.QLabel("Nessuno strumento dichiarato.")
        self._summary.setProperty("role", "hud")

        self._table = QtWidgets.QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["Strumento", "Categoria", "Rischio", "Usi", "Successo", "Media", "p95"]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for colonna in range(1, 7):
            header.setSectionResizeMode(
                colonna, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
        self._table.currentCellChanged.connect(self._on_selection)

        self._detail = QtWidgets.QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(120)
        self._detail.setPlaceholderText("Seleziona uno strumento per vederne il dettaglio.")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._summary)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._detail)

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.TOOLS_UPDATED, self._on_changed),
            bus.subscribe(EventType.ACTION_CHANGED, self._on_changed),
        ]
        self.refresh()

    @safe_slot("ui.tools")
    def _on_changed(self, _: Event[object]) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Ricostruisce la tabella dallo stato del motore."""
        strumenti = self._engine.tools()
        # Prima i non dichiarati ma usati: sono l'anomalia da notare.
        strumenti = sorted(
            strumenti,
            key=lambda t: (t.declared or not t.invocations, -t.invocations, t.display_name),
        )

        selezionato = self._current_tool_name()
        self._table.setRowCount(len(strumenti))

        for riga, tool in enumerate(strumenti):
            nome = QtWidgets.QTableWidgetItem(tool.display_name)
            nome.setData(Qt.ItemDataRole.UserRole, tool.name)
            if not tool.declared:
                nome.setText(f"{tool.display_name}  ⚠")
                nome.setToolTip(
                    "Usato ma non presente nel registro dichiarato dal backend."
                )
                nome.setForeground(QtGui.QBrush(self._theme.color("state.warning")))
            self._table.setItem(riga, 0, nome)

            self._table.setItem(riga, 1, QtWidgets.QTableWidgetItem(tool.category or "—"))

            rischio = QtWidgets.QTableWidgetItem(RISK_LABEL.get(tool.risk.value, "—"))
            rischio.setForeground(
                QtGui.QBrush(self._theme.color(RISK_TOKEN.get(tool.risk.value, "text.secondary")))
            )
            self._table.setItem(riga, 2, rischio)

            self._table.setItem(riga, 3, QtWidgets.QTableWidgetItem(str(tool.invocations)))

            tasso = tool.success_rate
            cella = QtWidgets.QTableWidgetItem("—" if tasso is None else f"{tasso * 100:.0f}%")
            if tasso is not None and tasso < 0.8:
                cella.setForeground(QtGui.QBrush(self._theme.color("state.error")))
            self._table.setItem(riga, 4, cella)

            media = QtWidgets.QTableWidgetItem(format_duration(tool.average_ms))
            self._table.setItem(riga, 5, media)
            self._table.setItem(riga, 6, QtWidgets.QTableWidgetItem(format_duration(tool.p95_ms)))

            if tool.name == selezionato:
                self._table.selectRow(riga)

        dichiarati = sum(1 for t in strumenti if t.declared)
        usati = sum(1 for t in strumenti if t.invocations)
        non_dichiarati = sum(1 for t in strumenti if t.invocations and not t.declared)
        testo = f"{dichiarati} dichiarati · {usati} usati in questa sessione"
        if non_dichiarati:
            testo += f" · ⚠ {non_dichiarati} usati ma non dichiarati"
        self._summary.setText(testo)

    def _current_tool_name(self) -> str | None:
        item = self._table.item(self._table.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    @safe_slot("ui.tools")
    def _on_selection(self, riga: int, *_: object) -> None:
        item = self._table.item(riga, 0)
        if item is None:
            return
        nome = item.data(Qt.ItemDataRole.UserRole)
        tool = next((t for t in self._engine.tools() if t.name == nome), None)
        if tool is None:
            return

        righe = [
            f"{tool.display_name}  ({tool.name})",
            "",
            tool.description or "Nessuna descrizione dichiarata.",
            "",
            f"Categoria: {tool.category or '—'}    "
            f"Rischio: {RISK_LABEL.get(tool.risk.value, '—')}    "
            f"Nel registro: {'sì' if tool.declared else 'no'}",
            f"Invocazioni: {tool.invocations}    "
            f"riuscite {tool.succeeded}    fallite {tool.failed}    "
            f"negate {tool.denied}    annullate {tool.cancelled}",
            f"Durata media: {format_duration(tool.average_ms)}    "
            f"p95: {format_duration(tool.p95_ms)}",
        ]
        self._detail.setPlainText("\n".join(righe))
