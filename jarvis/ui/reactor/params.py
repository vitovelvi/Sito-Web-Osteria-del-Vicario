"""Parametri del nucleo e preset per modalita' visiva.

Il nucleo e' descritto **interamente da scalari**. Nessuna animazione manipola
direttamente il disegno: l'animatore fa evolvere questi numeri, il renderer li
legge e basta.

E' questa separazione a rendere possibile la dissolvenza fra stati. Passare da
"ascolto" a "elaborazione" non e' scambiare due animazioni — sarebbe uno scatto:
e' interpolare due insiemi di parametri. Ed e' anche cio' che rende sostituibile
il renderer (QPainter oggi, QML con shader domani) senza toccare la logica.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from core.qtcompat import QtGui
from core.state.machines import VisualMode

__all__ = ["ReactorFrame", "ReactorParams", "blend", "preset_for"]


@dataclass(slots=True)
class ReactorParams:
    """Aspetto statico del nucleo in una data modalita'.

    Tutti i campi sono interpolabili: e' il requisito che permette di fondere
    due preset senza casi speciali.
    """

    color: QtGui.QColor
    """Colore dominante del nucleo e degli anelli."""

    glow: QtGui.QColor
    """Colore dell'alone. Spesso piu' saturo del colore principale."""

    energy: float = 1.0
    """Intensita' complessiva (0-1): scala opacita' e ampiezze."""

    pulse_hz: float = 0.35
    """Frequenza del respiro. 0.35 Hz ≈ un ciclo ogni tre secondi: il ritmo di
    un respiro a riposo, non di un indicatore di caricamento."""

    pulse_depth: float = 0.10
    """Ampiezza del respiro come frazione del raggio."""

    rotation_speed: float = 0.0
    """Velocita' degli archi in gradi al secondo. Il segno inverte il verso."""

    wave_rate: float = 0.0
    """Onde concentriche emesse al secondo."""

    wave_strength: float = 0.0
    """Opacita' iniziale delle onde (0-1)."""

    bar_strength: float = 0.0
    """Intensita' dell'equalizzatore radiale (0-1)."""

    impulse_rate: float = 0.0
    """Impulsi emessi al secondo."""

    ring_opacity: float = 0.5
    """Opacita' degli anelli fissi."""

    glow_strength: float = 0.6
    """Intensita' dell'alone (0-1)."""

    jitter: float = 0.0
    """Tremolio in pixel. Usato solo in errore."""

    core_ratio: float = 0.34
    """Raggio del disco centrale come frazione del raggio disponibile."""

    def copy(self) -> ReactorParams:
        """Copia indipendente, con i colori duplicati."""
        return replace(self, color=QtGui.QColor(self.color), glow=QtGui.QColor(self.glow))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_color(a: QtGui.QColor, b: QtGui.QColor, t: float) -> QtGui.QColor:
    """Interpola due colori in HSV.

    In RGB il passaggio fra due tinte sature attraversa il grigio a meta' strada
    — il nucleo sbiadirebbe per un istante a ogni cambio di stato. In HSV la
    tinta ruota e la saturazione resta, che e' l'effetto voluto.
    """
    ha, sa, va, aa = a.getHsvF()
    hb, sb, vb, ab = b.getHsvF()

    # Tinta non definita (grigio puro): si eredita quella dell'altro estremo.
    if ha < 0:
        ha = hb
    if hb < 0:
        hb = ha
    if ha < 0 and hb < 0:
        ha = hb = 0.0

    # Si percorre l'arco piu' breve del cerchio cromatico.
    delta = hb - ha
    if delta > 0.5:
        ha += 1.0
    elif delta < -0.5:
        hb += 1.0

    hue = (_lerp(ha, hb, t)) % 1.0
    result = QtGui.QColor()
    result.setHsvF(hue, _lerp(sa, sb, t), _lerp(va, vb, t), _lerp(aa, ab, t))
    return result


