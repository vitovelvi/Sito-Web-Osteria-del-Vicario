"""Action Queue: cosa è in coda, cosa gira, cosa è appena finito.

La coda mostra tre gruppi in un'unica lista, nell'ordine in cui contano:
attesa di conferma, esecuzione, coda. Le azioni concluse scorrono sotto, poche
e in ordine inverso.

Il pulsante di annullamento esiste **solo se il backend dichiara**
``actions.cancel``. Un pulsante che non fa nulla è peggio di un pulsante
assente, perché insegna a non fidarsi dell'interfaccia.
"""

from __future__ import annotations

from typing import Final

from jarvis_protocol.capabilities import Capability
from jarvis_protocol.missions import ActionStatus, MissionType

from core.capabilities import CapabilityManager
from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import ActionSnapshot, EventType
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtCore, QtWidgets
from ui.ops.common import ACTION_LABEL, ACTION_TOKEN, RISK_LABEL, RISK_TOKEN, format_duration
from ui.theme.theme import Theme

__all__ = ["ActionQueue"]

#: Azioni concluse mostrate sotto la coda.
_RECENT_SHOWN: Final[int] = 15

#: Ordine di priorità nella lista.
_ORDER: Final[dict[str, int]] = {
    ActionStatus.WAITING_CONFIRMATION.value: 0,
    ActionStatus.RUNNING.value: 1,
    ActionStatus.QUEUED.value: 2,
}


class ActionQueue(QtWidgets.QWidget):
    """Coda di esecuzione e cronologia recente delle azioni."""

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
        self._engine = engine
        self._capabilities = capabilities
        self._theme = theme
        self._sender = sender

        self._header = QtWidgets.QLabel("Coda vuota")
        self._header.setProperty("role", "hud")

        self._table = QtWidgets.QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Azione", "Strumento", "Stato", ""])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._header)
        layout.addWidget(self._table, 1)

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.ACTION_CHANGED, self._on_action),
            bus.subscribe(EventType.CAPABILITIES_UPDATED, self._on_capabilities),
        ]

        # Le durate delle azioni in corso avanzano da sole: senza un timer, il
        # tempo mostrato resterebbe fermo all'ultimo evento ricevuto.
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.reload)
        self.reload()

    # ------------------------------------------------------------------ #

    def showEvent(self, event) -> None:
        self._timer.start()
        self.reload()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    @safe_slot("ui.queue")
    def _on_action(self, _: Event[ActionSnapshot]) -> None:
        self.reload()

    @safe_slot("ui.queue")
    def _on_capabilities(self, _: Event[object]) -> None:
        self.reload()

    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        """Ricostruisce la tabella dallo stato del motore."""
        attive = sorted(
            self._engine.active_actions(),
            key=lambda a: (_ORDER.get(a.status.value, 9), a.queued_at),
        )
        recenti = self._engine.action_history()[:_RECENT_SHOWN]

        self._table.setRowCount(len(attive) + len(recenti))
        annullabile = self._capabilities.has(Capability.ACTIONS_CANCEL)

        for riga, action in enumerate([*attive, *recenti]):
            self._fill_row(riga, action, annullabile and action.is_active)

        in_coda = sum(1 for a in attive if a.status is ActionStatus.QUEUED)
        in_corso = sum(1 for a in attive if a.status is ActionStatus.RUNNING)
        in_attesa = sum(1 for a in attive if a.status is ActionStatus.WAITING_CONFIRMATION)

        parti = []
        if in_corso:
            parti.append(f"{in_corso} in esecuzione")
        if in_coda:
            parti.append(f"{in_coda} in coda")
        if in_attesa:
            parti.append(f"{in_attesa} in attesa di conferma")
        if not parti:
            parti.append("coda vuota")
        # La cronologia va dichiarata: "coda vuota" sopra una tabella con dentro
        # tre righe fa dubitare di quello che si sta guardando.
        if recenti:
            parti.append(f"{len(recenti)} in cronologia")
        self._header.setText(" · ".join(parti).capitalize())

    def _fill_row(self, riga: int, action, annullabile: bool) -> None:
        titolo = QtWidgets.QTableWidgetItem(action.title)
        dettaglio = [
            f"Strumento: {action.tool}",
            f"Rischio: {RISK_LABEL.get(action.risk.value, '?')}",
        ]
        if action.args_preview:
            dettaglio.append(f"Argomenti: {action.args_preview}")
        if action.error:
            dettaglio.append(f"Errore: {action.error}")
        if action.queue_wait_ms is not None:
            dettaglio.append(f"Attesa in coda: {format_duration(action.queue_wait_ms)}")
        durata_totale = action.backend_duration_ms or action.wall_duration_ms
        if durata_totale is not None:
            dettaglio.append(f"Durata: {format_duration(durata_totale)}")
        titolo.setToolTip("\n".join(dettaglio))
        self._table.setItem(riga, 0, titolo)

        strumento = QtWidgets.QTableWidgetItem(action.tool)
        strumento.setForeground(
            self._theme.color(RISK_TOKEN.get(action.risk.value, "text.secondary"))
        )
        self._table.setItem(riga, 1, strumento)

        stato = ACTION_LABEL.get(action.status.value, action.status.value)
        if action.status is ActionStatus.RUNNING and action.progress is not None:
            stato = f"{stato} {action.progress * 100:.0f}%"
        cella = QtWidgets.QTableWidgetItem(stato)
        # La durata va nel tooltip: in una barra da 400 px la colonna Azione
        # resterebbe con tre caratteri e un'ellissi.
        durata = action.backend_duration_ms or action.wall_duration_ms
        cella.setToolTip(f"Durata: {format_duration(durata)}")
        cella.setForeground(
            self._theme.color(ACTION_TOKEN.get(action.status.value, "text.secondary"))
        )
        self._table.setItem(riga, 2, cella)

        if not annullabile:
            self._table.setCellWidget(riga, 3, None)
            self._table.setItem(riga, 3, QtWidgets.QTableWidgetItem(""))
            return

        pulsante = QtWidgets.QPushButton("Annulla")
        pulsante.setProperty("role", "chrome")
        pulsante.setCursor(Qt.CursorShape.PointingHandCursor)
        pulsante.clicked.connect(lambda _=False, a=action.action_id: self._cancel(a))
        self._table.setCellWidget(riga, 3, pulsante)

    @safe_slot("ui.queue")
    def _cancel(self, action_id: str) -> None:
        """Chiede al backend di annullare un'azione.

        La GUI non annulla nulla da sé: manda la richiesta e attende che il
        backend dichiari il nuovo stato. Segnare l'azione come annullata qui
        significherebbe mostrare un esito che nessuno ha confermato.
        """
        if self._sender is None:
            return
        self._sender.send(MissionType.ACTION_CANCEL, {"action_id": action_id})
