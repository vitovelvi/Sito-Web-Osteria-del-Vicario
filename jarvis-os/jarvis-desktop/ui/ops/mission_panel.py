"""Pannello delle missioni: cosa Jarvis sta facendo, e cosa ha fatto.

Ogni missione è una scheda espandibile con le proprie azioni. Due dettagli che
distinguono un pannello utile da un elenco:

* l'avanzamento **dedotto** dalle azioni concluse è mostrato in modo diverso da
  quello dichiarato dal backend. Presentarli uguali significherebbe spacciare
  una stima per un dato;
* le missioni concluse non spariscono: scorrono nella cronologia. La domanda
  "cos'ha fatto poco fa?" è la più frequente, e un pannello che mostra solo il
  presente non sa rispondere.
"""

from __future__ import annotations

from typing import Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import ActionSnapshot, EventType, MissionSnapshot
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtWidgets
from ui.ops.common import (
    ACTION_LABEL,
    ACTION_TOKEN,
    MISSION_LABEL,
    MISSION_TOKEN,
    RISK_LABEL,
    RISK_TOKEN,
    format_duration,
)
from ui.theme.theme import Theme

__all__ = ["MissionPanel"]

#: Missioni concluse mostrate in cronologia.
_HISTORY_SHOWN: Final[int] = 12


class _ActionRow(QtWidgets.QWidget):
    """Riga compatta di un'azione dentro una missione."""

    def __init__(self, theme: Theme, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        self._status = QtWidgets.QLabel("•")
        self._status.setFixedWidth(12)
        self._title = QtWidgets.QLabel()
        self._title.setWordWrap(True)
        self._meta = QtWidgets.QLabel()
        self._meta.setProperty("role", "muted")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 2, 4, 2)
        layout.setSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._title, 1)
        layout.addWidget(self._meta)

    def update_from(self, action: ActionSnapshot) -> None:
        colore = self._theme.color(ACTION_TOKEN.get(action.status, "text.secondary"))
        self._status.setStyleSheet(f"color: {colore.name()};")
        self._title.setText(action.title)

        parti = [ACTION_LABEL.get(action.status, action.status)]
        if action.duration_ms is not None:
            parti.append(format_duration(action.duration_ms))
        self._meta.setText(" · ".join(parti))
        if action.risk in RISK_LABEL and action.risk != "low":
            # Il rischio si vede dal colore dello stato, non da altro testo:
            # la riga e' stretta e la ridondanza la spezzerebbe su due righe.
            self._meta.setStyleSheet(
                f"color: {self._theme.color(RISK_TOKEN[action.risk]).name()};"
            )

        tooltip = [f"Strumento: {action.tool}"]
        if action.args_preview:
            tooltip.append(f"Argomenti: {action.args_preview}")
        if action.error:
            tooltip.append(f"Errore: {action.error}")
        elif action.result_preview:
            tooltip.append(f"Esito: {action.result_preview}")
        self.setToolTip("\n".join(tooltip))


class _MissionCard(QtWidgets.QFrame):
    """Scheda di una missione, con le sue azioni."""

    def __init__(
        self, mission: MissionSnapshot, theme: Theme, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._rows: dict[str, _ActionRow] = {}
        self.setProperty("role", "panel")

        self._title = QtWidgets.QLabel(mission.title)
        self._title.setProperty("role", "title")
        self._title.setWordWrap(True)

        self._status = QtWidgets.QLabel()
        self._status.setProperty("role", "hud")

        self._bar = QtWidgets.QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        self._bar.setRange(0, 1000)

        self._summary = QtWidgets.QLabel()
        self._summary.setProperty("role", "muted")
        self._summary.setWordWrap(True)
        self._summary.hide()

        self._actions_box = QtWidgets.QVBoxLayout()
        self._actions_box.setContentsMargins(0, 2, 0, 0)
        self._actions_box.setSpacing(1)

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self._title, 1)
        header.addWidget(self._status)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.addLayout(header)
        layout.addWidget(self._bar)
        layout.addWidget(self._summary)
        layout.addLayout(self._actions_box)

        self.update_from(mission)

    def update_from(self, mission: MissionSnapshot) -> None:
        colore = self._theme.color(MISSION_TOKEN.get(mission.status, "text.secondary"))
        etichetta = MISSION_LABEL.get(mission.status, mission.status)
        # La durata sta nel tooltip: in colonna occuperebbe spazio che serve al
        # titolo, che e' l'informazione per cui si guarda la scheda.
        self._status.setText(etichetta)
        self._status.setToolTip(f"Durata: {mission.duration_s:.0f} s")
        self._status.setStyleSheet(f"color: {colore.name()};")
        self._title.setText(mission.title)

        if mission.progress is None:
            self._bar.hide()
        else:
            self._bar.show()
            self._bar.setValue(int(mission.progress * 1000))
            # L'avanzamento dedotto è tratteggiato dall'opacità: si vede che è
            # una stima senza dover leggere una legenda.
            opacita = 0.45 if mission.progress_is_derived else 1.0
            self._bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: rgba("
                f"{colore.red()},{colore.green()},{colore.blue()},{opacita}); "
                f"border-radius: 2px; }}"
                f"QProgressBar {{ background: transparent; border: none; }}"
            )
            self._bar.setToolTip(
                "Avanzamento stimato dalle azioni concluse"
                if mission.progress_is_derived
                else "Avanzamento dichiarato dal backend"
            )

        testo = mission.error or mission.summary or mission.goal
        self._summary.setText(testo or "")
        self._summary.setVisible(bool(testo))

    def update_action(self, action: ActionSnapshot) -> None:
        riga = self._rows.get(action.action_id)
        if riga is None:
            riga = _ActionRow(self._theme, self)
            self._rows[action.action_id] = riga
            self._actions_box.addWidget(riga)
        riga.update_from(action)


