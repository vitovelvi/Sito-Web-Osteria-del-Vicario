"""Test della rete: backoff, backend JCP simulato, dispatcher, sessione.

Il backend simulato è ciò che rende verificabili i casi che con un backend reale
non si sanno provocare a comando: handshake omesso, versione incompatibile,
token rifiutato, caduta a metà risposta, payload malformato.
"""

from __future__ import annotations

import asyncio
import base64
import time

import pytest

from core.capabilities import CapabilityManager
from core.errors import TransportError
from core.eventbus import EventBus
from core.events import EventType
from core.identity import IdentityService
from core.jcp.envelope import Envelope
from core.jcp.messages import MessageType
from core.jcp.version import PROTOCOL_VERSION
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
        initial=1.0, maximum=5.0, factor=2.0, jitter=0.0,
        circuit_threshold=3, circuit_delay=60.0,
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


async def _collect_until(transport: MockTransport, wanted: str, timeout: float = 5.0):
    """Raccoglie finché non compare un messaggio del tipo atteso.

    Contare i messaggi sarebbe fragile: il simulatore inserisce a caso un ciclo
    di task, quindi il numero di messaggi prima della risposta non è fisso.
    """
    received: list[Envelope] = []

    async def pump() -> None:
        async for message in transport.receive():
            envelope = Envelope.from_wire(message)
            received.append(envelope)
            if envelope.type == wanted:
                return

    await asyncio.wait_for(pump(), timeout=timeout)
    return received


async def test_mock_risponde_all_handshake() -> None:
    transport = MockTransport(MockScenario(handshake_delay=0.01, latency=0.0))
    await transport.connect()
    hello = Envelope.make(MessageType.SESSION_HELLO, {})
    await transport.send(hello.to_wire())

    received = await _collect_until(transport, MessageType.SESSION_WELCOME)

    welcome = received[-1]
    assert welcome.corr == hello.id
    assert welcome.payload["protocol"]["major"] == PROTOCOL_VERSION.major
    await transport.close()


async def test_mock_risponde_al_ping() -> None:
    transport = MockTransport(MockScenario(latency=0.0))
    await transport.connect()
    ping = Envelope.make(MessageType.PING)
    await transport.send(ping.to_wire())

    received = await _collect_until(transport, MessageType.PONG)

    assert received[-1].corr == ping.id
    await transport.close()


async def test_mock_streamma_la_risposta() -> None:
    transport = MockTransport(MockScenario(latency=0.0, emit_audio=False, seed=1))
    await transport.connect()
    await transport.send(
        Envelope.make(MessageType.CHAT_SEND, {"text": "ciao", "message_id": "m1"}).to_wire()
    )

    received = await _collect_until(transport, MessageType.CHAT_DELTA)

    assert MessageType.AGENT_STATE in [e.type for e in received]
    assert received[-1].type == MessageType.CHAT_DELTA
    await transport.close()


async def test_mock_usa_stream_generici_per_l_audio() -> None:
    """L'audio passa da ``stream.*``, non da messaggi propri."""
    transport = MockTransport(MockScenario(latency=0.0, seed=1))
    await transport.connect()
    await transport.send(
        Envelope.make(MessageType.CHAT_SEND, {"text": "x", "message_id": "m1"}).to_wire()
    )

    received = await _collect_until(transport, MessageType.STREAM_OPEN, timeout=8.0)
    apertura = received[-1].payload

    assert apertura["kind"] == "audio"
    assert apertura["related_id"] == "m1"
    await transport.close()


async def test_mock_connessione_rifiutata() -> None:
    with pytest.raises(TransportError):
        await MockTransport(MockScenario(fail_connect=True)).connect()


async def test_mock_invio_a_canale_chiuso() -> None:
    with pytest.raises(TransportError):
        await MockTransport().send({"t": "link.ping"})


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #


@pytest.fixture
def dispatcher(bus: EventBus, state: StateManager, temp_paths):
    identity = IdentityService(bus, temp_paths)
    capabilities = CapabilityManager(bus)
    return MessageDispatcher(bus, state, identity, capabilities), identity, capabilities


def _welcome(major: int = PROTOCOL_VERSION.major, minor: int = 0, **server) -> Envelope:
    payload = {
        "protocol": {"major": major, "minor": minor},
        "server": {"version": "1.0", "model": "backend-test", **server},
        "capabilities": ["chat.stream", "tts.stream"],
    }
    return Envelope.make(MessageType.SESSION_WELCOME, payload)


