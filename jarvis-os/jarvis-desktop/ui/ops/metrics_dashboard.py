"""Metrics Dashboard: il comportamento del backend, misurato.

Tutte le metriche sono **derivate dagli eventi**, non chieste al backend: non
esiste un messaggio "dammi le statistiche". È una conseguenza della scelta
architetturale, non un limite — significa che le misure descrivono ciò che
l'interfaccia ha realmente ricevuto, che è esattamente ciò che serve quando si
sospetta che qualcosa non arrivi.

Due misure meritano attenzione:

* **p95 accanto alla media.** La media da sola nasconde le code lente, che sono
  il caso che rende un assistente frustrante da usare;
* **attesa in coda separata dalla durata.** Un'operazione lenta perché lo
  strumento è lento e una lenta perché è rimasta in coda si correggono in modi
  opposti, e con un solo numero non si distinguono.
"""

from __future__ import annotations

from collections import deque
from typing import Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType, OperationsMetrics
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from ui.ops.common import format_duration
from ui.theme.theme import Theme

__all__ = ["MetricsDashboard"]

#: Campioni della profondità di coda conservati per il grafico.
_SPARK_POINTS: Final[int] = 120


class _Sparkline(QtWidgets.QWidget):
    """Micro-grafico della profondità di coda nel tempo.

    Un numero dice quanto è profonda la coda adesso; la forma dice se sta
    crescendo — che è la domanda vera quando si guarda una coda.
    """

    def __init__(self, theme: Theme, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._points: deque[float] = deque(maxlen=_SPARK_POINTS)
        self.setMinimumHeight(46)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )

    def add(self, value: float) -> None:
        self._points.append(value)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if len(self._points) < 2:
            return

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        massimo = max(max(self._points), 1.0)
        larghezza = self.width() / (len(self._points) - 1)
        altezza = self.height() - 6

        percorso = QtGui.QPainterPath()
        for indice, valore in enumerate(self._points):
            x = indice * larghezza
            y = 3 + altezza * (1.0 - valore / massimo)
            percorso.lineTo(x, y) if indice else percorso.moveTo(x, y)

        colore = self._theme.color("accent.core")
        painter.setPen(QtGui.QPen(colore, 1.5))
        painter.drawPath(percorso)

        # Riempimento sotto la curva: rende leggibile l'andamento anche quando
        # i valori sono piccoli e la linea quasi piatta.
        riempimento = QtGui.QPainterPath(percorso)
        riempimento.lineTo(self.width(), self.height())
        riempimento.lineTo(0, self.height())
        riempimento.closeSubpath()
        colore.setAlphaF(0.12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colore)
        painter.drawPath(riempimento)
        painter.end()


class _Stat(QtWidgets.QFrame):
    """Riquadro con un valore e la sua etichetta."""

    def __init__(self, label: str, theme: Theme, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "panel")
        self._theme = theme

        self._value = QtWidgets.QLabel("—")
        font = self._value.font()
        font.setPointSize(font.pointSize() + 7)
        self._value.setFont(font)

        self._label = QtWidgets.QLabel(label)
        self._label.setProperty("role", "hud")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(self._value)
        layout.addWidget(self._label)

    def set(self, text: str, token: str = "text.primary") -> None:
        self._value.setText(text)
        self._value.setStyleSheet(f"color: {self._theme.color(token).name()};")


class MetricsDashboard(QtWidgets.QWidget):
    """Metriche operative in tempo reale."""

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

        self._stats = {
            "queue": _Stat("in coda", theme),
            "running": _Stat("in esecuzione", theme),
            "success": _Stat("tasso di successo", theme),
            "p95": _Stat("durata p95", theme),
            "throughput": _Stat("azioni al minuto", theme),
            "missions": _Stat("missioni attive", theme),
        }

        griglia = QtWidgets.QGridLayout()
        griglia.setSpacing(8)
        for indice, widget in enumerate(self._stats.values()):
            griglia.addWidget(widget, indice // 3, indice % 3)

        self._spark = _Sparkline(theme, self)
        spark_label = QtWidgets.QLabel("Profondità della coda nel tempo")
        spark_label.setProperty("role", "hud")

        self._detail = QtWidgets.QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(griglia)
        layout.addWidget(spark_label)
        layout.addWidget(self._spark)
        layout.addWidget(self._detail, 1)

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.OPERATIONS_METRICS, self._on_metrics, replay_last=True)
        ]

        # Il campionamento della coda è periodico e non a evento: la coda può
        # restare profonda a lungo senza che accada nulla, e un grafico
        # aggiornato solo dagli eventi mostrerebbe una linea piatta proprio nel
        # momento in cui il problema è che nulla si muove.
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event) -> None:
        self._timer.start()
        self.refresh()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    @safe_slot("ui.metrics")
    def _on_metrics(self, event: Event[OperationsMetrics]) -> None:
        self._apply(event.payload)

    def refresh(self) -> None:
        """Ricalcola dal motore e aggiorna il grafico."""
        self._apply(self._engine.metrics())

    def _apply(self, m: OperationsMetrics) -> None:
        self._stats["queue"].set(
            str(m.queue_depth), "state.warning" if m.queue_depth > 3 else "text.primary"
        )
        self._stats["running"].set(str(m.running))
        self._stats["missions"].set(str(m.missions_active))
        self._stats["throughput"].set(f"{m.throughput_per_min:.1f}".replace(".", ","))

        if m.success_rate is None:
            self._stats["success"].set("—")
        else:
            token = (
                "state.error"
                if m.success_rate < 0.7
                else "state.warning"
                if m.success_rate < 0.9
                else "state.success"
            )
            self._stats["success"].set(f"{m.success_rate * 100:.0f}%", token)

        self._stats["p95"].set(format_duration(m.p95_duration_ms))
        self._spark.add(float(m.queue_depth + m.running))

        righe = [
            "── Missioni ──",
            f"  attive              {m.missions_active}",
            f"  completate          {m.missions_completed}",
            f"  fallite             {m.missions_failed}",
            f"  di esito ignoto     {m.missions_unknown}"
            + ("   ⚠ canale caduto durante l'esecuzione" if m.missions_unknown else ""),
            "",
            "── Azioni ──",
            f"  in coda             {m.queue_depth}",
            f"  in esecuzione       {m.running}",
            f"  attendono conferma  {m.awaiting_confirmation}",
            f"  concluse            {m.actions_completed}",
            f"  durata media        {format_duration(m.avg_duration_ms)}",
            f"  durata p95          {format_duration(m.p95_duration_ms)}",
            f"  attesa in coda      {format_duration(m.avg_queue_wait_ms)}",
            "",
            "── Strumenti ──",
            f"  dichiarati          {m.tools_declared}",
            f"  usati               {m.tools_used}",
        ]
        scroll = self._detail.verticalScrollBar().value()
        self._detail.setPlainText("\n".join(righe))
        self._detail.verticalScrollBar().setValue(scroll)
