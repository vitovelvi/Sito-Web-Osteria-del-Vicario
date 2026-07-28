"""Test della Developer Console."""

from __future__ import annotations

import pytest
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.messages import MessageType

from core.eventbus import EventBus
from core.events import AudioChunk, EventType, NotificationRequest, ServiceStatus
from core.frameclock import FrameClock
from core.registry import ServiceRegistry
from core.service import BaseService, ServiceState
from core.state.manager import StateManager
from ui.devtools.formatting import format_payload, summarize
from ui.devtools.monitors import DiagnosticsPanel, ServiceMonitor
from ui.devtools.timeline import EventInspector, EventTimeline
from ui.theme.theme import load_theme


@pytest.fixture
def theme():
    return load_theme()


# --------------------------------------------------------------------------- #
# Formattazione
# --------------------------------------------------------------------------- #


def test_i_byte_non_vengono_stampati() -> None:
    """Un blocco audio da 2880 byte riempirebbe la finestra."""
    reso = format_payload(AudioChunk(stream_id="s1", sequence=0, pcm=b"\x00" * 2880))

    assert "2880 byte" in reso
    assert "\x00" * 100 not in reso
    assert len(reso) < 400


def test_stringhe_lunghe_troncate_con_la_lunghezza() -> None:
    """Un base64 da 4 KB non deve nascondere i campi che gli stanno intorno."""
    reso = format_payload({"data": "x" * 4000})

    assert "4000 caratteri" in reso
    assert len(reso) < 400


def test_summarize_mostra_i_campi_non_il_tipo() -> None:
    """Scorrendo la timeline si vuole vedere cosa è successo, non la classe."""
    riga = summarize(NotificationRequest(title="Jarvis online", kind="success"))

    assert "Jarvis online" in riga
    assert "NotificationRequest" not in riga


def test_summarize_rispetta_il_limite() -> None:
    riga = summarize(NotificationRequest(title="a" * 300), limit=50)
    assert len(riga) <= 50


def test_payload_non_rappresentabile_non_solleva() -> None:
    class Ostile:
        def __repr__(self) -> str:
            raise RuntimeError("nessuna rappresentazione")

    assert "non rappresentabile" in format_payload(Ostile())


# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #


def test_timeline_raccoglie_gli_eventi(qt_app, bus: EventBus, theme) -> None:
    timeline = EventTimeline(bus, theme)
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="prova"))
    qt_app.processEvents()

    assert timeline._list.count() >= 1


def test_timeline_mostra_lo_storico_precedente(qt_app, bus: EventBus, theme) -> None:
    """La console si apre di solito *dopo* che è successo qualcosa di interessante."""
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="prima"))
    qt_app.processEvents()

    timeline = EventTimeline(bus, theme)

    assert timeline._list.count() >= 1


def test_pausa_trattiene_senza_perdere(qt_app, bus: EventBus, theme) -> None:
    """Alla ripresa non si deve essere perso nulla."""
    timeline = EventTimeline(bus, theme)
    timeline._pause.setChecked(True)
    prima = timeline._list.count()

    for i in range(5):
        bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title=f"n{i}"))
    qt_app.processEvents()
    assert timeline._list.count() == prima

    timeline._pause.setChecked(False)
    qt_app.processEvents()
    assert timeline._list.count() == prima + 5


def test_filtro_riapplicato_allo_storico(qt_app, bus: EventBus, theme) -> None:
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="alfa"))
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="beta"))
    qt_app.processEvents()

    timeline = EventTimeline(bus, theme)
    timeline._search.setText("alfa")
    qt_app.processEvents()

    righe = [
        timeline._list.item(i).text()
        for i in range(timeline._list.count())
    ]
    assert all("alfa" in r for r in righe)


def test_inspector_mostra_il_dettaglio(qt_app, bus: EventBus, theme) -> None:
    inspector = EventInspector(theme)
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="dettaglio"))
    qt_app.processEvents()

    evento = bus.last(EventType.NOTIFICATION_REQUESTED)
    assert evento is not None
    inspector.show_event(evento)

    assert "ui.notification" in inspector._header.text()
    assert "dettaglio" in inspector._body.toPlainText()


# --------------------------------------------------------------------------- #
# Monitor dei servizi
# --------------------------------------------------------------------------- #


class _Servizio(BaseService):
    def __init__(self, name: str, *, fallisce: bool = False) -> None:
        super().__init__(name)
        self._fallisce = fallisce

    def _on_start(self) -> None:
        if self._fallisce:
            raise RuntimeError("guasto simulato")


def test_monitor_riflette_lo_stato_reale(qt_app, bus: EventBus, theme) -> None:
    registry = ServiceRegistry(bus)
    registry.register(_Servizio, lambda _: _Servizio("rete"))
    registry.start_all()

    monitor = ServiceMonitor(registry, bus, theme)

    assert monitor._table.rowCount() == 1
    assert monitor._table.item(0, 0).text() == "rete"
    assert monitor._table.item(0, 1).text() == "operativo"