def blend(a: ReactorParams, b: ReactorParams, t: float) -> ReactorParams:
    """Fonde due preset. ``t`` = 0 restituisce ``a``, ``t`` = 1 restituisce ``b``."""
    t = max(0.0, min(1.0, t))
    return ReactorParams(
        color=_lerp_color(a.color, b.color, t),
        glow=_lerp_color(a.glow, b.glow, t),
        energy=_lerp(a.energy, b.energy, t),
        pulse_hz=_lerp(a.pulse_hz, b.pulse_hz, t),
        pulse_depth=_lerp(a.pulse_depth, b.pulse_depth, t),
        rotation_speed=_lerp(a.rotation_speed, b.rotation_speed, t),
        wave_rate=_lerp(a.wave_rate, b.wave_rate, t),
        wave_strength=_lerp(a.wave_strength, b.wave_strength, t),
        bar_strength=_lerp(a.bar_strength, b.bar_strength, t),
        impulse_rate=_lerp(a.impulse_rate, b.impulse_rate, t),
        ring_opacity=_lerp(a.ring_opacity, b.ring_opacity, t),
        glow_strength=_lerp(a.glow_strength, b.glow_strength, t),
        jitter=_lerp(a.jitter, b.jitter, t),
        core_ratio=_lerp(a.core_ratio, b.core_ratio, t),
    )


@dataclass(slots=True)
class ReactorFrame:
    """Tutto cio' che serve a disegnare **un** fotogramma.

    Separa l'aspetto (``params``, interpolato) dal moto (fasi e liste, prodotte
    dall'animatore integrando il tempo). Il renderer non ha memoria: riceve
    questo oggetto e disegna, il che lo rende banale da testare e sostituire.
    """

    params: ReactorParams
    rotation_deg: float = 0.0
    pulse: float = 0.0
    """Valore del respiro in [-1, 1]."""

    waves: tuple[float, ...] = ()
    """Avanzamento delle onde attive, ciascuna in [0, 1]."""

    impulses: tuple[float, ...] = ()
    """Avanzamento degli impulsi attivi, ciascuno in [0, 1]."""

    spectrum: tuple[float, ...] = ()
    """Ampiezze dell'equalizzatore, gia' smorzate."""

    level: float = 0.0
    """Livello audio istantaneo (0-1)."""

    jitter_offset: tuple[float, float] = (0.0, 0.0)


# --------------------------------------------------------------------------- #
# Preset per modalita'
# --------------------------------------------------------------------------- #
#
# I colori arrivano dal tema (ui/theme/tokens.json) e vengono iniettati da
# `preset_for`: qui si descrive il **comportamento**, non la tinta.


def _params(color: QtGui.QColor, glow: QtGui.QColor, **overrides: float) -> ReactorParams:
    return ReactorParams(color=color, glow=glow, **overrides)  # type: ignore[arg-type]


