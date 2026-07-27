"""Test della rete: backoff, backend simulato, dispatcher, sessione completa.

Il backend simulato non è un accessorio dei test: è ciò che rende verificabili i
casi che con un backend reale non si sanno provocare a comando — handshake
omesso, caduta a metà risposta, payload malformato, versione di protocollo
incompatibile.
"""

from __future__ import annotations

import time

import pytest

from core.capabilities import CapabilityManager
from core.errors import TransportError
from core.eventbus import EventBus
from core.events import EventType
from core.identity import IdentityService
from core.protocol.envelope import PROTOCOL_VERSION, Envelope
from core.protocol.messages import MessageType
from core.settings import BackendSettings
from core.state.machines import AgentState, AppState, LinkState
from core.state.manager import StateManager
from network.dispatcher import MessageDispatcher
from network.mock.backend import MockScenario, MockTransport
from network.reconnect import BackoffPolicy
from network.service import NetworkService

# --------------------------------------------------------------------------- #
# Backoff
# --------------------------------------------------------------------------- #


def test_backoff_cresce_e_si_ferma_al_tetto() -> None:
    policy = BackoffPolicy(initial=1.0, maximum=8.0, factor=2.0, jitter=0.0)
    assert [policy.next_delay() for _ in range(6)] == [1.0, 2.0, 4.0, 8.0, 8.0, 8.0]


def test_backoff_con_jitter_resta_nell_intorno() -> None:
    """Il jitter evita che più client riprovino tutti nello stesso istante."""
    # Soglia dell'interruttore alta di proposito: qui si verifica il jitter,
    # non la diradazione dei tentativi, che ha un test dedicato.
    policy = BackoffPolicy(
        initial=4.0, maximum=4.0, factor=1.0, jitter=0.3, circuit_threshold=10_000
    )
    delays = [policy.next_delay() for _ in range(40)]

    assert all(2.8 <= d <= 5.2 for d in delays)
    assert len(set(delays)) > 1  # non è una costante


def test_backoff_mai_negativo() -> None:
    policy = BackoffPolicy(initial=0.2, maximum=0.2, factor=1.0, jitter=1.0)
    assert all(policy.next_delay() > 0 for _ in range(50))


def test_interruttore_dirada_i_tentativi() -> None:
    """Dopo molti fallimenti la causa non è transitoria: si riprova con calma."""
    policy = BackoffPolicy(
        initial=1.0, maximum=5.0, factor=2.0, jitter=0.0, circuit_threshold=3,
        circuit_delay=60.0,
    )
    delays = [policy.next_delay() for _ in range(4)]

    assert delays[:2] == [1.0, 2.0]
    assert policy.circuit_open
    assert delays[-1] == 60.0


def test_reset_dopo_connessione_riuscita() -> None:
    policy = BackoffPolicy(jitter=0.0)
    policy.next_delay()
    policy.next_delay()
    policy.reset()

    assert policy.attempts == 0
    assert policy.next_delay() == pytest.approx(policy.initial)


# --------------------------------------------------------------------------- #
# Backend simulato
# --------------------------------------------------------------------------- #


async def _collect(transport: MockTransport, count: int, timeout: float = 5.0):
    """Raccoglie ``count`` messaggi, fallendo se non arrivano in tempo."""
    import asyncio

    received = []

    async def pump() -> None:
        async for envelope in transport.receive():
            received.append(envelope)
            if len(received) >= count:
                return

    await asyncio.wait_for(pump(), timeout=timeout)
    return received


async def _collect_until(transport: MockTransport, wanted: str, timeout: float = 5.0):
    """Raccoglie finché non compare un messaggio del tipo atteso.

    Contare i messaggi sarebbe fragile: il simulatore inserisce a caso un ciclo
    di task, e il numero di messaggi prima della risposta non è fisso.
    """
    import asyncio

    received = []

    async def pump() -> None:
        async for envelope in transport.receive():
            received.append(envelope)
            if envelope.type == wanted:
                return

    await asyncio.wait_for(pump(), timeout=timeout)
    return received


