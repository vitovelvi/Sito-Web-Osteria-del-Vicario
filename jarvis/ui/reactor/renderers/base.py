"""Contratto del renderer del nucleo.

Esiste per una ragione precisa: oggi il nucleo e' disegnato con ``QPainter``,
che e' portabile e sufficiente per il budget di 4 ms per frame. Domani, se
servissero shader veri (bagliori volumetrici, distorsioni, particelle), la
strada e' Qt Quick con GLSL — ma ``QQuickWidget`` dentro una finestra frameless
e translucida si comporta in modo diverso fra Windows, macOS e Linux, e va
valutato sull'hardware reale.

Dietro questa interfaccia, quel cambio e' l'aggiunta di un file. Senza, sarebbe
la riscrittura del widget.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from core.qtcompat import QtCore, QtGui
from ui.reactor.params import ReactorFrame

__all__ = ["IReactorRenderer", "Quality"]


class Quality(StrEnum):
    """Livello di dettaglio del disegno.

    Deciso dal carico misurato dal :class:`~core.frameclock.FrameClock`, non
    dall'utente: un'interfaccia che si adatta e' preferibile a una che scatta.
    """

    HIGH = "high"
    """Alone sfumato, tutti gli anelli, antialiasing pieno."""

    LOW = "low"
    """Niente alone in pixmap, meno archi. Per macchine sotto pressione,
    portatili a batteria o sessioni remote."""


@runtime_checkable
class IReactorRenderer(Protocol):
    """Disegna un fotogramma del nucleo.

    Il renderer e' **senza memoria**: riceve tutto cio' che serve e non conserva
    stato di animazione. Le uniche cache ammesse sono quelle di puro disegno
    (pixmap pre-renderizzati), invalidabili con :meth:`invalidate`.
    """

    def render(
        self, painter: QtGui.QPainter, rect: QtCore.QRectF, frame: ReactorFrame
    ) -> None:
        """Disegna il nucleo dentro ``rect``."""
        ...

    def set_quality(self, quality: Quality) -> None:
        """Cambia il livello di dettaglio."""
        ...

    def invalidate(self) -> None:
        """Svuota le cache interne (cambio di tema o di scala DPI)."""
        ...