def test_handshake_valido(dispatcher) -> None:
    disp, identity, capabilities = dispatcher
    result = disp.apply_welcome(_welcome())

    assert result.accepted
    assert identity.is_confirmed
    assert identity.backend.model == "backend-test"
    assert "chat.stream" in capabilities.granted


def test_major_incompatibile_ferma_i_tentativi(dispatcher, state) -> None:
    """Insistere non serve: la versione del backend non cambia da sola."""
    disp, identity, _ = dispatcher
    result = disp.apply_welcome(_welcome(major=PROTOCOL_VERSION.major + 3))

    assert not result.accepted
    assert not result.retryable
    assert not identity.is_confirmed
    assert any(c.source == "protocol" for c in state.active_errors())


def test_minor_diverso_e_accettato(dispatcher) -> None:
    """È il caso che permette di aggiornare GUI e backend in momenti diversi."""
    disp, identity, _ = dispatcher
    result = disp.apply_welcome(_welcome(minor=PROTOCOL_VERSION.minor + 7))

    assert result.accepted
    assert identity.is_confirmed


def test_welcome_malformato_rifiutato(dispatcher) -> None:
    disp, _, _ = dispatcher
    envelope = Envelope.make(MessageType.SESSION_WELCOME, {"niente": "di utile"})
    assert not disp.apply_welcome(envelope).accepted


def test_denied_non_ritentabile(dispatcher, state) -> None:
    disp, _, _ = dispatcher
    result = disp.apply_denied(
        Envelope.make(
            MessageType.SESSION_DENIED,
            {"code": "auth.denied", "message": "Token non valido", "retryable": False},
        )
    )

    assert not result.accepted
    assert not result.retryable
    assert any(c.source == "protocol" for c in state.active_errors())


def test_stato_dal_backend_e_autorevole(dispatcher, state) -> None:
    disp, _, _ = dispatcher
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    disp.dispatch(Envelope.make(MessageType.AGENT_STATE, {"state": "thinking"}))

    assert state.agent_state is AgentState.THINKING


def test_stato_sconosciuto_scartato(dispatcher, state) -> None:
    """Un backend più recente può inventare stati: si ignora, non si cade."""
    disp, _, _ = dispatcher
    disp.dispatch(Envelope.make(MessageType.AGENT_STATE, {"state": "sognando"}))
    assert state.agent_state is AgentState.IDLE


def test_tipo_sconosciuto_ignorato(dispatcher) -> None:
    disp, _, _ = dispatcher
    disp.dispatch(Envelope.make("funzione.del.futuro", {"x": 1}))  # non solleva


def test_payload_malformato_non_propaga(dispatcher, collected) -> None:
    disp, _, _ = dispatcher
    disp.dispatch(Envelope.make(MessageType.CHAT_DELTA, {"__malformato__": True}))
    assert not [e for e in collected if e.type is EventType.AI_RESPONSE]


def test_frammenti_e_chiusura_della_risposta(dispatcher, collected) -> None:
    disp, _, _ = dispatcher
    disp.dispatch(MessageType.CHAT_DELTA and Envelope.make(
        MessageType.CHAT_DELTA, {"text": "ciao ", "message_id": "m1"}
    ))
    disp.dispatch(Envelope.make(MessageType.CHAT_DONE, {"message_id": "m1"}))

    risposte = [e for e in collected if e.type is EventType.AI_RESPONSE]
    assert len(risposte) == 2
    assert risposte[-1].payload.final


# --------------------------------------------------------------------------- #
# Stream
# --------------------------------------------------------------------------- #


def _open_audio(disp, stream_id: str = "s1", rate: int = 16000) -> None:
    disp.dispatch(
        Envelope.make(
            MessageType.STREAM_OPEN,
            {"stream_id": stream_id, "kind": "audio", "sample_rate": rate, "channels": 1},
        )
    )


