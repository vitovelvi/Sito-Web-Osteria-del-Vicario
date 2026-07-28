"""Strumenti per collaudare adapter, plugin e backend.

Chi scrive un'estensione deve poterla verificare senza montare l'intera
applicazione. Qui ci sono le tre cose che servono ogni volta: costruire buste
valide, raccogliere ciò che un componente produce, e affermare qualcosa sulla
sequenza risultante.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from typing import Any

from jarvis_protocol.capabilities import CLIENT_CAPABILITIES
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.messages import MessageType
from jarvis_protocol.version import PROTOCOL_VERSION

__all__ = [
    "CollectingTransport",
    "assert_sequence",
    "make_hello",
    "make_welcome",
    "types_of",
]


def make_hello(**overrides: Any) -> Envelope:
    """Busta ``session.hello`` valida, per i test."""
    payload: dict[str, Any] = {
        "protocol": {"major": PROTOCOL_VERSION.major, "minor": PROTOCOL_VERSION.minor},
        "client": {"name": "test", "version": "0.0.0", "instance_id": "test"},
        "capabilities": sorted(CLIENT_CAPABILITIES),
        "auth": {"scheme": "none"},
    }
    payload.update(overrides)
    return Envelope.make(MessageType.SESSION_HELLO, payload)


def make_welcome(*, capabilities: Iterable[str] = (), **server: Any) -> Envelope:
    """Busta ``session.welcome`` valida, per i test."""
    return Envelope.make(
        MessageType.SESSION_WELCOME,
        {
            "protocol": {"major": PROTOCOL_VERSION.major, "minor": PROTOCOL_VERSION.minor},
            "server": {"name": "test-backend", **server},
            "capabilities": list(capabilities),
        },
    )


def types_of(envelopes: Iterable[Envelope]) -> list[str]:
    """Solo i tipi, nell'ordine. La forma in cui si legge una sequenza."""
    return [e.type for e in envelopes]


def assert_sequence(envelopes: Iterable[Envelope], expected: Iterable[str]) -> None:
    """Verifica che i tipi attesi compaiano **in ordine**, anche non adiacenti.

    L'adiacenza stretta renderebbe i test fragili: fra due messaggi che
    interessano ne possono comparire altri legittimi — uno stato, un progresso
    — e un test che si rompe per questo verrebbe presto disattivato.

    :raises AssertionError: se un tipo atteso non compare dopo il precedente.
    """
    presenti = types_of(envelopes)
    cursore = 0
    for atteso in expected:
        try:
            cursore = presenti.index(atteso, cursore) + 1
        except ValueError:
            raise AssertionError(
                f"'{atteso}' non trovato dopo la posizione {cursore}.\n"
                f"Sequenza ricevuta: {presenti}"
            ) from None


class CollectingTransport:
    """Trasporto finto che raccoglie l'inviato e restituisce il predisposto.

    Implementa il contratto del trasporto, quindi si può passare a un servizio
    reale senza che se ne accorga.
    """

    def __init__(self, responses: Iterable[Envelope] = ()) -> None:
        self.sent: list[Envelope] = []
        self._responses = list(responses)
        self._connected = False

    @property
    def endpoint(self) -> str:
        return "test://collecting"

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(Envelope.from_wire(message))

    async def receive(self) -> AsyncIterator[dict[str, Any]]:
        for busta in self._responses:
            if not self._connected:
                return
            yield busta.to_wire()

    def queue(self, *envelopes: Envelope) -> None:
        """Aggiunge risposte da restituire alla prossima lettura."""
        self._responses.extend(envelopes)
