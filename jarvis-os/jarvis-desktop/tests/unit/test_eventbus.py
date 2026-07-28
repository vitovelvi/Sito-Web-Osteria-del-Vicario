"""Test dell'event bus."""

from __future__ import annotations

import gc
import threading

import pytest

from core.eventbus import EventBus
from core.events import Empty, EventType, NotificationRequest
from core.qtcompat import QtCore


def test_publish_and_receive(bus: EventBus) -> None:
    received: list[str] = []
    bus.subscribe(EventType.NOTIFICATION_REQUESTED, lambda e: received.append(e.payload.title))

    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="ciao"))

    assert received == ["ciao"]


def test_payload_non_conforme_rifiutato_in_strict(bus: EventBus) -> None:
    """Il contratto payload-evento e' verificato, non solo documentato."""
    with pytest.raises(TypeError, match="Payload non conforme"):
        bus.publish(EventType.NOTIFICATION_REQUESTED, Empty())


def test_payload_non_conforme_scartato_in_produzione() -> None:
    """Fuori dai test un payload sbagliato si scarta: la GUI non deve cadere."""
    permissive = EventBus(strict=False)
    received: list = []
    permissive.subscribe(EventType.NOTIFICATION_REQUESTED, received.append)

    permissive.publish(EventType.NOTIFICATION_REQUESTED, Empty())

    assert received == []


def test_unsubscribe(bus: EventBus) -> None:
    received: list = []
    token = bus.subscribe(EventType.APP_READY, received.append)

    bus.publish(EventType.APP_READY, Empty())
    token.unsubscribe()
    bus.publish(EventType.APP_READY, Empty())

    assert len(received) == 1
    assert not token.active
    token.unsubscribe()  # idempotente


def test_subscription_come_context_manager(bus: EventBus) -> None:
    received: list = []
    with bus.subscribe(EventType.APP_READY, received.append):
        bus.publish(EventType.APP_READY, Empty())
    bus.publish(EventType.APP_READY, Empty())

    assert len(received) == 1


def test_replay_last(bus: EventBus) -> None:
    """Un modulo che si avvia tardi deve poter vedere lo stato corrente."""
    bus.publish(EventType.NOTIFICATION_REQUESTED, NotificationRequest(title="prima"))

    received: list = []
    bus.subscribe(EventType.NOTIFICATION_REQUESTED, received.append, replay_last=True)

    assert [e.payload.title for e in received] == ["prima"]


def test_once(bus: EventBus) -> None:
    received: list = []
    bus.subscribe(EventType.APP_READY, received.append, once=True)

    bus.publish(EventType.APP_READY, Empty())
    bus.publish(EventType.APP_READY, Empty())

    assert len(received) == 1


def test_handler_che_solleva_non_blocca_gli_altri(bus: EventBus) -> None:
    """L'isolamento dei guasti vale anche nella consegna degli eventi."""
    ordine: list[str] = []

    def rotto(_: object) -> None:
        ordine.append("rotto")
        raise RuntimeError("guasto simulato")

    bus.subscribe(EventType.APP_READY, rotto)
    bus.subscribe(EventType.APP_READY, lambda _: ordine.append("sano"))

    bus.publish(EventType.APP_READY, Empty())

    assert ordine == ["rotto", "sano"]
    assert bus.metrics()["handler_errors"] == 1


def test_metodo_legato_referenziato_debolmente(bus: EventBus) -> None:
    """La distruzione di un widget deve annullare la sua sottoscrizione.

    Senza questo, ogni pannello chiuso resterebbe vivo per sempre, trattenuto
    dal bus: e' la perdita di memoria classica delle GUI a eventi.
    """
    received: list = []

    class Consumatore:
        def on_event(self, event: object) -> None:
            received.append(event)

    consumatore = Consumatore()
    bus.subscribe(EventType.APP_READY, consumatore.on_event)
    bus.publish(EventType.APP_READY, Empty())
    assert len(received) == 1

    del consumatore
    gc.collect()

    bus.publish(EventType.APP_READY, Empty())
    assert len(received) == 1


def test_evento_plugin_richiede_prefisso(bus: EventBus) -> None:
    received: list = []
    bus.subscribe("plugin.meteo.aggiornato", received.append)
    bus.publish("plugin.meteo.aggiornato", {"gradi": 21})
    assert received[0].payload == {"gradi": 21}

    with pytest.raises(TypeError, match="prefisso"):
        bus.publish("evento.arbitrario", None)


def test_dead_letter_contato(bus: EventBus) -> None:
    """Un evento che nessuno ascolta e' quasi sempre un sintomo."""
    bus.publish(EventType.APP_READY, Empty())
    assert bus.metrics()["dead_letters"]["app.ready"] == 1


def test_publish_da_altro_thread_consegna_nel_thread_del_bus(
    bus: EventBus, qt_app: QtCore.QCoreApplication
) -> None:
    """Il punto centrale del bus: la consegna avviene sempre nel thread GUI.

    Se questo test fallisce, la GUI viene toccata da un thread di lavoro e i
    crash che ne derivano sono sporadici e quasi impossibili da diagnosticare.
    """
    thread_di_consegna: list[int] = []
    thread_principale = threading.get_ident()

    bus.subscribe(EventType.APP_READY, lambda _: thread_di_consegna.append(threading.get_ident()))

    worker = threading.Thread(target=lambda: bus.publish(EventType.APP_READY, Empty()))
    worker.start()
    worker.join()

    # La consegna e' accodata: si lascia girare il ciclo di eventi.
    for _ in range(20):
        qt_app.processEvents()
        if thread_di_consegna:
            break

    assert thread_di_consegna == [thread_principale]


def test_history_limitata() -> None:
    piccolo = EventBus(history=3)
    for _ in range(5):
        piccolo.publish(EventType.APP_READY, Empty())
    assert len(piccolo.history()) == 3