def test_stream_audio_decodificato(dispatcher, collected) -> None:
    """La rete decodifica il trasporto (base64) e nient'altro."""
    disp, _, _ = dispatcher
    _open_audio(disp)
    disp.dispatch(
        Envelope.make(
            MessageType.STREAM_DATA,
            {
                "stream_id": "s1",
                "seq": 0,
                "data": base64.b64encode(b"\x00\x01\x02\x03").decode(),
            },
        )
    )

    chunks = [e for e in collected if e.type is EventType.AUDIO_STREAM_CHUNK]
    assert chunks[0].payload.pcm == b"\x00\x01\x02\x03"
    assert chunks[0].payload.sample_rate == 16000  # formato preso da stream.open


def test_blocco_senza_apertura_scartato(dispatcher, collected) -> None:
    """Senza il formato dichiarato non si saprebbe come interpretare i byte."""
    disp, _, _ = dispatcher
    disp.dispatch(
        Envelope.make(MessageType.STREAM_DATA, {"stream_id": "ignoto", "seq": 0, "data": ""})
    )
    assert not [e for e in collected if e.type is EventType.AUDIO_STREAM_CHUNK]


def test_audio_non_decodificabile_scartato(dispatcher, collected) -> None:
    disp, _, _ = dispatcher
    _open_audio(disp)
    disp.dispatch(
        Envelope.make(
            MessageType.STREAM_DATA,
            {"stream_id": "s1", "seq": 0, "data": "non-base64!!!"},
        )
    )
    assert not [e for e in collected if e.type is EventType.AUDIO_STREAM_CHUNK]


def test_stream_non_audio_non_produce_eventi_audio(dispatcher, collected) -> None:
    """Video e file useranno lo stesso meccanismo, con consumatori propri."""
    disp, _, _ = dispatcher
    disp.dispatch(
        Envelope.make(
            MessageType.STREAM_OPEN, {"stream_id": "v1", "kind": "video", "mime": "image/jpeg"}
        )
    )
    assert not [e for e in collected if e.type is EventType.AUDIO_PLAYING]


def test_chiusura_stream_segnala_fine(dispatcher, collected) -> None:
    disp, _, _ = dispatcher
    _open_audio(disp)
    disp.dispatch(Envelope.make(MessageType.STREAM_CLOSE, {"stream_id": "s1"}))
    assert [e for e in collected if e.type is EventType.AUDIO_FINISHED]


# --------------------------------------------------------------------------- #
# Estensioni
# --------------------------------------------------------------------------- #


def test_estensione_negoziata_arriva_ai_plugin(dispatcher, collected) -> None:
    disp, _, capabilities = dispatcher
    capabilities.apply(["ext.acme.meteo"])

    disp.dispatch(Envelope.make("ext.acme.meteo", {"gradi": 21}))

    inoltrati = [e for e in collected if str(e.key).startswith("plugin.")]
    assert inoltrati and inoltrati[-1].payload == {"gradi": 21}


def test_estensione_non_negoziata_ignorata(dispatcher, collected) -> None:
    """Usare un'estensione senza averla dichiarata è un errore del mittente."""
    disp, _, _ = dispatcher
    disp.dispatch(Envelope.make("ext.acme.meteo", {"gradi": 21}))
    assert not [e for e in collected if str(e.key).startswith("plugin.")]


# --------------------------------------------------------------------------- #
# Errori
# --------------------------------------------------------------------------- #


def test_errore_del_backend_diventa_condizione(dispatcher, state) -> None:
    disp, _, _ = dispatcher
    disp.dispatch(
        Envelope.make(
            MessageType.ERROR, {"code": "rate_limit", "message": "Troppe richieste"}
        )
    )
    assert "backend.rate_limit" in [c.source for c in state.active_errors()]


def test_errore_non_critico_ha_una_scadenza(dispatcher, state) -> None:
    """Il protocollo non prevede 'errore risolto': senza TTL resterebbe per sempre."""
    disp, _, _ = dispatcher
    disp.dispatch(
        Envelope.make(MessageType.ERROR, {"code": "x", "message": "temporaneo"})
    )
    assert state.active_errors()[0].expires_at is not None


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


def _service(bus, state, temp_paths, *, scenario=None, settings=None):
    return NetworkService(
        bus,
        state,
        IdentityService(bus, temp_paths),
        CapabilityManager(bus),
        settings or _settings(),
        scenario=scenario,
    )


