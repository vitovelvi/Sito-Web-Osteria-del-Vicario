"""Servizio di rete: unico ponte fra la GUI e OpenClaw.

**Modello di concorrenza.** Il loop asyncio vive in un thread dedicato; la
frontiera con l'interfaccia è fatta solo di pubblicazioni sul bus, che
marshalla da sé verso il thread GUI. La conseguenza è strutturale: nessuna
coroutine può bloccare il rendering, qualunque cosa faccia la rete.

L'alternativa — ``qasync``, un unico loop condiviso — è più elegante sulla
carta, ma una coroutine lenta blocca l'interfaccia e gli stack misti Qt/asyncio
sono penosi da leggere. Qui il costo è un ``run_coroutine_threadsafe`` per
l'invio, incapsulato in :meth:`NetworkService.send`.

**Ciclo di vita di una sessione**: connessione → ``client.hello`` →
``server.hello`` (con timeout proprio, distinto da quello di connessione) →
heartbeat → lettura dei messaggi. Alla caduta: identità azzerata, capability
svuotate, backoff e nuovo tentativo. Il tutto senza mai bloccare l'avvio della
GUI, che parte e resta reattiva anche se il backend non esiste.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from typing import Any

from core.capabilities import CapabilityManager
from core.errors import ErrorCondition, ErrorSeverity, TransportError
from core.eventbus import EventBus
from core.events import Empty, EventType, LatencySample, LinkStatus
from core.identity import IdentityService
from core.logging_setup import LogCategory, get_logger
from core.protocol.envelope import Envelope
from core.protocol.messages import MessageType
from core.qtcompat import QtCore
from core.service import Health, ServiceState
from core.settings import BackendSettings
from core.state.machines import LinkState
from core.state.manager import StateManager
from network.dispatcher import MessageDispatcher
from network.mock.backend import MockScenario, MockTransport
from network.reconnect import BackoffPolicy
from network.transport.base import ITransport
from network.transport.websocket import WebSocketTransport

__all__ = ["NetworkService"]

_log = get_logger(LogCategory.NETWORK)

#: Campione di latenza conservati per la media mobile mostrata in HUD.
_LATENCY_WINDOW = 10

#: Heartbeat mancati consecutivi dopo i quali la sessione si considera persa.
_MAX_MISSED_BEATS = 3


class NetworkService(QtCore.QObject):
    """Gestisce connessione, handshake, heartbeat e riconnessione.

    Implementa :class:`~core.service.IService` per struttura, non per eredità:
    ``QObject`` e ``ABCMeta`` hanno metaclassi incompatibili, e il protocollo è
    ``runtime_checkable``, quindi il registry lo riconosce comunque.
    """

    name = "network"

    def __init__(
        self,
        bus: EventBus,
        state: StateManager,
        identity: IdentityService,
        capabilities: CapabilityManager,
        settings: BackendSettings,
        *,
        scenario: MockScenario | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._state = state
        self._identity = identity
        self._capabilities = capabilities
        self._settings = settings
        self._scenario = scenario
        self._dispatcher = MessageDispatcher(bus, state, identity, capabilities)

        self._thread: QtCore.QThread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._stopping = threading.Event()

        self._transport: ITransport | None = None
        self._backoff = BackoffPolicy(
            initial=settings.reconnect_initial_s,
            maximum=settings.reconnect_max_s,
            factor=settings.reconnect_factor,
            jitter=settings.reconnect_jitter,
            circuit_threshold=settings.circuit_breaker_threshold,
        )

        self._pending_pings: dict[str, float] = {}
        self._latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self._service_state = ServiceState.STOPPED
        self._detail: str | None = None

    # ------------------------------------------------------------------ #
    # Ciclo di vita del servizio
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Avvia il thread di rete. Ritorna immediatamente."""
        if self._thread is not None:
            return

        self._stopping.clear()
        self._loop_ready.clear()
        self._service_state = ServiceState.STARTING

        service = self

        class _NetworkThread(QtCore.QThread):
            """Thread proprietario del loop asyncio."""

            def run(self) -> None:
                try:
                    asyncio.run(service._main())
                except Exception:
                    _log.exception("Il ciclo di rete è terminato in modo anomalo")

        self._thread = _NetworkThread()
        self._thread.setObjectName("jarvis-network")
        self._thread.start()
        self._service_state = ServiceState.RUNNING
        _log.info("Servizio di rete avviato (trasporto: %s)", self._settings.transport)

    def stop(self) -> None:
        """Ferma il thread di rete in modo ordinato. Idempotente."""
        thread, self._thread = self._thread, None
        self._stopping.set()

        loop = self._loop
        if loop is not None and not loop.is_closed():
            # Il loop gira in un altro thread: lo si sveglia da lì.
            loop.call_soon_threadsafe(loop.stop)

        if thread is not None:
            if not thread.wait(3000):
                _log.warning("Il thread di rete non si è fermato entro 3 s")
            else:
                _log.info("Servizio di rete fermato")

        self._loop = None
        self._service_state = ServiceState.STOPPED

    def health(self) -> Health:
        """Salute del servizio, senza mai sollevare."""
        return Health(state=self._service_state, detail=self._detail)

    # ------------------------------------------------------------------ #
    # Invio dalla GUI
    # ------------------------------------------------------------------ #

    def send(self, message_type: str, payload: dict[str, Any] | None = None) -> bool:
        """Invia un messaggio al backend. Chiamabile dal thread GUI.

        :returns: ``False`` se il canale non è disponibile. Non solleva: chi
            chiama è un widget, e un pulsante premuto a canale chiuso non deve
            produrre un'eccezione ma un'indicazione visiva.
        """
        loop = self._loop
        if loop is None or loop.is_closed() or self._transport is None:
            _log.debug("Invio di '%s' scartato: canale non disponibile", message_type)
            return False

        envelope = Envelope(type=message_type, payload=payload or {})
        try:
            asyncio.run_coroutine_threadsafe(self._send(envelope), loop)
        except RuntimeError as exc:  # loop fermato fra il controllo e l'invio
            _log.debug("Invio di '%s' non riuscito: %s", message_type, exc)
            return False
        return True

    async def _send(self, envelope: Envelope) -> None:
        transport = self._transport
        if transport is None:
            return
        try:
            await transport.send(envelope)
        except TransportError as exc:
            _log.warning("Invio non riuscito: %s", exc)

    # ------------------------------------------------------------------ #
    # Ciclo principale
    # ------------------------------------------------------------------ #

    async def _main(self) -> None:
        """Ciclo di connessione e riconnessione. Gira nel thread di rete."""
        self._loop = asyncio.get_running_loop()
        self._loop_ready.set()

        while not self._stopping.is_set():
            self._state.set_link_state(LinkState.CONNECTING, reason=self._backoff.describe())

            transport = self._make_transport()
            try:
                await transport.connect()
            except TransportError as exc:
                await self._handle_connect_failure(str(exc))
                continue

            self._transport = transport
            self._detail = None
            try:
                await self._session(transport)
            except asyncio.CancelledError:
                raise
            except TransportError as exc:
                _log.info("Sessione interrotta: %s", exc)
                self._detail = str(exc)
            except Exception as exc:
                _log.exception("Errore imprevisto nella sessione")
                self._detail = str(exc)
            finally:
                await self._teardown(transport)

            if self._stopping.is_set():
                break

            delay = self._backoff.next_delay()
            _log.info("Nuovo tentativo fra %.1f s", delay)
            await asyncio.sleep(delay)

    def _make_transport(self) -> ITransport:
        """Costruisce il trasporto scelto dalla configurazione."""
        if self._settings.transport == "mock":
            return MockTransport(self._scenario)
        return WebSocketTransport(
            self._settings.url, connect_timeout=self._settings.connect_timeout_s
        )

    async def _handle_connect_failure(self, reason: str) -> None:
        """Registra un tentativo fallito e attende prima del successivo."""
        delay = self._backoff.next_delay()
        self._detail = reason
        _log.warning("Connessione non riuscita (%s): nuovo tentativo fra %.1f s", reason, delay)

        self._state.set_link_state(LinkState.OFFLINE, reason=reason)
        if self._backoff.circuit_open:
            # Dopo molti fallimenti la causa non è transitoria: lo si dice,
            # invece di lasciar credere che il prossimo tentativo sia imminente.
            self._state.raise_error(
                ErrorCondition(
                    source="network",
                    message="Backend non raggiungibile",
                    detail=reason,
                    severity=ErrorSeverity.WARNING,
                )
            )
        await asyncio.sleep(delay)

    async def _session(self, transport: ITransport) -> None:
        """Handshake, heartbeat e lettura dei messaggi."""
        messages = transport.receive().__aiter__()

        await transport.send(
            Envelope(
                type=MessageType.CLIENT_HELLO,
                payload=self._identity.hello_payload().model_dump(),
            )
        )

        # L'handshake ha un timeout **proprio**: un backend che accetta la
        # connessione TCP ma non si presenta è un caso reale (servizio in avvio,
        # porta occupata da un altro processo) e non va confuso con un host
        # irraggiungibile, che fallisce prima.
        try:
            await asyncio.wait_for(
                self._await_handshake(messages), timeout=self._settings.connect_timeout_s * 2
            )
        except TimeoutError as exc:
            raise TransportError("Il backend non si è presentato entro il timeout") from exc

        self._backoff.reset()
        self._state.clear_error("network")
        self._state.set_link_state(LinkState.ONLINE, reason="handshake completato")
        self._bus.publish(
            EventType.CONNECTED,
            LinkStatus(state=LinkState.ONLINE.value, endpoint=transport.endpoint),
            source="network",
        )

        heartbeat = asyncio.create_task(self._heartbeat(transport))
        try:
            async for envelope in messages:
                if envelope.type == MessageType.PONG:
                    self._on_pong(envelope)
                    continue
                self._dispatcher.dispatch(envelope)
        finally:
            heartbeat.cancel()
            # Si attende davvero la cancellazione: senza, il compito potrebbe
            # sopravvivere alla sessione e scrivere su un trasporto già chiuso.
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _await_handshake(self, messages: Any) -> None:
        """Consuma i messaggi finché non arriva una presentazione valida."""
        async for envelope in messages:
            if envelope.type != MessageType.SERVER_HELLO:
                _log.debug("In attesa dell'handshake, ignorato: %s", envelope.type)
                continue
            if self._dispatcher.apply_server_hello(envelope) is None:
                raise TransportError("Presentazione del backend rifiutata")
            return
        raise TransportError("Canale chiuso prima dell'handshake")

    async def _teardown(self, transport: ITransport) -> None:
        """Chiude la sessione e riporta l'interfaccia allo stato reale."""
        self._transport = None
        self._pending_pings.clear()
        self._latencies.clear()

        await transport.close()

        # Senza canale la GUI non sa più quale modello sia attivo né cosa il
        # backend sappia fare: continuare a mostrarlo sarebbe una bugia.
        self._identity.forget_remote()
        self._capabilities.clear()

        self._state.set_link_state(LinkState.OFFLINE, reason=self._detail or "canale chiuso")
        self._bus.publish(
            EventType.DISCONNECTED,
            LinkStatus(state=LinkState.OFFLINE.value, reason=self._detail),
            source="network",
        )

    # ------------------------------------------------------------------ #
    # Heartbeat
    # ------------------------------------------------------------------ #

    async def _heartbeat(self, transport: ITransport) -> None:
        """Misura la latenza e rileva un canale muto.

        Un socket TCP aperto non garantisce che dall'altra parte ci sia ancora
        qualcuno: senza heartbeat applicativo, una caduta silenziosa lascia
        l'HUD su "Jarvis online" finché l'utente non prova a parlargli.
        """
        missed = 0
        interval = self._settings.heartbeat_interval_s

        while True:
            await asyncio.sleep(interval)

            ping = Envelope(type=MessageType.PING)
            self._pending_pings[ping.id] = time.monotonic()
            try:
                await transport.send(ping)
            except TransportError as exc:
                raise TransportError(f"Heartbeat non inviato: {exc}") from exc

            await asyncio.sleep(self._settings.heartbeat_timeout_s)

            if self._pending_pings.pop(ping.id, None) is None:
                missed = 0  # la risposta è arrivata: lo stato lo gestisce _on_pong
                continue

            missed += 1
            _log.warning("Heartbeat senza risposta (%d/%d)", missed, _MAX_MISSED_BEATS)
            if missed >= _MAX_MISSED_BEATS:
                raise TransportError("Il backend non risponde all'heartbeat")

            self._state.set_link_state(LinkState.DEGRADED, reason="heartbeat mancato")

    def _on_pong(self, envelope: Envelope) -> None:
        """Registra la latenza di andata e ritorno."""
        sent_at = self._pending_pings.pop(envelope.corr or "", None)
        if sent_at is None:
            return  # risposta tardiva a un ping già scaduto

        rtt_ms = (time.monotonic() - sent_at) * 1000.0
        self._latencies.append(rtt_ms)
        average = sum(self._latencies) / len(self._latencies)

        self._bus.publish(
            EventType.TRANSPORT_LATENCY,
            LatencySample(rtt_ms=rtt_ms, average_ms=average),
            source="network",
        )

        # La media, non il singolo campione: un picco isolato non deve far
        # lampeggiare l'HUD fra "online" e "lento".
        if average > self._settings.degraded_latency_ms:
            self._state.set_link_state(LinkState.DEGRADED, reason=f"latenza {average:.0f} ms")
        elif self._state.link_state is LinkState.DEGRADED:
            self._state.set_link_state(LinkState.ONLINE, reason="latenza rientrata")

    # ------------------------------------------------------------------ #
    # Comandi di alto livello
    # ------------------------------------------------------------------ #

    def send_chat(self, text: str, message_id: str) -> bool:
        """Invia un messaggio dell'utente."""
        return self.send(
            MessageType.CHAT_SEND, {"text": text, "message_id": message_id}
        )

    def cancel(self) -> bool:
        """Chiede l'interruzione della risposta in corso."""
        return self.send(MessageType.CHAT_CANCEL)

    def voice_start(self) -> bool:
        """Segnala l'inizio dell'ascolto."""
        self._bus.publish(EventType.VOICE_STARTED, Empty(), source="network")
        return self.send(MessageType.VOICE_START)

    def voice_stop(self) -> bool:
        """Segnala la fine dell'ascolto."""
        self._bus.publish(EventType.VOICE_STOPPED, Empty(), source="network")
        return self.send(MessageType.VOICE_STOP)
