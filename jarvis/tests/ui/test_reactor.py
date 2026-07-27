"""Test del nucleo: parametri, animatore, renderer.

L'animatore e' testabile **senza aprire una finestra**, perche' non disegna e
non conosce widget: produce un :class:`ReactorFrame`. E' il vantaggio pratico
della separazione fra aspetto, moto e disegno.
"""

from __future__ import annotations

import pytest

from core.qtcompat import QtCore, QtGui
from core.state.machines import VisualMode
from ui.reactor.animator import ReactorAnimator
from ui.reactor.params import blend, preset_for
from ui.reactor.renderers.base import Quality
from ui.reactor.renderers.painter import PainterReactorRenderer
from ui.theme.theme import load_theme


@pytest.fixture
def theme():
    return load_theme()


@pytest.fixture
def animator(qt_app, theme) -> ReactorAnimator:
    return ReactorAnimator(theme)


def _advance(animator: ReactorAnimator, seconds: float, step: float = 1 / 60) -> None:
    for _ in range(int(seconds / step)):
        animator.advance(step)


# --------------------------------------------------------------------------- #
# Parametri
# --------------------------------------------------------------------------- #


def test_blend_agli_estremi(theme) -> None:
    a = preset_for(VisualMode.IDLE, theme.state_color("idle"), theme.color("accent.glow"))
    b = preset_for(VisualMode.ERROR, theme.state_color("error"), theme.color("accent.glow"))

    assert blend(a, b, 0.0).pulse_hz == pytest.approx(a.pulse_hz)
    assert blend(a, b, 1.0).pulse_hz == pytest.approx(b.pulse_hz)


def test_blend_intermedio_e_monotono(theme) -> None:
    a = preset_for(VisualMode.IDLE, theme.state_color("idle"), theme.color("accent.glow"))
    b = preset_for(VisualMode.ERROR, theme.state_color("error"), theme.color("accent.glow"))

    valori = [blend(a, b, t / 10).pulse_hz for t in range(11)]
    assert valori == sorted(valori)  # da 0.28 a 2.2: crescita monotona


def test_blend_fuori_range_viene_limitato(theme) -> None:
    a = preset_for(VisualMode.IDLE, theme.state_color("idle"), theme.color("accent.glow"))
    b = preset_for(VisualMode.ERROR, theme.state_color("error"), theme.color("accent.glow"))
    assert blend(a, b, 5.0).pulse_hz == pytest.approx(b.pulse_hz)
    assert blend(a, b, -3.0).pulse_hz == pytest.approx(a.pulse_hz)


def test_colore_interpolato_non_passa_dal_grigio(theme) -> None:
    """L'interpolazione e' in HSV proprio per evitare lo sbiadimento a meta'.

    In RGB, blu → rosso attraversa un grigio spento: il nucleo sembrerebbe
    spegnersi a ogni cambio di stato.
    """
    a = preset_for(VisualMode.IDLE, QtGui.QColor("#3fa9f5"), QtGui.QColor("#3fa9f5"))
    b = preset_for(VisualMode.ERROR, QtGui.QColor("#ff4d5e"), QtGui.QColor("#ff4d5e"))

    meta = blend(a, b, 0.5).color
    _, saturazione, valore, _ = meta.getHsvF()

    assert saturazione > 0.5
    assert valore > 0.5


# --------------------------------------------------------------------------- #
# Animatore
# --------------------------------------------------------------------------- #


def test_cambio_modalita_immediato_senza_transizione(animator) -> None:
    animator.set_mode(VisualMode.ERROR, 0)
    assert animator.mode is VisualMode.ERROR
    assert not animator.is_transitioning


def test_rotazione_avanza_solo_dove_prevista(animator) -> None:
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 1.0)
    assert animator.frame().rotation_deg == pytest.approx(0.0)

    animator.set_mode(VisualMode.THINKING, 0)
    _advance(animator, 1.0)
    assert animator.frame().rotation_deg > 10.0


def test_onde_emesse_in_ascolto(animator) -> None:
    animator.set_mode(VisualMode.LISTENING, 0)
    _advance(animator, 1.5)
    assert animator.frame().waves


def test_nessuna_onda_a_riposo(animator) -> None:
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 2.0)
    assert animator.frame().waves == ()


def test_onde_limitate(animator) -> None:
    """Un delta accumulato non deve produrre una raffica al risveglio."""
    animator.set_mode(VisualMode.LISTENING, 0)
    for _ in range(50):
        animator.advance(0.1)
    assert len(animator.frame().waves) <= 8


def test_delta_anomalo_non_fa_saltare_le_animazioni(animator) -> None:
    """Una sospensione del sistema produce un delta enorme: va limitato."""
    animator.set_mode(VisualMode.THINKING, 0)
    animator.advance(30.0)  # trenta secondi di sospensione
    # Con 84 gradi/s, trenta secondi sarebbero 2520 gradi. Limitando a 0.1 s
    # l'avanzamento resta sotto i dieci gradi.
    assert animator.frame().rotation_deg < 10.0


def test_impulsi_in_esecuzione(animator) -> None:
    animator.set_mode(VisualMode.EXECUTING, 0)
    _advance(animator, 1.5)
    assert animator.frame().impulses