async def test_mock_risponde_all_handshake() -> None:
    transport = MockTransport(MockScenario(handshake_delay=0.01, latency=0.0))
    await transport.connect()
    await transport.send(Envelope(type=MessageType.CLIENT_HELLO))

    received = await _collect(transport, 1)

    assert received[0].type == MessageType.SERVER_HELLO
    assert received[0].payload["protocol_version"] == PROTOCOL_VERSION
    await transport.close()


async def test_mock_correla_la_risposta() -> None:
    transport = MockTransport(MockScenario(handshake_delay=0.0, latency=0.0))
    await transport.connect()
    request = Envelope(type=MessageType.CLIENT_HELLO)
    await transport.send(request)

    received = await _collect(transport, 1)

    assert received[0].corr == request.id
    await transport.close()


async def test_mock_risponde_al_ping() -> None:
    transport = MockTransport(MockScenario(latency=0.0))
    await transport.connect()
    ping = Envelope(type=MessageType.PING)
    await transport.send(ping)

    received = await _collect(transport, 1)

    assert received[0].type == MessageType.PONG
    assert received[0].corr == ping.id
    await transport.close()


async def test_mock_streamma_la_risposta() -> None:
    transport = MockTransport(MockScenario(latency=0.0, emit_audio=False, seed=1))
    await transport.connect()
    await transport.send(
        Envelope(type=MessageType.CHAT_SEND, payload={"text": "ciao", "message_id": "m1"})
    )

    received = await _collect_until(transport, MessageType.CHAT_DELTA)
    tipi = [e.type for e in received]

    assert MessageType.AGENT_STATE in tipi
    assert tipi[-1] == MessageType.CHAT_DELTA
    await transport.close()


async def test_mock_connessione_rifiutata() -> None:
    transport = MockTransport(MockScenario(fail_connect=True))
    with pytest.raises(TransportError):
        await transport.connect()


async def test_mock_invio_a_canale_chiuso() -> None:
    transport = MockTransport()
    with pytest.raises(TransportError):
        await transport.send(Envelope(type=MessageType.PING))


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #


@pytest.fixture
def dispatcher(bus: EventBus, state: StateManager, temp_paths):
    identity = IdentityService(bus, temp_paths)
    return MessageDispatcher(bus, state, identity, CapabilityManager(bus)), identity


def _hello(**overrides) -> Envelope:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "backend_version": "1.0",
        "model": "openclaw-test",
        "capabilities": ["chat.stream", "tts.stream"],
    }
    payload.update(overrides.pop("payload", {}))
    return Envelope(type=MessageType.SERVER_HELLO, payload=payload, **overrides)


def test_handshake_valido(dispatcher) -> None:
    disp, identity = dispatcher
    assert disp.apply_server_hello(_hello()) is not None
    assert identity.is_confirmed
    assert identity.backend.model == "openclaw-test"


def test_handshake_con_versione_non_supportata_rifiutato(dispatcher, state) -> None:
    """Una GUI vecchia davanti a un backend nuovo deve rifiutare, non indovinare."""
    disp, identity = dispatcher
    envelope = _hello(v=PROTOCOL_VERSION + 10)

    assert disp.apply_server_hello(envelope) is None
    assert not identity.is_confirmed
    assert any(c.source == "protocol" for c in state.active_errors())


def test_handshake_malformato_rifiutato(dispatcher) -> None:
    disp, _ = dispatcher
    envelope = Envelope(type=MessageType.SERVER_HELLO, payload={"niente": "di utile"})
    assert disp.apply_server_hello(envelope) is None


def test_stato_dal_backend_e_autorevole(dispatcher, state) -> None:
    disp, _ = dispatcher
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    disp.dispatch(Envelope(type=MessageType.AGENT_STATE, payload={"state": "thinking"}))

    assert state.agent_state is AgentState.THINKING


