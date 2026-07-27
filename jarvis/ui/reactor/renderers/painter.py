"""Renderer del nucleo basato su QPainter.

Tre accorgimenti fanno la differenza fra 4 ms e 15 ms per frame, cioe' fra
un'interfaccia fluida e una che perde frame:

1. **Nessun ``QGraphicsDropShadowEffect``.** E' rasterizzazione software
   ripetuta a ogni frame: su un cerchio grande costa da solo 10-15 ms, il budget
   intero (docs §2.2). L'alone qui e' un ``QPixmap`` pre-renderizzato con
   gradiente radiale, disegnato in composizione additiva e **messo in cache**
   per raggio e colore.
2. **Cache invalidata solo quando serve.** La chiave include il colore
   quantizzato: durante una dissolvenza il colore cambia a ogni frame, e senza
   quantizzazione si rigenererebbe la pixmap sessanta volte al secondo,
   ottenendo l'effetto opposto a quello voluto.
3. **Niente allocazioni nel ciclo di disegno.** Penne e pennelli sono
   riutilizzati; le geometrie si calcolano con aritmetica semplice.
"""

from __future__ import annotations

import math
from typing import Final

from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, QtGui
from ui.reactor.params import ReactorFrame
from ui.reactor.renderers.base import Quality

__all__ = ["PainterReactorRenderer"]

_log = get_logger(LogCategory.UI, "renderer")

#: Anelli fissi, come frazione del raggio disponibile.
_RINGS: Final[tuple[float, ...]] = (0.52, 0.70, 0.88)

#: Archi rotanti: (frazione del raggio, ampiezza in gradi, offset, spessore).
_ARCS: Final[tuple[tuple[float, float, float, float], ...]] = (
    (0.62, 62.0, 0.0, 2.2),
    (0.62, 38.0, 180.0, 2.2),
    (0.78, 26.0, 96.0, 1.6),
    (0.78, 26.0, 276.0, 1.6),
    (0.94, 14.0, 40.0, 1.2),
)

#: Numero massimo di pixmap d'alone in cache. Ogni voce costa
#: (2·raggio)² · 4 byte: con raggio 200 px sono ~640 KB, quindi il tetto e' basso.
_GLOW_CACHE_SIZE: Final[int] = 12

#: Passo di quantizzazione del colore per la chiave di cache (0-255).
_COLOR_QUANTUM: Final[int] = 16

#: Passo di quantizzazione del raggio dell'alone, in pixel. Il respiro fa
#: variare il raggio in continuazione: senza questo arrotondamento la cache
#: verrebbe mancata a ogni frame.
_RADIUS_QUANTUM: Final[int] = 24


