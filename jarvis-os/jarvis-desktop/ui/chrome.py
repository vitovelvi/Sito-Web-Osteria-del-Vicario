"""Barra del titolo personalizzata.

Con una finestra senza cornice la barra va ricostruita: trascinamento, doppio
clic per massimizzare, pulsanti di sistema. Sono pochi comportamenti, ma se ne
manca uno l'interfaccia risulta subito "sbagliata" all'uso, anche quando
sembra giusta in una schermata.
"""

from __future__ import annotations

from collections.abc import Callable

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import BackendIdentity, EventType
from core.qtcompat import Qt, QtGui, QtWidgets

__all__ = ["TitleBar"]


class _ChromeButton(QtWidgets.QPushButton):
    """Pulsante della barra: piatto, quadrato, senza etichetta di testo."""

    def __init__(
        self, glyph: str, tooltip: str, on_click: Callable[[], None], *, danger: bool = False
    ) -> None:
        super().__init__(glyph)
        self.setProperty("role", "chrome")
        if danger:
            self.setProperty("danger", "true")
        self.setToolTip(tooltip)
        self.setFixedSize(30, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clicked.connect(on_click)


class TitleBar(QtWidgets.QWidget):
    """Barra superiore: identita' a sinistra, comandi a destra."""

    def __init__(
        self,
        bus: EventBus,
        window: QtWidgets.QWidget,
        *,
        height: int = 44,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._window = window
        self.setFixedHeight(height)
        self.setMouseTracking(True)

        self._title = QtWidgets.QLabel("J.A.R.V.I.S.")
        self._title.setProperty("role", "title")

        self._subtitle = QtWidgets.QLabel("in attesa del backend")
        self._subtitle.setProperty("role", "muted")

        heading = QtWidgets.QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(0)
        heading.addWidget(self._title)
        heading.addWidget(self._subtitle)

        self._pin = _ChromeButton("⇧", "Sempre in primo piano", self._toggle_pin)
        self._pin.setCheckable(True)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 8, 6)
        layout.setSpacing(4)
        layout.addLayout(heading)
        layout.addStretch(1)
        layout.addWidget(self._pin)
        layout.addWidget(_ChromeButton("—", "Riduci a icona", self._window.showMinimized))
        layout.addWidget(_ChromeButton("□", "Ingrandisci", self._toggle_max))
        layout.addWidget(_ChromeButton("✕", "Chiudi", self._window.close, danger=True))

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.IDENTITY_UPDATED, self._on_identity, replay_last=True)
        ]

    # ------------------------------------------------------------------ #
    # Identita'
    # ------------------------------------------------------------------ #

    @safe_slot("ui.chrome")
    def _on_identity(self, event: Event[BackendIdentity]) -> None:
        """Mostra l'identita' dichiarata dal backend.

        Finche' il backend non si e' presentato, il sottotitolo dice
        esplicitamente che l'informazione manca: la GUI riflette lo stato reale
        e non simula una connessione che non c'e'.
        """
        identity = event.payload
        self._title.setText(identity.assistant_name)
        if identity.backend_version:
            model = identity.model or "modello non dichiarato"
            self._subtitle.setText(
                f"{identity.backend_name} {identity.backend_version} · {model}"
            )
        else:
            self._subtitle.setText("in attesa del backend")

    # ------------------------------------------------------------------ #
    # Comandi
    # ------------------------------------------------------------------ #

    def _toggle_pin(self, checked: bool) -> None:
        setter = getattr(self._window, "set_always_on_top", None)
        if callable(setter):
            setter(checked)

    def _toggle_max(self) -> None:
        toggler = getattr(self._window, "toggle_maximized", None)
        if callable(toggler):
            toggler()

    # ------------------------------------------------------------------ #
    # Trascinamento
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Avvia il trascinamento della finestra."""
        if event.button() is Qt.MouseButton.LeftButton:
            starter = getattr(self._window, "begin_system_move", None)
            if callable(starter):
                starter(event)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """Doppio clic: alterna la massimizzazione, come una barra nativa."""
        if event.button() is Qt.MouseButton.LeftButton:
            self._toggle_max()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Sottile linea di separazione dal contenuto."""
        painter = QtGui.QPainter(self)
        color = self.palette().color(QtGui.QPalette.ColorRole.Mid)
        color.setAlpha(90)
        painter.setPen(color)
        painter.drawLine(16, self.height() - 1, self.width() - 16, self.height() - 1)
        painter.end()
