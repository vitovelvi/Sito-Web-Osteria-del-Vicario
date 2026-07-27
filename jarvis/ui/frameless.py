"""Finestra senza cornice, con ombra e ridimensionamento propri.

Rinunciare alla cornice nativa significa reimplementare a mano cio' che il
gestore di finestre offriva gratis: trascinamento, ridimensionamento dai bordi,
massimizzazione con doppio clic, aggancio ai lati, comportamento su piu' monitor
con DPI differenti. Vale la pena farlo solo perche' l'estetica richiesta lo
impone; e va fatto **bene**, altrimenti si ottiene una finestra che sembra
moderna e si comporta peggio di una nativa.

Due scelte tecniche che fanno la differenza:

**``startSystemResize`` / ``startSystemMove``.** Qt 6 delega l'operazione al
gestore di finestre invece di seguire il mouse a mano. Si ottengono cosi'
aggancio ai bordi, resistenza ai margini dello schermo e fluidita' nativi. Il
percorso manuale resta come ripiego dove il compositor non li supporta.

**Ombra disegnata e messa in cache.** ``QGraphicsDropShadowEffect`` applicato
alla superficie principale verrebbe ri-rasterizzato a ogni ridisegno di un
qualunque figlio — e il nucleo si ridisegna sessanta volte al secondo. L'ombra
e' quindi una pixmap costruita a ogni ridimensionamento e poi solo copiata.
"""

from __future__ import annotations

from typing import Final

from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from ui.theme.theme import Theme

__all__ = ["FramelessWindow"]

_log = get_logger(LogCategory.UI, "window")

#: Numero di passate per approssimare la sfocatura dell'ombra. Piu' passate =
#: sfumatura piu' morbida; il costo si paga una volta sola per dimensione.
_SHADOW_STEPS: Final[int] = 18


