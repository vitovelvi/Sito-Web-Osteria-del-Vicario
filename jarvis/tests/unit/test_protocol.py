"""Test del contratto di protocollo, delle capability e dell'identita'."""

from __future__ import annotations

import json

import pytest

from core.capabilities import CapabilityManager, MissingCapabilityError
from core.errors import ProtocolError
from core.eventbus import EventBus
from core.events import EventType
from core.identity import IdentityService
from core.protocol import PROTOCOL_VERSION, Capability, Envelope, MessageType, parse_payload
from core.protocol.messages import ServerHelloPayload

# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #


def test_roundtrip() -> None:
    originale = Envelope(type=MessageType.CHAT_SEND, payload={"text": "ciao"})
    ricostruito = Envelope.from_json(originale.to_json())

    assert ricostruito.type == originale.type
    assert ricostruito.id == originale.id
    assert ricostruito.payload["text"] == "ciao"


def test_id_ordinabili_nel_tempo() -> None:
    """Gli id ordinati alfabeticamente devono essere anche in ordine cronologico."""
    ids = [Envelope(type="ping").id for _ in range(50)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 50


def test_json_non_valido_solleva_protocol_error() -> None:
    with pytest.raises(ProtocolError, match="non decodificabile"):
        Envelope.from_json("{non json")


def test_json_non_oggetto_rifiutato() -> None:
    with pytest.raises(ProtocolError, match="atteso un oggetto"):
        Envelope.from_json("[1, 2, 3]")


def test_busta_incompleta_rifiutata() -> None:
    with pytest.raises(ProtocolError, match="non conforme"):
        Envelope.from_json(json.dumps({"v": 1}))  # manca 'type'


def test_campi_extra_ignorati() -> None:
    """Un backend piu' recente puo' aggiungere campi senza rompere questa build."""
    grezzo = json.dumps(
        {"v": 1, "id": "X", "type": "ping", "ts": 0.0, "payload": {}, "novita": True}
    )
    assert Envelope.from_json(grezzo).type == "ping"


def test_versione_supportata() -> None:
    assert Envelope(type="ping").is_supported
    assert not Envelope(type="ping", v=PROTOCOL_VERSION + 5).is_supported


def test_reply_correla() -> None:
    richiesta = Envelope(type=MessageType.CHAT_SEND)
    risposta = richiesta.reply(MessageType.CHAT_DELTA, {"text": "ok", "message_id": "1"})
    assert risposta.corr == richiesta.id


def test_payload_sconosciuto_non_e_errore() -> None:
    """Un tipo che questa build non conosce va ignorato, non fatto esplodere."""
    assert parse_payload("funzione.futura", {"x": 1}) is None


def test_payload_malformato_restituisce_none() -> None:
    assert parse_payload(MessageType.CHAT_DELTA, {"manca": "tutto"}) is None


def test_payload_valido_tipizzato() -> None:
    parsed = parse_payload(MessageType.CHAT_DELTA, {"text": "ciao", "message_id": "1"})
    assert parsed is not None
    assert parsed.text == "ciao"  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #


def test_capability_note_e_sconosciute(bus: EventBus) -> None:
    manager = CapabilityManager(bus)
    risultato = manager.apply(
        ["chat.stream", "tts.stream", "teletrasporto"], protocol_version=1
    )

    assert manager.has(Capability.CHAT_STREAM)
    assert not manager.has(Capability.VISION_INGEST)
    assert risultato.unknown == frozenset({"teletrasporto"})


def test_require_solleva_su_capability_assente(bus: EventBus) -> None:
    manager = CapabilityManager(bus)
    manager.apply(["chat.stream"], protocol_version=1)

    manager.require(Capability.CHAT_STREAM)
    with pytest.raises(MissingCapabilityError):
        manager.require(Capability.VISION_INGEST)


def test_clear_alla_disconnessione(bus: EventBus) -> None:
    """Senza canale nessuna funzione e' disponibile, e la GUI deve dirlo."""
    manager = CapabilityManager(bus)
    manager.apply(["chat.stream", "tasks"], protocol_version=1)
    manager.clear()

    assert manager.granted == frozenset()
    assert manager.protocol_version == 0


def test_capabilities_pubblicate(bus: EventBus, collected: list) -> None:
    CapabilityManager(bus).apply(["chat.stream"], protocol_version=1)
    assert any(e.type is EventType.CAPABILITIES_UPDATED for e in collected)


def test_nessun_evento_se_l_insieme_non_cambia(bus: EventBus, collected: list) -> None:
    manager = CapabilityManager(bus)
    manager.apply(["chat.stream"], protocol_version=1)
    prima = len(collected)
    manager.apply(["chat.stream"], protocol_version=1)
    assert len(collected) == prima


# --------------------------------------------------------------------------- #
# Identita'
# --------------------------------------------------------------------------- #


def test_identita_locale_persistente(bus: EventBus, temp_paths) -> None:
    """L'instance_id deve sopravvivere ai riavvii."""
    primo = IdentityService(bus, temp_paths).client.instance_id
    secondo = IdentityService(bus, temp_paths).client.instance_id
    assert primo == secondo


def test_identita_backend_non_confermata_prima_dell_handshake(
    bus: EventBus, temp_paths
) -> None:
    servizio = IdentityService(bus, temp_paths)
    assert not servizio.is_confirmed
    assert servizio.backend.model is None


def test_handshake_aggiorna_identita(bus: EventBus, temp_paths, collected: list) -> None:
    servizio = IdentityService(bus, temp_paths)
    servizio.apply_server_hello(
        ServerHelloPayload(
            protocol_version=1,
            backend_version="2.1.0",
            model="claude-opus",
            session_id="s-1",
        )
    )

    assert servizio.is_confirmed
    assert servizio.backend.model == "claude-opus"
    assert servizio.session_id == "s-1"
    assert any(e.type is EventType.IDENTITY_UPDATED for e in collected)


def test_disconnessione_azzera_l_identita_remota(bus: EventBus, temp_paths) -> None:
    """Senza canale la GUI non sa piu' quale modello sia attivo: non deve affermarlo."""
    servizio = IdentityService(bus, temp_paths)
    servizio.apply_server_hello(
        ServerHelloPayload(protocol_version=1, model="claude-opus", backend_version="2.1.0")
    )

    servizio.forget_remote()

    assert not servizio.is_confirmed
    assert servizio.backend.model is None
    assert servizio.display_name  # il nome del prodotto resta


def test_hello_dichiara_versione_e_capability(bus: EventBus, temp_paths) -> None:
    hello = IdentityService(bus, temp_paths).hello_payload()
    assert hello.protocol_version == PROTOCOL_VERSION
    assert Capability.CHAT_STREAM.value in hello.capabilities
    assert hello.instance_id