def test_stato_sconosciuto_scartato(dispatcher, state) -> None:
    """Un backend più recente può inventare stati: si ignora, non si cade."""
    disp, _ = dispatcher
    disp.dispatch(Envelope(type=MessageType.AGENT_STATE, payload={"state": "sognando"}))
    assert state.agent_state is AgentState.IDLE


def test_tipo_sconosciuto_ignorato(dispatcher) -> None:
    disp, _ = dispatcher
    disp.dispatch(Envelope(type="funzione.del.futuro", payload={"x": 1}))  # non solleva


def test_payload_malformato_non_propaga(dispatcher, collected) -> None:
    disp, _ = dispatcher
    disp.dispatch(Envelope(type=MessageType.CHAT_DELTA, payload={"__malformato__": True}))
    assert not [e for e in collected if e.type is EventType.AI_RESPONSE]


def test_frammenti_di_risposta_pubblicati(dispatcher, collected) -> None:
    disp, _ = dispatcher
    disp.dispatch(
        Envelope(type=MessageType.CHAT_DELTA, payload={"text": "ciao ", "message_id": "m1"})
    )
    disp.dispatch(
        Envelope(type=MessageType.CHAT_DONE, payload={"text": "", "message_id": "m1"})
    )

    risposte = [e for e in collected if e.type is EventType.AI_RESPONSE]
    assert len(risposte) == 2
    assert risposte[-1].payload.final


def test_audio_decodificato_e_pubblicato(dispatcher, collected) -> None:
    """La rete decodifica il trasporto (base64) e nient'altro."""
    import base64

    disp, _ = dispatcher
    disp.dispatch(
        Envelope(
            type=MessageType.AUDIO_START,
            payload={"stream_id": "s1", "sample_rate": 16000, "channels": 1},
        )
    )
    disp.dispatch(
        Envelope(
            type=MessageType.AUDIO_CHUNK,
            payload={
                "stream_id": "s1",
                "sequence": 0,
                "data": base64.b64encode(b"\x00\x01\x02\x03").decode(),
            },
        )
    )

    chunks = [e for e in collected if e.type is EventType.AUDIO_STREAM_CHUNK]
    assert chunks[0].payload.pcm == b"\x00\x01\x02\x03"
    assert chunks[0].payload.sample_rate == 16000  # formato preso da audio.start


def test_audio_non_decodificabile_scartato(dispatcher, collected) -> None:
    disp, _ = dispatcher
    disp.dispatch(
        Envelope(
            type=MessageType.AUDIO_CHUNK,
            payload={"stream_id": "s1", "sequence": 0, "data": "non-base64!!!"},
        )
    )
    assert not [e for e in collected if e.type is EventType.AUDIO_STREAM_CHUNK]


def test_errore_del_backend_diventa_condizione(dispatcher, state) -> None:
    disp, _ = dispatcher
    disp.dispatch(
        Envelope(
            type=MessageType.ERROR,
            payload={"code": "rate_limit", "message": "Troppe richieste"},
        )
    )
    sorgenti = [c.source for c in state.active_errors()]
    assert "backend.rate_limit" in sorgenti


def test_errore_non_critico_ha_una_scadenza(dispatcher, state) -> None:
    """Il protocollo non prevede 'errore risolto': senza TTL resterebbe per sempre."""
    disp, _ = dispatcher
    disp.dispatch(
        Envelope(type=MessageType.ERROR, payload={"code": "x", "message": "temporaneo"})
    )
    condizione = state.active_errors()[0]
    assert condizione.expires_at is not None


# --------------------------------------------------------------------------- #
# Sessione completa
# --------------------------------------------------------------------------- #


def _settings(**overrides) -> BackendSettings:
    base = {
        "transport": "mock",
        "connect_timeout_s": 1.0,
        "heartbeat_interval_s": 0.2,
        "heartbeat_timeout_s": 0.3,
        "reconnect_initial_s": 0.05,
        "reconnect_max_s": 0.2,
        "reconnect_jitter": 0.0,
    }
    base.update(overrides)
    return BackendSettings(**base)


