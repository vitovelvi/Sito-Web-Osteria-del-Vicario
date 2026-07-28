"""Richieste di conferma.

È l'unico punto dell'interfaccia in cui una decisione dell'utente torna al
backend, e va trattato con più cura del resto:

* **il rischio cambia l'aspetto.** Una conferma per un'operazione distruttiva
  non può somigliare a una notifica: bordo rosso, etichetta esplicita, nessun
  pulsante preselezionato;
* **nessun pulsante è predefinito.** Premere Invio per abitudine non deve poter
  autorizzare un comando di sistema;
* **il tempo residuo è visibile e scorre.** Alla scadenza la scheda si ritira da
  sola e lo dice: continuare a offrire un'autorizzazione che il backend ha già
  abbandonato invita a un gesto senza effetto.
"""

from __future__ import annotations

from typing import Final

from jarvis_protocol.missions import RiskLevel

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import ConfirmSnapshot, EventType
from core.logging_setup import LogCategory, get_logger
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from ui.ops.common import RISK_LABEL, RISK_TOKEN
from ui.theme.theme import Theme

__all__ = ["ConfirmationLayer"]

_log = get_logger(LogCategory.UI, "confirm")

_CARD_WIDTH: Final[int] = 380
_MARGIN: Final[int] = 18


class _ConfirmCard(QtWidgets.QFrame):
    """Scheda di una singola richiesta."""

    def __init__(
        self,
        request: ConfirmSnapshot,
        engine: MissionEngine,
        theme: Theme,
        parent: QtWidgets.QWidget,
    ) -> None:
        super().__init__(parent)
        self._request = request
        self._engine = engine
        self._theme = theme
        self._accent = theme.color(RISK_TOKEN.get(request.risk, "state.warning"))
        self._seconds_left = request.seconds_left

        self.setProperty("role", "panel")
        self.setFixedWidth(_CARD_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        rischio = QtWidgets.QLabel(
            f"CONFERMA RICHIESTA · RISCHIO {RISK_LABEL.get(request.risk, '?').upper()}"
        )
        rischio.setProperty("role", "hud")
        rischio.setStyleSheet(f"color: {self._accent.name()};")

        titolo = QtWidgets.QLabel(request.title)
        titolo.setProperty("role", "title")
        titolo.setWordWrap(True)

        self._countdown = QtWidgets.QLabel()
        self._countdown.setProperty("role", "muted")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 14, 12)
        layout.setSpacing(6)
        layout.addWidget(rischio)
        layout.addWidget(titolo)

        if request.detail:
            dettaglio = QtWidgets.QLabel(request.detail)
            dettaglio.setProperty("role", "muted")
            dettaglio.setWordWrap(True)
            layout.addWidget(dettaglio)

        layout.addWidget(self._countdown)

        pulsanti = QtWidgets.QHBoxLayout()
        pulsanti.setSpacing(8)
        pulsanti.addStretch(1)

        nega = QtWidgets.QPushButton("Nega")
        nega.clicked.connect(lambda: self._reply(False))
        pulsanti.addWidget(nega)

        approva = QtWidgets.QPushButton("Autorizza")
        approva.clicked.connect(lambda: self._reply(True))
        # Nessun pulsante predefinito: per le operazioni rischiose l'utente deve
        # compiere un gesto deliberato, non premere Invio per abitudine.
        approva.setAutoDefault(False)
        approva.setDefault(False)
        if request.risk in (RiskLevel.HIGH.value, RiskLevel.DESTRUCTIVE.value):
            approva.setStyleSheet(
                f"QPushButton {{ border-color: {self._accent.name()}; "
                f"color: {self._accent.name()}; }}"
            )
        pulsanti.addWidget(approva)
        layout.addLayout(pulsanti)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def _tick(self) -> None:
        """Aggiorna il tempo residuo e ritira la scheda alla scadenza."""
        if self._seconds_left is None:
            self._countdown.setText("In attesa della tua decisione.")
            return

        rimasti = max(0.0, self._request.seconds_left or 0.0)
        if self._engine.sweep_expired_confirmations() or rimasti <= 0.0:
            self._timer.stop()
            self._countdown.setText("Richiesta scaduta.")
            self.setEnabled(False)
            QtCore.QTimer.singleShot(1200, self.deleteLater)
            return
        self._countdown.setText(f"Scade fra {rimasti:.0f} s.")

    @safe_slot("ui.confirm")
    def _reply(self, approved: bool) -> None:
        self._timer.stop()
        self.setEnabled(False)
        _log.info(
            "Conferma %s dall'utente: %s",
            "concessa" if approved else "negata",
            self._request.title,
        )
        self._engine.resolve_confirmation(self._request.request_id, approved)
        self.deleteLater()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Bordo colorato secondo il rischio."""
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(self._accent, 1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        painter.end()


class ConfirmationLayer(QtCore.QObject):
    """Impila le richieste di conferma sopra la finestra principale."""

    def __init__(
        self,
        bus: EventBus,
        engine: MissionEngine,
        host: QtWidgets.QWidget,
        theme: Theme,
        *,
        top_offset: int = 60,
    ) -> None:
        super().__init__(host)
        self._engine = engine
        self._host = host
        self._theme = theme
        self._top_offset = top_offset
        self._cards: dict[str, _ConfirmCard] = {}

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.CONFIRM_REQUESTED, self._on_requested),
            bus.subscribe(EventType.CONFIRM_RESOLVED, self._on_resolved),
        ]
        host.installEventFilter(self)

    @safe_slot("ui.confirm")
    def _on_requested(self, event: Event[ConfirmSnapshot]) -> None:
        request = event.payload
        if request.request_id in self._cards:
            return
        card = _ConfirmCard(request, self._engine, self._theme, self._host)
        self._cards[request.request_id] = card
        card.destroyed.connect(lambda _=None, r=request.request_id: self._forget(r))
        card.adjustSize()
        card.show()
        card.raise_()
        self._reflow()

    @safe_slot("ui.confirm")
    def _on_resolved(self, event: Event[ConfirmSnapshot]) -> None:
        card = self._cards.pop(event.payload.request_id, None)
        if card is not None:
            card.deleteLater()
        self._reflow()

    def _forget(self, request_id: str) -> None:
        self._cards.pop(request_id, None)
        self._reflow()

    def _reflow(self) -> None:
        """Impila le schede in alto a destra, sotto la barra del titolo."""
        y = self._top_offset
        for card in list(self._cards.values()):
            if not card.isVisible():
                continue
            card.move(self._host.width() - _CARD_WIDTH - _MARGIN, y)
            y += card.height() + 10

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self._host and event.type() == QtCore.QEvent.Type.Resize:
            self._reflow()
        return False