#: Comportamento di ciascuna modalita'. I valori sono stati scelti per lettura a
#: schermo, non per massimizzare il movimento: un'interfaccia che deve restare
#: accesa tutto il giorno non puo' agitarsi.
_BEHAVIOUR: Final[dict[VisualMode, dict[str, float]]] = {
    # Riposo: respiro lento e ampio. Nessuna rotazione.
    VisualMode.IDLE: {
        "energy": 0.85, "pulse_hz": 0.28, "pulse_depth": 0.055,
        "ring_opacity": 0.42, "glow_strength": 0.55, "core_ratio": 0.34,
    },
    # Ascolto: onde concentriche verso l'esterno, respiro piu' rapido.
    VisualMode.LISTENING: {
        "energy": 1.0, "pulse_hz": 0.9, "pulse_depth": 0.035,
        "wave_rate": 1.6, "wave_strength": 0.75,
        "ring_opacity": 0.6, "glow_strength": 0.85, "core_ratio": 0.30,
    },
    # Elaborazione: archi in rotazione, respiro quasi assente. Il movimento
    # rotatorio comunica lavoro senza suggerire attesa passiva.
    VisualMode.THINKING: {
        "energy": 0.95, "pulse_hz": 0.5, "pulse_depth": 0.02,
        "rotation_speed": 84.0, "ring_opacity": 0.72, "glow_strength": 0.7,
        "core_ratio": 0.28,
    },
    # Esecuzione: impulsi discreti verso l'esterno, rotazione inversa piu' lenta.
    VisualMode.EXECUTING: {
        "energy": 1.0, "pulse_hz": 0.6, "pulse_depth": 0.03,
        "rotation_speed": -52.0, "impulse_rate": 2.2,
        "ring_opacity": 0.68, "glow_strength": 0.8, "core_ratio": 0.31,
    },
    # Voce: equalizzatore radiale pilotato dall'ampiezza reale dell'audio.
    VisualMode.SPEAKING: {
        "energy": 1.0, "pulse_hz": 0.45, "pulse_depth": 0.025,
        "bar_strength": 1.0, "rotation_speed": 12.0,
        "ring_opacity": 0.55, "glow_strength": 0.95, "core_ratio": 0.30,
    },
    # Conferma: lampo breve e luminoso, senza moto.
    VisualMode.SUCCESS: {
        "energy": 1.0, "pulse_hz": 1.4, "pulse_depth": 0.07,
        "wave_rate": 2.4, "wave_strength": 0.9,
        "ring_opacity": 0.8, "glow_strength": 1.0, "core_ratio": 0.36,
    },
    # Errore: pulsazione rapida e tremolio contenuto. Il tremolio e' 1.5 px:
    # deve dare allarme, non rendere illeggibile l'interfaccia.
    VisualMode.ERROR: {
        "energy": 1.0, "pulse_hz": 2.2, "pulse_depth": 0.05,
        "ring_opacity": 0.75, "glow_strength": 0.9, "jitter": 1.5,
        "core_ratio": 0.33,
    },
    # Avvio: nucleo piccolo che si accende progressivamente.
    VisualMode.BOOT: {
        "energy": 0.5, "pulse_hz": 0.7, "pulse_depth": 0.09,
        "ring_opacity": 0.25, "glow_strength": 0.35, "core_ratio": 0.20,
    },
    # Connessione: onde lente e regolari, come un segnale che cerca risposta.
    VisualMode.CONNECTING: {
        "energy": 0.7, "pulse_hz": 0.8, "pulse_depth": 0.04,
        "wave_rate": 0.8, "wave_strength": 0.4, "rotation_speed": 30.0,
        "ring_opacity": 0.35, "glow_strength": 0.45, "core_ratio": 0.26,
    },
    # Offline: quasi spento, ma non immobile — l'interfaccia e' viva, il canale no.
    VisualMode.OFFLINE: {
        "energy": 0.35, "pulse_hz": 0.18, "pulse_depth": 0.03,
        "ring_opacity": 0.2, "glow_strength": 0.15, "core_ratio": 0.24,
    },
    # Standby: minimo assoluto. Anche il costo di disegno deve essere minimo.
    VisualMode.STANDBY: {
        "energy": 0.18, "pulse_hz": 0.12, "pulse_depth": 0.02,
        "ring_opacity": 0.12, "glow_strength": 0.08, "core_ratio": 0.18,
    },
}


def preset_for(mode: VisualMode, color: QtGui.QColor, glow: QtGui.QColor) -> ReactorParams:
    """Costruisce i parametri di una modalita' con i colori del tema.

    :param mode: modalita' visiva risolta dallo state manager.
    :param color: colore principale, dal token ``color.state.<mode>``.
    :param glow: colore dell'alone.
    """
    return _params(QtGui.QColor(color), QtGui.QColor(glow), **_BEHAVIOUR.get(mode, {}))