def _wait_until(qt_app, predicate, timeout: float = 6.0) -> bool:
    """Attende una condizione facendo girare il ciclo di eventi Qt."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    qt_app.processEvents()
    return predicate()


@pytest.fixture
def network(bus, state, temp_paths, request):
    """Servizio di rete contro il backend simulato, fermato a fine test."""
    identity = IdentityService(bus, temp_paths)
    capabilities = CapabilityManager(bus)
    settings = getattr(request, "param", None) or _settings()
    scenario = getattr(request, "scenario", None)

    service = NetworkService(bus, state, identity, capabilities, settings, scenario=scenario)
    yield service, identity, capabilities
    service.stop()


def test_sessione_completa_contro_il_mock(network, qt_app, state) -> None:
    """Il percorso nominale: connessione, handshake, identità, capability."""
    service, identity, capabilities = network
    state.set_app_state(AppState.RUNNING)

    service.start()

    assert _wait_until(qt_app, lambda: state.link_state is LinkState.ONLINE)
    assert identity.is_confirmed
    assert identity.backend.model == "openclaw-mock"
    assert "chat.stream" in capabilities.granted


def test_disconnessione_azzera_identita_e_capability(
    bus, state, temp_paths, qt_app
) -> None:
    """Senza canale la GUI non deve continuare ad affermare ciò che non verifica."""
    identity = IdentityService(bus, temp_paths)
    capabilities = CapabilityManager(bus)
    service = NetworkService(
        bus,
        state,
        identity,
        capabilities,
        _settings(),
        scenario=MockScenario(handshake_delay=0.0, latency=0.0, drop_after=0.4),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: identity.is_confirmed)
        assert _wait_until(qt_app, lambda: not identity.is_confirmed, timeout=6.0)
        assert capabilities.granted == frozenset()
    finally:
        service.stop()


def test_backend_che_non_si_presenta_va_in_timeout(bus, state, temp_paths, qt_app) -> None:
    """Connessione accettata ma nessun handshake: caso reale, timeout dedicato."""
    identity = IdentityService(bus, temp_paths)
    service = NetworkService(
        bus,
        state,
        identity,
        CapabilityManager(bus),
        _settings(connect_timeout_s=0.3),
        scenario=MockScenario(refuse_handshake=True),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: state.link_state is LinkState.OFFLINE, timeout=6.0)
        assert not identity.is_confirmed
    finally:
        service.stop()


def test_connessione_fallita_non_blocca_e_riprova(bus, state, temp_paths, qt_app) -> None:
    """Requisito centrale: senza backend la GUI resta viva e continua a provare."""
    service = NetworkService(
        bus,
        state,
        IdentityService(bus, temp_paths),
        CapabilityManager(bus),
        _settings(),
        scenario=MockScenario(fail_connect=True),
    )
    state.set_app_state(AppState.RUNNING)

    tentativi: list[object] = []
    bus.subscribe(
        EventType.LINK_STATE_CHANGED,
        lambda e: tentativi.append(e) if e.payload.state == "connecting" else None,
    )

    try:
        service.start()
        assert _wait_until(qt_app, lambda: len(tentativi) >= 3, timeout=6.0)
    finally:
        service.stop()


def test_invio_a_canale_chiuso_non_solleva(bus, state, temp_paths) -> None:
    """Un pulsante premuto senza connessione non deve produrre un'eccezione."""
    service = NetworkService(
        bus, state, IdentityService(bus, temp_paths), CapabilityManager(bus), _settings()
    )
    assert service.send_chat("ciao", "m1") is False


def test_stop_e_idempotente(bus, state, temp_paths) -> None:
    service = NetworkService(
        bus, state, IdentityService(bus, temp_paths), CapabilityManager(bus), _settings()
    )
    service.stop()
    service.stop()
