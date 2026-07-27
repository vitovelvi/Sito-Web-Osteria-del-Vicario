"""Striscia di stato: cio' che l'interfaccia sa, e nient'altro.

Regola che governa ogni etichetta di questo modulo: **si mostra solo cio' che e'
stato verificato**. Latenza sconosciuta si scrive "—", non "0 ms"; modello non
dichiarato si scrive "non dichiarato", non si inventa. Un HUD che riempie i
vuoti con valori plausibili e' peggio di uno che ammette di non sapere, perche'
smette di essere una fonte affidabile proprio quando serve.
"""

from __future__ import annotations

from typing import Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import (
    BackendIdentity,
    CapabilitySet,
    EventType,
    LatencySample,
    LinkStatus,
    ServiceStatus,
)
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from core.state.machines import LinkState
from ui.theme.theme import Theme

__all__ = ["StatusStrip"]

#: Testo mostrato per ciascuno stato del canale.
_LINK_LABEL: Final[dict[str, str]] = {
    LinkState.OFFLINE.value: "Non connesso",
    LinkState.CONNECTING.value: "Connessione a Jarvis…",
    LinkState.ONLINE.value: "Jarvis online",
    LinkState.DEGRADED.value: "Connessione lenta",
}

#: Colore del punto di stato, per token di tema.
_LINK_COLOR: Final[dict[str, str]] = {
    LinkState.OFFLINE.value: "state.offline",
    LinkState.CONNECTING.value: "state.connecting",
    LinkState.ONLINE.value: "state.success",
    LinkState.DEGRADED.value: "state.warning",
}


class _StatusDot(QtWidgets.QWidget):
    """Punto colorato che pulsa mentre la connessione e' in corso."""

    def __init__(self, theme: Theme, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._color = theme.color("state.offline")
        self._pulsing = False
        self._phase = 0.0
        self.setFixedSize(10, 10)

        # Timer locale a bassa frequenza: e' un solo punto e non giustifica di
        # agganciarsi al clock principale, che serve al nucleo.
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    def set_state(self, color: QtGui.QColor, pulsing: bool) -> None:
        self._color = color
        self._pulsing = pulsing
        if pulsing and not self._timer.isActive():
            self._timer.start()
        elif not pulsing and self._timer.isActive():
            self._timer.stop()
            self._phase = 0.0
        self.update()

    def _advance(self) -> None:
        self._phase = (self._phase + 0.06) % 1.0
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        import math

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        color = QtGui.QColor(self._color)
        if self._pulsing:
            color.setAlphaF(0.45 + 0.55 * (0.5 + 0.5 * math.sin(self._phase * math.tau)))
        painter.setBrush(color)
        painter.drawEllipse(self.rect().center(), 4, 4)
        painter.end()


class StatusStrip(QtWidgets.QFrame):
    """Riga di stato con canale, latenza, modello e capability."""

    def __init__(
        self,
        bus: EventBus,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setProperty("role", "panel")

        self._dot = _StatusDot(theme, self)
        self._link = self._label("Non connesso")
        self._latency = self._label("—")
        self._model = self._label("modello non dichiarato")
        self._capabilities = self._label("nessuna capability")
        self._services = self._label("")

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        layout.addWidget(self._dot)
        layout.addWidget(self._link)
        layout.addWidget(self._separator())
        layout.addWidget(self._latency)
        layout.addWidget(self._separator())
        layout.addWidget(self._model)
        layout.addStretch(1)
        layout.addWidget(self._services)
        layout.addWidget(self._capabilities)

        self._degraded_services: set[str] = set()
        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.LINK_STATE_CHANGED, self._on_link, replay_last=True),
            bus.subscribe(EventType.TRANSPORT_LATENCY, self._on_latency),
            bus.subscribe(EventType.IDENTITY_UPDATED, self._on_identity, replay_last=True),
            bus.subscribe(EventType.CAPABILITIES_UPDATED, self._on_capabilities, replay_last=True),
            bus.subscribe(EventType.SERVICE_STATUS_CHANGED, self._on_service),
        ]

    # ------------------------------------------------------------------ #
    # Costruzione
    # ------------------------------------------------------------------ #

    def _label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setProperty("role", "hud")
        return label

    def _separator(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        line.setProperty("role", "separator")
        line.setFixedWidth(1)
        return line

    # ------------------------------------------------------------------ #
    # Eventi
    # ------------------------------------------------------------------ #

    @safe_slot("ui.hud")
    def _on_link(self, event: Event[LinkStatus]) -> None:
        state = event.payload.state
        self._link.setText(_LINK_LABEL.get(state, state))
        self._dot.set_state(
            self._theme.color(_LINK_COLOR.get(state, "state.offline")),
            pulsing=state == LinkState.CONNECTING.value,
        )
        if state != LinkState.ONLINE.value:
            # Senza canale la latenza misurata non significa piu' nulla.
            self._latency.setText("—")

    @safe_slot("ui.hud")
    def _on_latency(self, event: Event[LatencySample]) -> None:
        sample = event.payload
        average = sample.average_ms if sample.average_ms is not None else sample.rtt_ms
        self._latency.setText(f"{average:.0f} ms")

    @safe_slot("ui.hud")
    def _on_identity(self, event: Event[BackendIdentity]) -> None:
        identity = event.payload
        self._model.setText(identity.model or "modello non dichiarato")

    @safe_slot("ui.hud")
    def _on_capabilities(self, event: Event[CapabilitySet]) -> None:
        granted = event.payload.granted
        if not granted:
            self._capabilities.setText("nessuna capability")
            self._capabilities.setToolTip("")
            return
        self._capabilities.setText(f"{len(granted)} capability")
        tooltip = "\n".join(sorted(granted))
        if event.payload.unknown:
            tooltip += "\n\nDichiarate ma non supportate da questa versione:\n"
            tooltip += "\n".join(sorted(event.payload.unknown))
        self._capabilities.setToolTip(tooltip)

    @safe_slot("ui.hud")
    def _on_service(self, event: Event[ServiceStatus]) -> None:
        """Segnala i servizi in difficolta' senza interrompere nulla."""
        status = event.payload
        if status.status in ("failed", "degraded"):
            self._degraded_services.add(status.name)
        else:
            self._degraded_services.discard(status.name)

        if not self._degraded_services:
            self._services.setText("")
            self._services.setToolTip("")
            return
        self._services.setText(f"⚠ {len(self._degraded_services)}")
        self._services.setToolTip(
            "Servizi non operativi:\n" + "\n".join(sorted(self._degraded_services))
        )
