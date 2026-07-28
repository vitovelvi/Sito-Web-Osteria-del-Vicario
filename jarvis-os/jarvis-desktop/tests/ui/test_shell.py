"""Test del tema e del guscio della finestra."""

from __future__ import annotations

import pytest

from core.eventbus import EventBus
from core.events import EventType, NotificationRequest
from core.qtcompat import QtGui, QtWidgets
from core.state.machines import VisualMode
from ui.theme.theme import Theme, load_theme


@pytest.fixture
def widgets_app(qt_app):
    """Alias di ``qt_app``, che e' gia' una ``QApplication`` (vedi conftest)."""
    return qt_app


@pytest.fixture
def theme() -> Theme:
    return load_theme()


# --------------------------------------------------------------------------- #
# Tema
# --------------------------------------------------------------------------- #


def test_colori_di_stato_definiti_per_ogni_modalita(theme: Theme) -> None:
    """Ogni modalita' visiva deve avere un colore, altrimenti il nucleo e' magenta."""
    for mode in VisualMode:
        color = theme.state_color(mode.value)
        assert color.isValid()
        assert color.name() != "#ff00ff"


def test_colore_fuori_dalla_tavolozza(theme: Theme) -> None:
    """L'ombra vive sotto 'elevation', non sotto 'color'.

    Il primo tentativo cercava solo in ``color.``: l'ombra veniva disegnata
    magenta attorno all'intera finestra.
    """
    shadow = theme.color("elevation.shadowColor")
    assert shadow.isValid()
    assert shadow.name() != "#ff00ff"


def test_token_assente_non_solleva(theme: Theme) -> None:
    assert theme.px("non.esiste", 7) == 7
    assert theme.color("non.esiste").name() == "#ff00ff"  # visibile in revisione


def test_qss_generato_e_non_vuoto(theme: Theme) -> None:
    qss = theme.qss()
    assert "rootSurface" in qss
    assert theme.hex("bg.base") in qss
    assert "{" in qss and "}" in qss


def test_tema_inesistente_ricade_sui_valori_minimi() -> None:
    fallback = load_theme("tema-che-non-esiste")
    assert fallback.color("accent.core").isValid()
    assert fallback.qss()


# --------------------------------------------------------------------------- #
# Notifiche
# --------------------------------------------------------------------------- #


def test_toast_impilati_e_limitati(widgets_app, theme: Theme) -> None:
    """Una pila che copre mezza finestra e' un guasto, non una notifica."""
    from ui.notifications import ToastManager

    host = QtWidgets.QWidget()
    host.resize(800, 600)
    bus = EventBus()
    manager = ToastManager(bus, host, theme)

    for i in range(9):
        bus.publish(
            EventType.NOTIFICATION_REQUESTED, NotificationRequest(title=f"avviso {i}")
        )
        widgets_app.processEvents()

    assert len(manager._toasts) <= 4


def test_toast_lasciano_spazio_in_basso(widgets_app, theme: Theme) -> None:
    from ui.notifications import ToastManager

    host = QtWidgets.QWidget()
    host.resize(800, 600)
    bus = EventBus()
    manager = ToastManager(bus, host, theme, bottom_offset=60)

    manager.show(NotificationRequest(title="prova"))
    widgets_app.processEvents()

    toast = manager._toasts[0]
    assert toast.y() + toast.height() <= 600 - 60


# --------------------------------------------------------------------------- #
# Finestra
# --------------------------------------------------------------------------- #


def test_finestra_opaca_non_riserva_spazio_all_ombra(widgets_app, theme: Theme) -> None:
    """Senza trasparenza non c'e' ombra da ospitare: niente margini sprecati."""
    from ui.frameless import FramelessWindow

    window = FramelessWindow(theme, translucent=False)
    margins = window.layout().contentsMargins()

    assert margins.left() == 0
    assert margins.top() == 0


def test_finestra_translucida_riserva_spazio(widgets_app, theme: Theme) -> None:
    from ui.frameless import FramelessWindow

    window = FramelessWindow(theme, translucent=True)
    assert window.layout().contentsMargins().left() > 0


# --------------------------------------------------------------------------- #
# Finestra principale
# --------------------------------------------------------------------------- #


def test_la_barra_operativa_si_riapre_senza_console(qt_app, bus: EventBus, theme) -> None:
    """F9 e' una funzione dell'utente, non uno strumento di sviluppo.

    Registrata insieme alla Developer Console, in una build distribuita — dove
    la console non viene collegata — la scorciatoia non esisterebbe: chi avesse
    nascosto la barra operativa non avrebbe piu' alcun modo di riaprirla.
    """
    from core.capabilities import CapabilityManager
    from core.frameclock import FrameClock
    from core.missions.engine import MissionEngine
    from core.settings import AppSettings
    from core.state.manager import StateManager
    from ui.main_window import MainWindow

    finestra = MainWindow(
        bus,
        StateManager(bus),
        FrameClock(target_fps=60),
        theme,
        AppSettings(),
        missions=MissionEngine(bus),
        capabilities=CapabilityManager(bus),
    )
    try:
        assert finestra._sidebar is not None
        scorciatoie = {s.key().toString() for s in finestra.findChildren(QtGui.QShortcut)}

        assert "F9" in scorciatoie  # senza attach_developer_console

        voluta = finestra._sidebar.is_wanted
        finestra.toggle_sidebar()
        assert finestra._sidebar.is_wanted is not voluta
    finally:
        finestra.close()