class PainterReactorRenderer:
    """Disegna il nucleo con le primitive 2D di Qt."""

    def __init__(self, quality: Quality = Quality.HIGH) -> None:
        self._quality = quality
        self._glow_cache: dict[tuple[int, int], QtGui.QPixmap] = {}
        self._pen = QtGui.QPen()
        self._pen.setCapStyle(Qt.PenCapStyle.RoundCap)

    # ------------------------------------------------------------------ #
    # Contratto
    # ------------------------------------------------------------------ #

    def set_quality(self, quality: Quality) -> None:
        if quality is self._quality:
            return
        self._quality = quality
        self.invalidate()
        _log.info("Qualita' di disegno: %s", quality.value)

    def invalidate(self) -> None:
        self._glow_cache.clear()

    def render(
        self, painter: QtGui.QPainter, rect: QtCore.QRectF, frame: ReactorFrame
    ) -> None:
        """Disegna un fotogramma completo."""
        p = frame.params
        if p.energy <= 0.01:
            return

        center = rect.center()
        dx, dy = frame.jitter_offset
        center = QtCore.QPointF(center.x() + dx, center.y() + dy)

        radius = min(rect.width(), rect.height()) * 0.5
        if radius < 8.0:
            return  # troppo piccolo per essere leggibile: si evita di sprecare frame

        # Il respiro modula il raggio di riferimento di tutti gli strati: e' cio'
        # che li fa percepire come un unico oggetto vivo e non come cerchi
        # sovrapposti che si muovono ciascuno per conto proprio.
        breath = 1.0 + frame.pulse * p.pulse_depth
        radius *= breath

        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        self._draw_glow(painter, center, radius, frame)
        self._draw_rings(painter, center, radius, frame)
        self._draw_arcs(painter, center, radius, frame)
        self._draw_waves(painter, center, radius, frame)
        self._draw_impulses(painter, center, radius, frame)
        self._draw_spectrum(painter, center, radius, frame)
        self._draw_core(painter, center, radius, frame)

    # ------------------------------------------------------------------ #
    # Strati
    # ------------------------------------------------------------------ #

    def _draw_glow(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Alone additivo, da pixmap pre-renderizzata."""
        p = frame.params
        strength = p.glow_strength * p.energy
        if strength <= 0.02 or self._quality is Quality.LOW:
            return

        target_radius = radius * 1.15
        # La pixmap si genera a un raggio **quantizzato** e si disegna scalata a
        # quello esatto. Senza questo passaggio il respiro — che varia il raggio
        # a ogni frame — produrrebbe una chiave di cache diversa ogni volta, e
        # la cache non servirebbe a nulla. Scalare una pixmap in fase di disegno
        # costa una frazione di quanto costa rigenerarla, e su un gradiente
        # morbido la differenza non e' percepibile.
        pixmap = self._glow_pixmap(_quantize_radius(target_radius), p.glow)
        if pixmap.isNull():
            return

        painter.save()
        # Composizione additiva: gli aloni sovrapposti si sommano invece di
        # coprirsi, che e' il comportamento della luce.
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Plus)
        painter.setOpacity(min(1.0, strength))
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(
            QtCore.QRectF(
                center.x() - target_radius,
                center.y() - target_radius,
                target_radius * 2,
                target_radius * 2,
            ),
            pixmap,
            QtCore.QRectF(pixmap.rect()),
        )
        painter.restore()

    def _draw_rings(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Anelli fissi, che danno profondita' senza attirare l'attenzione."""
        p = frame.params
        opacity = p.ring_opacity * p.energy
        if opacity <= 0.02:
            return

        for index, ratio in enumerate(_RINGS):
            r = radius * ratio
            self._pen.setColor(_with_alpha(p.color, opacity * (0.85 - index * 0.22)))
            self._pen.setWidthF(1.1 if index else 1.5)
            painter.setPen(self._pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, r, r)

    def _draw_arcs(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Archi in rotazione: e' la firma visiva dell'elaborazione."""
        p = frame.params
        if abs(p.rotation_speed) < 0.5:
            return

        opacity = p.ring_opacity * p.energy
        arcs = _ARCS if self._quality is Quality.HIGH else _ARCS[:2]

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for ratio, span, offset, width in arcs:
            r = radius * ratio
            box = QtCore.QRectF(center.x() - r, center.y() - r, r * 2, r * 2)
            self._pen.setColor(_with_alpha(p.color, opacity))
            self._pen.setWidthF(width)
            painter.setPen(self._pen)
            # Qt misura gli angoli in sedicesimi di grado, in senso antiorario.
            start = int((frame.rotation_deg + offset) * 16)
            painter.drawArc(box, start, int(span * 16))

    def _draw_waves(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Onde concentriche che si espandono e svaniscono."""
        p = frame.params
        if not frame.waves or p.wave_strength <= 0.02:
            return

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for progress in frame.waves:
            # Espansione decelerata e dissolvenza quadratica: l'onda "esce" dal
            # nucleo con energia e si spegne dolcemente, come un fronte reale.
            eased = 1.0 - (1.0 - progress) ** 2
            r = radius * (p.core_ratio + eased * (1.05 - p.core_ratio))
            alpha = p.wave_strength * p.energy * (1.0 - progress) ** 2
            if alpha <= 0.01:
                continue
            self._pen.setColor(_with_alpha(p.color, alpha))
            self._pen.setWidthF(max(0.8, 2.4 * (1.0 - progress)))
            painter.setPen(self._pen)
            painter.drawEllipse(center, r, r)

    def _draw_impulses(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Impulsi discreti dell'esecuzione: archi spessi e brevi."""
        p = frame.params
        if not frame.impulses or p.impulse_rate <= 0.01:
            return

        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, progress in enumerate(frame.impulses):
            r = radius * (p.core_ratio + progress * (1.0 - p.core_ratio))
            alpha = p.energy * (1.0 - progress)
            if alpha <= 0.01:
                continue
            box = QtCore.QRectF(center.x() - r, center.y() - r, r * 2, r * 2)
            self._pen.setColor(_with_alpha(p.color, alpha * 0.9))
            self._pen.setWidthF(max(1.0, 3.5 * (1.0 - progress)))
            painter.setPen(self._pen)
            start = int((frame.rotation_deg + index * 137.5) * 16)
            painter.drawArc(box, start, (70 * 16))

    def _draw_spectrum(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Equalizzatore radiale, pilotato dall'ampiezza dell'audio."""
        p = frame.params
        if p.bar_strength <= 0.02 or not frame.spectrum:
            return

        bars = len(frame.spectrum)
        step = 360.0 / bars
        inner = radius * (p.core_ratio + 0.12)
        span = radius * 0.34 * p.bar_strength * p.energy

        self._pen.setWidthF(max(1.4, radius * 0.018))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        for i, magnitude in enumerate(frame.spectrum):
            if magnitude <= 0.01:
                continue
            angle = math.radians(i * step + frame.rotation_deg)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            outer = inner + span * magnitude
            self._pen.setColor(_with_alpha(p.color, 0.35 + 0.55 * magnitude))
            painter.setPen(self._pen)
            painter.drawLine(
                QtCore.QPointF(center.x() + cos_a * inner, center.y() - sin_a * inner),
                QtCore.QPointF(center.x() + cos_a * outer, center.y() - sin_a * outer),
            )

    def _draw_core(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        radius: float,
        frame: ReactorFrame,
    ) -> None:
        """Disco centrale: gradiente radiale piu' bordo luminoso."""
        p = frame.params
        r = radius * p.core_ratio
        if r < 2.0:
            return

        gradient = QtGui.QRadialGradient(center, r)
        bright = _lighter(p.color, 1.55)
        gradient.setColorAt(0.0, _with_alpha(bright, 0.95 * p.energy))
        gradient.setColorAt(0.55, _with_alpha(p.color, 0.80 * p.energy))
        gradient.setColorAt(1.0, _with_alpha(p.color, 0.06 * p.energy))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawEllipse(center, r, r)

        # Bordo: definisce il nucleo contro l'alone, che altrimenti lo sfuoca.
        self._pen.setColor(_with_alpha(bright, 0.55 * p.energy))
        self._pen.setWidthF(1.4)
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, r, r)

    # ------------------------------------------------------------------ #
    # Cache dell'alone
    # ------------------------------------------------------------------ #

    def _glow_pixmap(self, radius: int, color: QtGui.QColor) -> QtGui.QPixmap:
        """Pixmap dell'alone, generata una volta per raggio e colore.

        La chiave quantizza il colore: durante una dissolvenza la tinta cambia a
        ogni frame, e rigenerare la pixmap sessanta volte al secondo costerebbe
        piu' del ``QGraphicsDropShadowEffect`` che si voleva evitare. Con un
        passo di 16 livelli per canale la differenza non e' percepibile e la
        cache resta stabile per l'intera transizione.
        """
        radius = max(8, radius)
        key = (radius, _quantize(color))
        cached = self._glow_cache.get(key)
        if cached is not None:
            return cached

        if len(self._glow_cache) >= _GLOW_CACHE_SIZE:
            # Politica volutamente grossolana: la cache e' piccola e il costo di
            # ricostruzione basso, quindi non vale una struttura LRU.
            self._glow_cache.clear()

        size = radius * 2
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        gradient = QtGui.QRadialGradient(radius, radius, radius)
        # Il profilo non e' lineare: una sfumatura lineare produce un alone
        # "piatto", da alone di nebbia. Le fermate concentrano la luce al centro.
        for stop, alpha in ((0.0, 0.55), (0.25, 0.30), (0.5, 0.13), (0.75, 0.04), (1.0, 0.0)):
            gradient.setColorAt(stop, _with_alpha(color, alpha))

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawEllipse(0, 0, size, size)
        painter.end()

        self._glow_cache[key] = pixmap
        return pixmap


# --------------------------------------------------------------------------- #
# Utilita' di colore
# --------------------------------------------------------------------------- #


def _with_alpha(color: QtGui.QColor, alpha: float) -> QtGui.QColor:
    """Copia del colore con alpha in [0, 1]."""
    result = QtGui.QColor(color)
    result.setAlphaF(max(0.0, min(1.0, alpha)))
    return result


def _lighter(color: QtGui.QColor, factor: float) -> QtGui.QColor:
    """Schiarisce un colore mantenendone la tinta."""
    h, s, v, a = color.getHsvF()
    result = QtGui.QColor()
    result.setHsvF(
        max(0.0, h), max(0.0, s * 0.75), min(1.0, max(0.0, v) * factor), a
    )
    return result


def _quantize_radius(radius: float) -> int:
    """Arrotonda il raggio al passo di cache superiore."""
    step = _RADIUS_QUANTUM
    return max(step, int((radius + step - 1) // step) * step)


def _quantize(color: QtGui.QColor) -> int:
    """Riduce il colore a una chiave stabile per la cache."""
    r = color.red() // _COLOR_QUANTUM
    g = color.green() // _COLOR_QUANTUM
    b = color.blue() // _COLOR_QUANTUM
    return (r << 16) | (g << 8) | b
