"""Widget del nucleo centrale.

E' l'elemento principale dell'interfaccia e l'unico che disegna se stesso. Fa
tre cose e nient'altro:

* ascolta ``VISUAL_MODE_CHANGED`` e chiede all'animatore la dissolvenza;
* ascolta ``AUDIO_LEVEL`` e passa l'inviluppo all'animatore;
* a ogni tick del clock avanza il moto e si ridisegna.

Non conosce macchine a stati, connessioni o backend: riceve una modalita' gia'
risolta. E' la ragione per cui aggiungere in futuro un nuovo stato non comporta
alcuna modifica qui.
"""

from __future__ import annotations

from typing import Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import AudioLevel, EventType, VisualModeChange
from core.frameclock import FrameClock
from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from core.state.machines import VisualMode
from ui.reactor.animator import ReactorAnimator
from ui.reactor.renderers.base import IReactorRenderer, Quality
from ui.reactor.renderers.painter import PainterReactorRenderer
from ui.theme.theme import Theme

__all__ = ["CoreReactorWidget"]

_log = get_logger(LogCategory.UI, "core")

#: Ogni quanti tick rivalutare la qualita' di disegno.
_QUALITY_CHECK_TICKS: Final[int] = 120

#: Soglie di carico per scendere e risalire di qualita'. La banda morta fra le
#: due impedisce l'oscillazione continua fra i due livelli.
_DOWNGRADE_LOAD: Final[float] = 1.25
_UPGRADE_LOAD: Final[float] = 0.80

#: Modalita' statiche: si ridisegnano a frequenza ridotta. In standby non ha
#: senso spendere sessanta frame al secondo per un punto che respira una volta
#: ogni otto: e' l'accorgimento che rende accettabile lasciare Jarvis acceso.
_LOW_RATE_MODES: Final[frozenset[VisualMode]] = frozenset(
    {VisualMode.STANDBY, VisualMode.OFFLINE}
)
_LOW_RATE_DIVIDER: Final[int] = 4


class CoreReactorWidget(QtWidgets.QWidget):
    """Nucleo animato di J.A.R.V.I.S."""

    def __init__(
        self,
        bus: EventBus,
        clock: FrameClock,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
        *,
        renderer: IReactorRenderer | None = None,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._clock = clock
        self._animator = ReactorAnimator(theme, self)
        self._renderer: IReactorRenderer = renderer or PainterReactorRenderer()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Il nucleo non riceve eventi del mouse: i clic passano al pannello
        # sottostante. Senza questo, un cerchio grande al centro della finestra
        # diventa una zona morta per l'interazione.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )

        if reduced_motion:
            self._animator.set_motion_scale(0.35)

        self._tick_count = 0
        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.VISUAL_MODE_CHANGED, self._on_visual_mode, replay_last=True),
            bus.subscribe(EventType.AUDIO_LEVEL, self._on_audio_level),
            bus.subscribe(EventType.AUDIO_FINISHED, self._on_audio_finished),
        ]
        clock.tick.connect(self._on_tick)

    # ------------------------------------------------------------------ #
    # Eventi del bus
    # ------------------------------------------------------------------ #

    @safe_slot("ui.reactor")
    def _on_visual_mode(self, event: Event[VisualModeChange]) -> None:
        """Avvia la dissolvenza verso la nuova modalita'."""
        try:
            mode = VisualMode(event.payload.mode)
        except ValueError:
            # Modalita' introdotta da una versione piu' recente del dominio:
            # si resta su quella corrente invece di mostrare un nucleo vuoto.
            _log.warning("Modalita' visiva sconosciuta: '%s'", event.payload.mode)
            return
        self._animator.set_mode(mode, event.payload.transition_ms)

    @safe_slot("ui.reactor")
    def _on_audio_level(self, event: Event[AudioLevel]) -> None:
        """Trasferisce l'inviluppo audio all'animatore."""
        payload = event.payload
        if payload.direction != "output":
            return
        self._animator.set_audio_level(payload.rms, payload.spectrum)

    @safe_slot("ui.reactor")
    def _on_audio_finished(self, _: Event[object]) -> None:
        self._animator.clear_audio()

    # ------------------------------------------------------------------ #
    # Ciclo di disegno
    # ------------------------------------------------------------------ #

    @safe_slot("ui.reactor")
    def _on_tick(self, dt: float) -> None:
        """Avanza il moto e richiede il ridisegno."""
        if not self.isVisible():
            return  # nessun costo per pixel che nessuno guarda

        self._animator.advance(dt)
        self._tick_count += 1

        if self._tick_count % _QUALITY_CHECK_TICKS == 0:
            self._adjust_quality()

        if (
            self._animator.mode in _LOW_RATE_MODES
            and not self._animator.is_transitioning
            and self._tick_count % _LOW_RATE_DIVIDER
        ):
            return

        self.update()

    def _adjust_quality(self) -> None:
        """Adatta il dettaglio al carico misurato."""
        load = self._clock.load
        if load > _DOWNGRADE_LOAD:
            self._renderer.set_quality(Quality.LOW)
        elif load < _UPGRADE_LOAD:
            self._renderer.set_quality(Quality.HIGH)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        """Disegna il fotogramma corrente."""
        painter = QtGui.QPainter(self)
        try:
            self._renderer.render(
                painter, QtCore.QRectF(self.rect()), self._animator.frame()
            )
        except Exception:
            _log.exception("Errore nel disegno del nucleo")
        finally:
            painter.end()

    # ------------------------------------------------------------------ #
    # Ciclo di vita
    # ------------------------------------------------------------------ #

    def set_reduced_motion(self, enabled: bool) -> None:
        """Applica la preferenza di accessibilita' sul movimento."""
        self._animator.set_motion_scale(0.35 if enabled else 1.0)

    def reload_theme(self, theme: Theme) -> None:
        """Applica un tema diverso, con dissolvenza."""
        self._renderer.invalidate()
        self._animator.reload_theme(theme)

    @property
    def animator(self) -> ReactorAnimator:
        """Animatore sottostante. Esposto per i test e per il pannello di prova."""
        return self._animator

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Rilascia le sottoscrizioni alla chiusura."""
        for subscription in self._subscriptions:
            subscription.unsubscribe()
        self._subscriptions.clear()
        super().closeEvent(event)