class FramelessWindow(QtWidgets.QWidget):
    """Finestra priva di cornice nativa, con superficie arrotondata e ombra."""

    def __init__(
        self,
        theme: Theme,
        *,
        translucent: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._translucent = translucent
        self._radius = theme.px("radius.xl", 18)
        self._resize_margin = theme.px("window.resizeMargin", 6)
        self._shadow_margin = theme.px("window.shadowMargin", 22) if translucent else 0
        self._shadow_cache: QtGui.QPixmap | None = None
        self._drag_origin: QtCore.QPoint | None = None

        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        self.setWindowFlags(flags)
        if translucent:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            # Senza trasparenza non c'e' spazio per l'ombra: la superficie
            # occupa l'intera finestra e i bordi restano netti (docs §10).
            self._radius = 0

        self.setMouseTracking(True)

        # La superficie e' un figlio: e' lei ad avere il fondo e il bordo, cosi'
        # il foglio di stile non deve conoscere l'ombra.
        self._surface = QtWidgets.QWidget(self)
        self._surface.setObjectName("rootSurface")
        self._surface.setMouseTracking(True)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(*([self._shadow_margin] * 4))
        outer.addWidget(self._surface)

    # ------------------------------------------------------------------ #
    # Superficie
    # ------------------------------------------------------------------ #

    @property
    def surface(self) -> QtWidgets.QWidget:
        """Contenitore in cui va inserito il contenuto della finestra."""
        return self._surface

    # ------------------------------------------------------------------ #
    # Ombra
    # ------------------------------------------------------------------ #

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Disegna l'ombra sotto la superficie."""
        if not self._translucent or self._shadow_margin <= 0:
            return
        if self._shadow_cache is None or self._shadow_cache.size() != self.size():
            self._shadow_cache = self._build_shadow()
        painter = QtGui.QPainter(self)
        painter.drawPixmap(0, 0, self._shadow_cache)
        painter.end()

    def _build_shadow(self) -> QtGui.QPixmap:
        """Costruisce la pixmap dell'ombra per la dimensione corrente.

        L'approssimazione della sfocatura per passate concentriche costa poco e
        produce un risultato indistinguibile da una gaussiana a queste
        dimensioni. Il calcolo avviene solo al ridimensionamento.
        """
        ratio = self.devicePixelRatioF()
        pixmap = QtGui.QPixmap(self.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)

        color = self._theme.color("elevation.shadowColor")
        max_alpha = self._theme.px("elevation.shadowAlpha", 160)
        offset_y = self._theme.px("elevation.shadowOffsetY", 8)
        margin = self._shadow_margin

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        for step in range(_SHADOW_STEPS, 0, -1):
            progress = step / _SHADOW_STEPS
            inset = margin * (1.0 - progress)
            # L'alpha cresce in modo quadratico verso l'interno: e' cio' che
            # rende l'ombra "attaccata" alla finestra invece che diffusa.
            alpha = int(max_alpha * (1.0 - progress) ** 2 / _SHADOW_STEPS * 6)
            if alpha <= 0:
                continue
            shade = QtGui.QColor(color)
            shade.setAlpha(min(255, alpha))
            painter.setBrush(shade)
            rect = QtCore.QRectF(self.rect()).adjusted(
                inset, inset + offset_y * progress * 0.5,
                -inset, -inset + offset_y * progress * 0.5,
            )
            painter.drawRoundedRect(rect, self._radius + inset, self._radius + inset)

        painter.end()
        return pixmap

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        self._shadow_cache = None
        super().resizeEvent(event)

    # ------------------------------------------------------------------ #
    # Trascinamento e ridimensionamento
    # ------------------------------------------------------------------ #

    def _edges_at(self, position: QtCore.QPoint) -> Qt.Edge | None:
        """Bordi coinvolti dalla posizione del puntatore, o ``None``."""
        rect = self._surface.geometry()
        margin = self._resize_margin
        edges: Qt.Edge | None = None

        def add(edge: Qt.Edge) -> None:
            nonlocal edges
            edges = edge if edges is None else edges | edge  # type: ignore[assignment]

        if abs(position.x() - rect.left()) <= margin:
            add(Qt.Edge.LeftEdge)
        elif abs(position.x() - rect.right()) <= margin:
            add(Qt.Edge.RightEdge)
        if abs(position.y() - rect.top()) <= margin:
            add(Qt.Edge.TopEdge)
        elif abs(position.y() - rect.bottom()) <= margin:
            add(Qt.Edge.BottomEdge)
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edge | None) -> Qt.CursorShape:
        """Puntatore corrispondente ai bordi."""
        if edges is None:
            return Qt.CursorShape.ArrowCursor
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Aggiorna il puntatore in base alla vicinanza ai bordi."""
        if not self.isMaximized():
            self.setCursor(self._cursor_for(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Avvia il ridimensionamento se il clic e' su un bordo."""
        if event.button() is not Qt.MouseButton.LeftButton or self.isMaximized():
            super().mousePressEvent(event)
            return

        edges = self._edges_at(event.position().toPoint())
        if edges is None:
            super().mousePressEvent(event)
            return

        handle = self.windowHandle()
        if handle is not None and handle.startSystemResize(edges):
            event.accept()
            return

        # Ripiego per i compositor che non supportano l'operazione di sistema.
        self._drag_origin = event.globalPosition().toPoint()
        event.accept()

    def begin_system_move(self, event: QtGui.QMouseEvent) -> bool:
        """Avvia il trascinamento della finestra.

        Invocata dalla barra del titolo: e' lei a sapere quali zone sono
        trascinabili, non la finestra.
        """
        handle = self.windowHandle()
        if handle is not None and handle.startSystemMove():
            return True
        self._drag_origin = event.globalPosition().toPoint()
        return False

    def toggle_maximized(self) -> None:
        """Alterna fra massimizzata e dimensione normale."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def set_always_on_top(self, enabled: bool) -> None:
        """Attiva o disattiva "sempre in primo piano".

        Cambiare i flag ricrea la finestra nativa: bisogna rimostrarla, oppure
        sparisce. E' un dettaglio noto di Qt che vale la pena incapsulare qui
        una volta per tutte.
        """
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()
        _log.info("Sempre in primo piano: %s", "attivo" if enabled else "disattivo")
