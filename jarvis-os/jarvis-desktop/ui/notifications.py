"""Notifiche toast, con animazioni morbide.

Le animazioni qui usano ``QPropertyAnimation`` **come e' giusto**: sono
transizioni di durata finita su proprieta' di un oggetto (posizione, opacita'),
non moto continuo. E' la distinzione fatta nel nucleo, applicata al contrario.

Due dettagli che separano un toast curato da uno fastidioso: la pila si
ricompone con animazione quando un toast scompare — non salta — e il timer di
chiusura si ferma mentre il puntatore e' sopra, perche' un avviso che sparisce
proprio mentre lo si sta leggendo e' peggio di nessun avviso.
"""

from __future__ import annotations

from typing import Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType, NotificationRequest
from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets, Signal
from ui.theme.theme import Theme

__all__ = ["ToastManager"]

_log = get_logger(LogCategory.UI, "toast")

#: Colore del bordo sinistro per tipo di notifica.
_KIND_COLOR: Final[dict[str, str]] = {
    "info": "accent.core",
    "success": "state.success",
    "warning": "state.warning",
    "error": "state.error",
}

_TOAST_WIDTH: Final[int] = 320
_MARGIN: Final[int] = 18
_SPACING: Final[int] = 10

#: Oltre questo numero i toast piu' vecchi vengono chiusi: una pila che copre
#: mezza finestra e' un guasto, non una notifica.
_MAX_VISIBLE: Final[int] = 4


class _Toast(QtWidgets.QFrame):
    """Singola notifica."""

    dismissed = Signal(object)

    def __init__(
        self, request: NotificationRequest, theme: Theme, parent: QtWidgets.QWidget
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._accent = theme.color(_KIND_COLOR.get(request.kind, "accent.core"))
        self.setProperty("role", "panel")
        self.setFixedWidth(_TOAST_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        title = QtWidgets.QLabel(request.title)
        title.setProperty("role", "title")
        title.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 11, 12, 11)
        layout.setSpacing(3)
        layout.addWidget(title)

        if request.body:
            body = QtWidgets.QLabel(request.body)
            body.setProperty("role", "muted")
            body.setWordWrap(True)
            layout.addWidget(body)

        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._duration = max(1200, request.duration_ms)

        self._animations: list[QtCore.QAbstractAnimation] = []

    # ------------------------------------------------------------------ #
    # Comparsa e scomparsa
    # ------------------------------------------------------------------ #

    def appear(self, target: QtCore.QPoint) -> None:
        """Entra in scena scivolando da destra."""
        self.move(target.x() + 40, target.y())
        self.show()

        group = QtCore.QParallelAnimationGroup(self)
        group.addAnimation(self._slide_to(target, self._theme.ms("normal")))
        group.addAnimation(self._fade_to(1.0, self._theme.ms("normal")))
        group.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

        self._timer.start(self._duration)

    def move_to(self, target: QtCore.QPoint) -> None:
        """Scorre verso una nuova posizione nella pila."""
        if self.pos() == target:
            return
        animation = self._slide_to(target, self._theme.ms("fast"))
        animation.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def dismiss(self) -> None:
        """Esce di scena e si distrugge."""
        self._timer.stop()
        animation = self._fade_to(0.0, self._theme.ms("fast"))
        animation.finished.connect(self._finalize)
        animation.start(QtCore.QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def _finalize(self) -> None:
        self.dismissed.emit(self)
        self.deleteLater()

    def _slide_to(self, target: QtCore.QPoint, duration: int) -> QtCore.QPropertyAnimation:
        animation = QtCore.QPropertyAnimation(self, b"pos", self)
        animation.setDuration(duration)
        animation.setStartValue(self.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        return animation

    def _fade_to(self, value: float, duration: int) -> QtCore.QPropertyAnimation:
        animation = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        animation.setDuration(duration)
        animation.setStartValue(self._opacity.opacity())
        animation.setEndValue(value)
        animation.setEasingCurve(QtCore.QEasingCurve.Type.InOutQuad)
        return animation

    # ------------------------------------------------------------------ #
    # Interazione
    # ------------------------------------------------------------------ #

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:
        """Sospende la chiusura mentre il puntatore e' sopra."""
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._timer.start(min(self._duration, 1800))
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Un clic chiude subito la notifica."""
        self.dismiss()
        event.accept()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Barra colorata sul bordo sinistro, che identifica il tipo."""
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent)
        painter.drawRoundedRect(QtCore.QRectF(1, 8, 3, self.height() - 16), 1.5, 1.5)
        painter.end()


class ToastManager(QtCore.QObject):
    """Riceve le richieste di notifica e gestisce la pila."""

    def __init__(
        self,
        bus: EventBus,
        host: QtWidgets.QWidget,
        theme: Theme,
        *,
        bottom_offset: int = 0,
    ) -> None:
        """
        :param host: widget sopra cui impilare i toast, tipicamente la superficie
            della finestra principale.
        :param bottom_offset: spazio da lasciare in basso. Serve a non coprire
            la striscia di stato: un avviso che nasconde l'indicatore di
            connessione toglie proprio l'informazione che di solito si sta
            cercando quando compare un avviso.
        """
        super().__init__(host)
        self._host = host
        self._theme = theme
        self._bottom_offset = bottom_offset
        self._toasts: list[_Toast] = []
        self._subscription: Subscription = bus.subscribe(
            EventType.NOTIFICATION_REQUESTED, self._on_request
        )
        host.installEventFilter(self)

    @safe_slot("ui.toast")
    def _on_request(self, event: Event[NotificationRequest]) -> None:
        """Crea e mostra un nuovo toast."""
        self.show(event.payload)

    def show(self, request: NotificationRequest) -> None:
        """Mostra una notifica senza passare dal bus."""
        while len(self._toasts) >= _MAX_VISIBLE:
            self._toasts[0].dismiss()
            # dismiss() e' asincrono: si rimuove subito dalla lista per non
            # ricalcolare la pila includendo un toast in uscita.
            self._toasts.pop(0)

        toast = _Toast(request, self._theme, self._host)
        toast.dismissed.connect(self._on_dismissed)
        toast.adjustSize()
        self._toasts.append(toast)
        toast.appear(self._position_for(len(self._toasts) - 1, toast.sizeHint().height()))
        _log.debug("Notifica [%s] %s", request.kind, request.title)

    @safe_slot("ui.toast")
    def _on_dismissed(self, toast: object) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)  # type: ignore[arg-type]
        self._reflow()

    def _position_for(self, index: int, height: int) -> QtCore.QPoint:
        """Posizione del toast di indice ``index``, impilando dal basso."""
        x = self._host.width() - _TOAST_WIDTH - _MARGIN
        y = self._host.height() - _MARGIN - height - self._bottom_offset
        for existing in self._toasts[:index]:
            y -= existing.height() + _SPACING
        return QtCore.QPoint(x, y)

    def _reflow(self) -> None:
        """Ricompone la pila con animazione."""
        for index, toast in enumerate(self._toasts):
            toast.move_to(self._position_for(index, toast.height()))

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        """Riposiziona i toast quando la finestra cambia dimensione."""
        if watched is self._host and event.type() == QtCore.QEvent.Type.Resize:
            self._reflow()
        return False
