"""Animatore del nucleo: dissolvenze fra stati e moto continuo.

Divisione dei compiti, che e' il punto dell'intero modulo:

* **``QVariantAnimation``** governa la *dissolvenza* fra due preset. Una sola
  animazione attiva alla volta, con curva di easing — esattamente cio' per cui
  la classe e' fatta.
* **``FrameClock``** governa il *moto continuo* (rotazione, onde, respiro,
  impulsi). Sono integrazioni sul tempo, non transizioni: affidarle a
  ``QPropertyAnimation`` significherebbe otto timer indipendenti e frame
  sfasati (docs §2.2).

L'animatore non disegna e non conosce widget: produce un :class:`ReactorFrame`.
Puo' quindi essere testato senza aprire una finestra.
"""

from __future__ import annotations

import math
import random
from typing import Final

from core.logging_setup import LogCategory, get_logger
from core.qtcompat import QtCore, QtGui
from core.state.machines import VisualMode
from ui.reactor.params import ReactorFrame, ReactorParams, blend, preset_for
from ui.theme.theme import Theme

__all__ = ["ReactorAnimator"]

_log = get_logger(LogCategory.UI, "reactor")

#: Durata di vita di un'onda concentrica, in secondi.
_WAVE_LIFETIME: Final[float] = 2.4

#: Durata di vita di un impulso.
_IMPULSE_LIFETIME: Final[float] = 0.85

#: Numero di barre dell'equalizzatore radiale.
_SPECTRUM_BARS: Final[int] = 28

#: Attacco e rilascio dell'inviluppo, in unita' al secondo. L'attacco e' rapido
#: e il rilascio lento: e' il comportamento di un VU meter, e senza questa
#: asimmetria l'equalizzatore sfarfalla invece di "respirare" con la voce.
_ENVELOPE_ATTACK: Final[float] = 14.0
_ENVELOPE_RELEASE: Final[float] = 4.5

#: Oltre questo numero di onde attive si smette di emetterne: protegge dal caso
#: in cui il clock si fermi e riparta con un delta accumulato.
_MAX_WAVES: Final[int] = 8
_MAX_IMPULSES: Final[int] = 6