class MissionPanel(QtWidgets.QWidget):
    """Missioni attive e cronologia recente."""

    def __init__(
        self,
        bus: EventBus,
        engine: MissionEngine,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._engine = engine
        self._theme = theme
        self._cards: dict[str, _MissionCard] = {}

        self._empty = QtWidgets.QLabel("Nessuna operazione in corso.")
        self._empty.setProperty("role", "muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._column = QtWidgets.QVBoxLayout()
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(8)
        self._column.addWidget(self._empty)
        self._column.addStretch(1)

        container = QtWidgets.QWidget()
        container.setLayout(self._column)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(container)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.MISSION_CHANGED, self._on_mission),
            bus.subscribe(EventType.ACTION_CHANGED, self._on_action),
        ]
        self.reload()

    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        """Ricostruisce dallo stato del motore."""
        for card in self._cards.values():
            card.setParent(None)
        self._cards.clear()

        for mission in self._engine.active_missions():
            self._card_for(mission.mission_id).update_from(self._snapshot(mission))
        for mission in self._engine.mission_history()[:_HISTORY_SHOWN]:
            self._card_for(mission.mission_id).update_from(self._snapshot(mission))
        self._update_empty()

    def _snapshot(self, mission) -> MissionSnapshot:
        return MissionSnapshot(
            mission_id=mission.mission_id,
            title=mission.title,
            status=mission.status.value,
            goal=mission.goal,
            progress=mission.progress,
            progress_is_derived=mission.progress is None,
            summary=mission.summary,
            error=mission.error,
            duration_s=mission.duration_s,
            action_count=len(mission.action_ids),
        )

    def _card_for(self, mission_id: str) -> _MissionCard:
        card = self._cards.get(mission_id)
        if card is not None:
            return card
        card = _MissionCard(
            MissionSnapshot(mission_id=mission_id, title="…", status="running"),
            self._theme,
            self,
        )
        self._cards[mission_id] = card
        # Le missioni recenti vanno in cima: la cronologia si legge dall'alto.
        self._column.insertWidget(0, card)
        return card

    @safe_slot("ui.missions")
    def _on_mission(self, event: Event[MissionSnapshot]) -> None:
        self._card_for(event.payload.mission_id).update_from(event.payload)
        self._prune()
        self._update_empty()

    @safe_slot("ui.missions")
    def _on_action(self, event: Event[ActionSnapshot]) -> None:
        action = event.payload
        if action.mission_id is None:
            return  # le azioni senza missione vivono nella coda, non qui
        self._card_for(action.mission_id).update_action(action)

    def _prune(self) -> None:
        """Limita le schede mostrate, rimuovendo le più vecchie."""
        conservare = {m.mission_id for m in self._engine.active_missions()}
        conservare |= {m.mission_id for m in self._engine.mission_history()[:_HISTORY_SHOWN]}
        for mission_id in [k for k in self._cards if k not in conservare]:
            self._cards.pop(mission_id).setParent(None)

    def _update_empty(self) -> None:
        self._empty.setVisible(not self._cards)