def test_inviluppo_audio_reale_prevale(animator) -> None:
    """Con l'ampiezza reale, l'equalizzatore la segue invece di inventarla."""
    animator.set_mode(VisualMode.SPEAKING, 0)
    animator.set_audio_level(0.9, tuple([0.9] * 16))
    _advance(animator, 0.5)

    assert animator.frame().level > 0.6


def test_inviluppo_decade_a_fine_riproduzione(animator) -> None:
    animator.set_mode(VisualMode.SPEAKING, 0)
    animator.set_audio_level(1.0)
    _advance(animator, 0.5)
    picco = animator.frame().level

    animator.clear_audio()
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 1.5)

    assert animator.frame().level < picco * 0.5


def test_attacco_piu_rapido_del_rilascio(animator) -> None:
    """Senza questa asimmetria l'equalizzatore sfarfalla invece di respirare."""
    animator.set_mode(VisualMode.IDLE, 0)

    animator.set_audio_level(1.0)
    _advance(animator, 0.1)
    salita = animator.frame().level

    animator.set_audio_level(0.0)
    _advance(animator, 0.1)
    discesa = salita - animator.frame().level

    assert salita > discesa


def test_tremolio_solo_in_errore(animator) -> None:
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 0.5)
    assert animator.frame().jitter_offset == (0.0, 0.0)

    animator.set_mode(VisualMode.ERROR, 0)
    _advance(animator, 0.5)
    assert animator.frame().jitter_offset != (0.0, 0.0)


def test_motion_scale_rallenta_il_moto(animator) -> None:
    """Preferenza di accessibilita': si rallenta, non si congela."""
    animator.set_mode(VisualMode.THINKING, 0)
    _advance(animator, 1.0)
    pieno = animator.frame().rotation_deg

    ridotto_animator = animator
    ridotto_animator.set_motion_scale(0.35)
    prima = ridotto_animator.frame().rotation_deg
    _advance(ridotto_animator, 1.0)
    ridotto = ridotto_animator.frame().rotation_deg - prima

    assert 0 < ridotto < pieno


def test_transizione_si_aggancia_ai_valori_correnti(animator, qt_app) -> None:
    """Interrompere una dissolvenza non deve produrre uno scatto."""
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 0.2)

    animator.set_mode(VisualMode.ERROR, 400)
    for _ in range(6):
        qt_app.processEvents()
        animator.advance(1 / 60)
    intermedio = animator.frame().params.pulse_hz

    animator.set_mode(VisualMode.SPEAKING, 400)
    animator.advance(1 / 60)
    dopo = animator.frame().params.pulse_hz

    # Il nuovo innesto parte da dove si era, non dal preset di riposo.
    assert abs(dopo - intermedio) < 0.5


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #


def _render(renderer: PainterReactorRenderer, animator: ReactorAnimator, size: int) -> None:
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QtGui.QPainter(image)
    renderer.render(painter, QtCore.QRectF(0, 0, size, size), animator.frame())
    painter.end()


def test_renderer_disegna_qualcosa(animator) -> None:
    renderer = PainterReactorRenderer()
    animator.set_mode(VisualMode.SPEAKING, 0)
    _advance(animator, 1.0)

    image = QtGui.QImage(200, 200, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QtGui.QPainter(image)
    renderer.render(painter, QtCore.QRectF(0, 0, 200, 200), animator.frame())
    painter.end()

    assert any(image.pixelColor(x, 100).alpha() > 0 for x in range(200))


def test_renderer_regge_dimensioni_estreme(animator) -> None:
    """Una finestra ridotta al minimo non deve produrre eccezioni."""
    renderer = PainterReactorRenderer()
    animator.set_mode(VisualMode.LISTENING, 0)
    _advance(animator, 1.0)

    for size in (1, 4, 12, 2000):
        _render(renderer, animator, size)


def test_cache_alone_riusata_durante_la_dissolvenza(animator) -> None:
    """Senza quantizzazione del colore la cache sarebbe inutile.

    E' il punto in cui l'ottimizzazione poteva silenziosamente non funzionare:
    la pixmap verrebbe rigenerata a ogni frame, costando piu' dell'effetto
    grafico che si voleva evitare.
    """
    renderer = PainterReactorRenderer()
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 0.2)

    for _ in range(60):
        animator.advance(1 / 60)
        _render(renderer, animator, 240)

    # Un secondo intero di respiro deve produrre una sola voce di cache: se ne
    # comparissero decine, la pixmap si starebbe rigenerando a ogni frame.
    assert len(renderer._glow_cache) <= 2


def test_qualita_bassa_salta_l_alone(animator) -> None:
    renderer = PainterReactorRenderer(quality=Quality.LOW)
    animator.set_mode(VisualMode.IDLE, 0)
    _advance(animator, 0.5)

    _render(renderer, animator, 240)

    assert renderer._glow_cache == {}


def test_standby_non_disegna_quasi_nulla(animator) -> None:
    """In standby il costo di disegno deve crollare, non solo l'aspetto."""
    animator.set_mode(VisualMode.STANDBY, 0)
    _advance(animator, 1.0)

    frame = animator.frame()
    assert frame.params.energy < 0.25
    assert frame.waves == ()
    assert frame.impulses == ()