class ReactorAnimator(QtCore.QObject):
    """Fa evolvere i parametri del nucleo nel tempo."""

    def __init__(self, theme: Theme, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._mode = VisualMode.BOOT

        self._target = self._preset(VisualMode.BOOT)
        self._from = self._target.copy()
        self._current = self._target.copy()

        # Una sola animazione di dissolvenza, riusata a ogni cambio di modalita'.
        self._fade = QtCore.QVariantAnimation(self)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)
        self._fade.valueChanged.connect(self._on_fade)
        self._blend_t = 1.0

        # Moto continuo.
        self._rotation = 0.0
        self._pulse_phase = 0.0
        self._waves: list[float] = []
        self._impulses: list[float] = []
        self._wave_accumulator = 0.0
        self._impulse_accumulator = 0.0

        # Inviluppo audio.
        self._spectrum = [0.0] * _SPECTRUM_BARS
        self._spectrum_target = [0.0] * _SPECTRUM_BARS
        self._level = 0.0
        self._level_target = 0.0
        self._has_real_audio = False

        self._jitter = (0.0, 0.0)
        # Seme fisso: il tremolio d'errore deve essere riproducibile nei test.
        self._rng = random.Random(0x4A5256)

        self._motion_scale = 1.0

    # ------------------------------------------------------------------ #
    # Modalita'
    # ------------------------------------------------------------------ #

    @property
    def mode(self) -> VisualMode:
        """Modalita' attualmente mostrata."""
        return self._mode

    def set_mode(self, mode: VisualMode, transition_ms: int) -> None:
        """Avvia la dissolvenza verso una nuova modalita'.

        :param transition_ms: durata, decisa dal dominio
            (:func:`core.state.resolver.transition_duration`) e non dal widget:
            la velocita' con cui un errore appare e' una scelta di prodotto.
        """
        if mode is self._mode:
            return

        # Si riparte dai parametri **correnti**, non dal preset di partenza: se
        # una dissolvenza e' ancora in corso, il nuovo innesto deve agganciarsi
        # a cio' che si vede adesso, altrimenti si ottiene uno scatto proprio
        # nel caso che questo sistema esiste per evitare.
        self._from = self._current.copy()
        self._target = self._preset(mode)
        self._mode = mode

        if transition_ms <= 0:
            self._blend_t = 1.0
            self._current = self._target.copy()
            return

        self._fade.stop()
        self._fade.setDuration(transition_ms)
        self._blend_t = 0.0
        self._fade.start()
        _log.debug("Dissolvenza verso '%s' in %d ms", mode.value, transition_ms)

    def _preset(self, mode: VisualMode) -> ReactorParams:
        """Preset di una modalita' con i colori del tema corrente."""
        color = self._theme.state_color(mode.value)
        glow = self._theme.color("accent.glow")
        # In errore e conferma l'alone segue il colore di stato: un alone blu
        # attorno a un nucleo rosso trasmetterebbe un messaggio confuso.
        if mode in (VisualMode.ERROR, VisualMode.SUCCESS):
            glow = QtGui.QColor(color)
        return preset_for(mode, color, glow)

    def _on_fade(self, value: object) -> None:
        """Aggiorna il fattore di miscelazione durante la dissolvenza."""
        try:
            self._blend_t = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            self._blend_t = 1.0

    # ------------------------------------------------------------------ #
    # Audio
    # ------------------------------------------------------------------ #

    def set_audio_level(self, level: float, spectrum: tuple[float, ...] = ()) -> None:
        """Aggiorna l'inviluppo audio da riprodurre nell'equalizzatore.

        Chiamato dagli eventi ``AUDIO_LEVEL``. Quando il backend streamma la
        voce, l'equalizzatore segue l'ampiezza **reale**: e' cio' che distingue
        un'animazione sincronizzata da un'animazione decorativa.
        """
        self._level_target = max(0.0, min(1.0, level))
        self._has_real_audio = True

        if not spectrum:
            return
        # Si ricampiona lo spettro ricevuto sul numero di barre da disegnare:
        # il produttore audio non deve conoscere la grafica.
        bins = len(spectrum)
        for i in range(_SPECTRUM_BARS):
            source = spectrum[min(bins - 1, i * bins // _SPECTRUM_BARS)]
            self._spectrum_target[i] = max(0.0, min(1.0, source))

    def clear_audio(self) -> None:
        """Segnala la fine della riproduzione: l'inviluppo decade a zero."""
        self._level_target = 0.0
        self._spectrum_target = [0.0] * _SPECTRUM_BARS
        self._has_real_audio = False

    # ------------------------------------------------------------------ #
    # Avanzamento
    # ------------------------------------------------------------------ #

    def set_motion_scale(self, scale: float) -> None:
        """Rallenta o accelera globalmente il moto continuo.

        Serve al rispetto della preferenza di accessibilita' "riduci
        animazioni": si porta a un valore basso invece di congelare tutto.
        Un'interfaccia immobile sembra bloccata, che e' proprio l'impressione
        che il nucleo esiste per smentire.
        """
        self._motion_scale = max(0.0, min(2.0, scale))

    def advance(self, dt: float) -> None:
        """Fa avanzare il moto di ``dt`` secondi. Invocato dal FrameClock."""
        # Un delta anomalo (sospensione del sistema, dialogo modale) non deve
        # far saltare le animazioni in avanti.
        dt = max(0.0, min(dt, 0.1)) * self._motion_scale

        self._current = blend(self._from, self._target, self._blend_t)
        p = self._current

        self._rotation = (self._rotation + p.rotation_speed * dt) % 360.0
        self._pulse_phase = (self._pulse_phase + p.pulse_hz * dt) % 1.0

        self._advance_waves(dt, p)
        self._advance_impulses(dt, p)
        self._advance_envelope(dt, p)

        if p.jitter > 0.01:
            amplitude = p.jitter * p.energy
            self._jitter = (
                self._rng.uniform(-amplitude, amplitude),
                self._rng.uniform(-amplitude, amplitude),
            )
        else:
            self._jitter = (0.0, 0.0)

    def _advance_waves(self, dt: float, p: ReactorParams) -> None:
        """Emette e fa avanzare le onde concentriche."""
        self._waves = [w + dt / _WAVE_LIFETIME for w in self._waves]
        self._waves = [w for w in self._waves if w < 1.0]

        if p.wave_rate <= 0.0:
            return
        self._wave_accumulator += dt * p.wave_rate
        while self._wave_accumulator >= 1.0 and len(self._waves) < _MAX_WAVES:
            self._wave_accumulator -= 1.0
            self._waves.append(0.0)
        # Se il tetto e' stato raggiunto si scarta l'arretrato invece di
        # accumularlo: al ritorno dalla sospensione non deve partire una raffica.
        if len(self._waves) >= _MAX_WAVES:
            self._wave_accumulator = 0.0

    def _advance_impulses(self, dt: float, p: ReactorParams) -> None:
        """Emette e fa avanzare gli impulsi dell'esecuzione."""
        self._impulses = [i + dt / _IMPULSE_LIFETIME for i in self._impulses]
        self._impulses = [i for i in self._impulses if i < 1.0]

        if p.impulse_rate <= 0.0:
            return
        self._impulse_accumulator += dt * p.impulse_rate
        while self._impulse_accumulator >= 1.0 and len(self._impulses) < _MAX_IMPULSES:
            self._impulse_accumulator -= 1.0
            self._impulses.append(0.0)
        if len(self._impulses) >= _MAX_IMPULSES:
            self._impulse_accumulator = 0.0

    def _advance_envelope(self, dt: float, p: ReactorParams) -> None:
        """Fa evolvere livello e spettro con attacco rapido e rilascio lento."""
        if p.bar_strength > 0.01 and not self._has_real_audio:
            # Senza audio reale — backend che non streamma, oppure modalita' di
            # prova — si sintetizza un inviluppo plausibile. Non e' un inganno:
            # e' l'unico modo di mostrare "sta parlando" quando l'ampiezza non
            # arriva, e appena arriva quella vera prende il sopravvento.
            base = 0.45 + 0.35 * math.sin(self._pulse_phase * math.tau * 3.0)
            self._level_target = max(0.0, min(1.0, base))
            for i in range(_SPECTRUM_BARS):
                wobble = math.sin(
                    self._pulse_phase * math.tau * (2.0 + i * 0.35) + i * 0.7
                )
                self._spectrum_target[i] = max(0.0, base * (0.55 + 0.45 * wobble))

        self._level = _approach(self._level, self._level_target, dt)
        for i in range(_SPECTRUM_BARS):
            self._spectrum[i] = _approach(self._spectrum[i], self._spectrum_target[i], dt)

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def frame(self) -> ReactorFrame:
        """Fotogramma corrente, pronto per il renderer."""
        p = self._current
        pulse = math.sin(self._pulse_phase * math.tau)
        return ReactorFrame(
            params=p,
            rotation_deg=self._rotation,
            pulse=pulse,
            waves=tuple(self._waves),
            impulses=tuple(self._impulses),
            spectrum=tuple(self._spectrum),
            level=self._level,
            jitter_offset=self._jitter,
        )

    @property
    def is_transitioning(self) -> bool:
        """Vero mentre una dissolvenza e' in corso."""
        return self._fade.state() == QtCore.QAbstractAnimation.State.Running

    def reload_theme(self, theme: Theme) -> None:
        """Applica un tema diverso senza interrompere il moto."""
        self._theme = theme
        self._target = self._preset(self._mode)
        self._from = self._current.copy()
        self._blend_t = 0.0
        self._fade.stop()
        self._fade.setDuration(self._theme.ms("normal"))
        self._fade.start()


def _approach(current: float, target: float, dt: float) -> float:
    """Avvicina ``current`` a ``target`` con attacco rapido e rilascio lento."""
    rate = _ENVELOPE_ATTACK if target > current else _ENVELOPE_RELEASE
    factor = min(1.0, rate * dt)
    return current + (target - current) * factor