def test_sessione_completa(bus, state, temp_paths, qt_app) -> None:
    """Percorso nominale: connessione, handshake, identità, capability."""
    identity = IdentityService(bus, temp_paths)
    capabilities = CapabilityManager(bus)
    service = NetworkService(bus, state, identity, capabilities, _settings())
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: state.link_state is LinkState.ONLINE)
        assert identity.is_confirmed
        assert identity.backend.model == "jcp-mock"
        assert "chat.stream" in capabilities.granted
    finally:
        service.stop()


def test_disconnessione_azzera_identita_e_capability(bus, state, temp_paths, qt_app) -> None:
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
        assert _wait_until(qt_app, lambda: not identity.is_confirmed)
        assert capabilities.granted == frozenset()
    finally:
        service.stop()


def test_backend_che_non_si_presenta_va_in_timeout(bus, state, temp_paths, qt_app) -> None:
    """Connessione accettata ma nessun handshake: caso reale, timeout dedicato."""
    service = _service(
        bus, state, temp_paths,
        scenario=MockScenario(refuse_handshake=True),
        settings=_settings(connect_timeout_s=0.3),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: state.link_state is LinkState.OFFLINE)
    finally:
        service.stop()


def test_connessione_fallita_non_blocca_e_riprova(bus, state, temp_paths, qt_app) -> None:
    """Requisito centrale: senza backend la GUI resta viva e continua a provare."""
    service = _service(bus, state, temp_paths, scenario=MockScenario(fail_connect=True))
    state.set_app_state(AppState.RUNNING)

    tentativi: list[object] = []
    bus.subscribe(
        EventType.LINK_STATE_CHANGED,
        lambda e: tentativi.append(e) if e.payload.state == "connecting" else None,
    )

    try:
        service.start()
        assert _wait_until(qt_app, lambda: len(tentativi) >= 3)
    finally:
        service.stop()


def test_versione_incompatibile_sospende_i_tentativi(bus, state, temp_paths, qt_app) -> None:
    """Un rifiuto permanente ferma il ciclo invece di riempire i log."""
    service = _service(
        bus, state, temp_paths,
        scenario=MockScenario(
            handshake_delay=0.0, latency=0.0, protocol_major=PROTOCOL_VERSION.major + 4
        ),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: service.health().state.value == "failed")
        assert service.diagnostics()["sospeso"] is True
    finally:
        service.stop()


def test_token_rifiutato_sospende_i_tentativi(bus, state, temp_paths, qt_app) -> None:
    """Insistere con un token sbagliato non lo rende valido."""
    service = _service(
        bus, state, temp_paths,
        scenario=MockScenario(handshake_delay=0.0, latency=0.0, require_auth=True),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: service.diagnostics()["sospeso"] is True)
    finally:
        service.stop()


def test_messaggi_sconosciuti_non_interrompono_la_sessione(
    bus, state, temp_paths, qt_app
) -> None:
    """Un tipo del futuro e un'estensione non negoziata: entrambi ignorati."""
    service = _service(
        bus, state, temp_paths,
        scenario=MockScenario(handshake_delay=0.0, latency=0.0, emit_unknown=True),
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: state.link_state is LinkState.ONLINE)
        time.sleep(0.3)
        qt_app.processEvents()
        assert state.link_state is LinkState.ONLINE  # ancora connessi
    finally:
        service.stop()


def test_traffico_registrato_per_la_console(bus, state, temp_paths, qt_app) -> None:
    """La Developer Console legge da qui: senza storico, non mostrerebbe nulla."""
    service = _service(
        bus, state, temp_paths, scenario=MockScenario(handshake_delay=0.0, latency=0.0)
    )
    state.set_app_state(AppState.RUNNING)

    try:
        service.start()
        assert _wait_until(qt_app, lambda: state.link_state is LinkState.ONLINE)
        tipi = [e.type for _, _, e in service.traffic_history()]
        assert MessageType.SESSION_HELLO in tipi
        assert MessageType.SESSION_WELCOME in tipi
    finally:
        service.stop()


def test_invio_a_canale_chiuso_non_solleva(bus, state, temp_paths) -> None:
    """Un pulsante premuto senza connessione non deve produrre un'eccezione."""
    assert _service(bus, state, temp_paths).send_chat("ciao", "m1") is False


def test_stop_e_idempotente(bus, state, temp_paths) -> None:
    service = _service(bus, state, temp_paths)
    service.stop()
    service.stop()