def test_monitor_mostra_i_guasti(qt_app, bus: EventBus, theme) -> None:
    """È la traduzione visiva di 'se un modulo fallisce, mostrane lo stato'."""
    registry = ServiceRegistry(bus)
    registry.register(_Servizio, lambda _: _Servizio("webcam", fallisce=True))
    registry.start_all()

    monitor = ServiceMonitor(registry, bus, theme)
    qt_app.processEvents()

    assert monitor._table.item(0, 1).text() == "guasto"
    assert "guasto simulato" in monitor._table.item(0, 3).text()


def test_monitor_aggiornato_dagli_eventi(qt_app, bus: EventBus, theme) -> None:
    registry = ServiceRegistry(bus)
    ServiceMonitor(registry, bus, theme)

    bus.publish(
        EventType.SERVICE_STATUS_CHANGED,
        ServiceStatus(name="audio", status=ServiceState.DEGRADED.value),
    )
    qt_app.processEvents()  # non deve sollevare


# --------------------------------------------------------------------------- #
# Diagnostica
# --------------------------------------------------------------------------- #


def test_diagnostica_riporta_le_metriche(
    qt_app, bus: EventBus, state: StateManager, theme
) -> None:
    panel = DiagnosticsPanel(bus, state, FrameClock(target_fps=60), theme)
    panel.refresh()
    testo = panel._text.toPlainText()

    assert "Rendering" in testo
    assert "Event bus" in testo
    assert "Modalità visiva" in testo


def test_diagnostica_segnala_gli_eventi_senza_ascoltatori(
    qt_app, bus: EventBus, state: StateManager, theme
) -> None:
    """Un evento che nessuno ascolta è quasi sempre un sintomo."""
    from core.events import Empty

    bus.publish(EventType.APP_READY, Empty())
    qt_app.processEvents()

    panel = DiagnosticsPanel(bus, state, FrameClock(), theme)
    panel.refresh()

    assert "app.ready" in panel._text.toPlainText()


def test_diagnostica_include_la_rete(
    qt_app, bus: EventBus, state: StateManager, theme
) -> None:
    class _Rete:
        def diagnostics(self) -> dict[str, object]:
            return {"trasporto": "mock", "adapter": {"name": "jcp-native"}}

    panel = DiagnosticsPanel(bus, state, FrameClock(), theme, _Rete())
    panel.refresh()

    assert "Rete" in panel._text.toPlainText()
    assert "jcp-native" in panel._text.toPlainText()


def test_diagnostica_regge_una_rete_rotta(
    qt_app, bus: EventBus, state: StateManager, theme
) -> None:
    """La diagnostica non deve rompersi proprio quando serve a diagnosticare."""

    class _Rotta:
        def diagnostics(self) -> dict[str, object]:
            raise RuntimeError("guasto")

    panel = DiagnosticsPanel(bus, state, FrameClock(), theme, _Rotta())
    panel.refresh()

    assert "non disponibile" in panel._text.toPlainText()


# --------------------------------------------------------------------------- #
# Traffico
# --------------------------------------------------------------------------- #


def test_traffico_nasconde_il_rumore_per_default(qt_app, theme) -> None:
    """Stream e ping sono decine al secondo: coprirebbero tutto il resto."""
    from ui.devtools.traffic import TrafficView

    class _Rete:
        traffic = None

        def traffic_history(self):
            return (
                (0.0, ">", Envelope.make(MessageType.SESSION_HELLO)),
                (0.1, "<", Envelope.make(MessageType.STREAM_DATA, {"stream_id": "s"})),
                (0.2, "<", Envelope.make(MessageType.PING)),
            )

    view = TrafficView(_Rete(), theme)

    assert view._list.count() == 1

    view._noise.setChecked(True)
    assert view._list.count() == 3


# --------------------------------------------------------------------------- #
# Sessione
# --------------------------------------------------------------------------- #


def test_il_pulsante_legge_lo_stato_del_registratore(qt_app, theme) -> None:
    """Una registrazione può partire da altrove: il pannello non ricorda, legge.

    Un pulsante che dicesse "Avvia" mentre la registrazione è già in corso
    mentirebbe su cosa succede premendolo.
    """
    from jarvis_sdk.recording import SessionRecorder

    from ui.devtools.session import SessionPanel

    class _Rete:
        def __init__(self) -> None:
            self.recorder = SessionRecorder(client="prova")

        def transport_factory(self):
            return None

    rete = _Rete()
    panel = SessionPanel(rete, theme)
    panel._refresh_status()
    assert panel._record_button.text() == "Avvia registrazione"

    rete.recorder.start()  # avviata fuori dal pannello
    panel._refresh_status()

    assert panel._record_button.text() == "Ferma registrazione"
