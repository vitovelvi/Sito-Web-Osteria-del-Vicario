"""Test dell'SDK: registrazione, replay, plugin, adapter."""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.errors import ProtocolError
from jarvis_protocol.messages import MessageType

from jarvis_sdk import PLUGIN_API_VERSION, PluginManifest, Recording, SessionRecorder
from jarvis_sdk.adapter import BaseAdapter
from jarvis_sdk.plugins import discover, validate_manifest
from jarvis_sdk.recording import SessionReplayer, redact_envelope
from jarvis_sdk.testing import CollectingTransport, assert_sequence, make_hello, make_welcome

# --------------------------------------------------------------------------- #
# Registrazione
# --------------------------------------------------------------------------- #


def test_round_trip(tmp_path) -> None:
    registratore = SessionRecorder(client="prova")
    registratore.start("nota")
    registratore.record("out", make_hello())
    registratore.record("in", make_welcome(capabilities=["chat.stream"]))
    originale = registratore.stop()

    percorso = tmp_path / "s.jcpl"
    originale.save(percorso)
    riletta = Recording.load(percorso)

    assert len(riletta) == 2
    assert [m.direction for m in riletta] == ["out", "in"]
    assert riletta.client == "prova"
    assert riletta.note == "nota"


def test_il_token_non_finisce_nel_file(tmp_path) -> None:
    """Una registrazione nasce per essere allegata a una segnalazione."""
    registratore = SessionRecorder()
    registratore.start()
    registratore.record("out", make_hello(auth={"scheme": "token", "token": "SEGRETISSIMO"}))

    percorso = tmp_path / "s.jcpl"
    registratore.stop().save(percorso)

    assert "SEGRETISSIMO" not in percorso.read_text(encoding="utf-8")


def test_i_blocchi_audio_non_gonfiano_il_file() -> None:
    grande = Envelope.make(
        MessageType.STREAM_DATA, {"stream_id": "s", "seq": 0, "data": "A" * 10_000}
    )
    ridotta = redact_envelope(grande)

    assert ridotta.payload["data"] == ""
    assert ridotta.payload["_omitted_chars"] == 10_000


def test_chiavi_che_sembrano_segreti_ovunque_si_trovino() -> None:
    busta = Envelope.make("ext.x.y", {"livello": {"api_key": "abc", "innocuo": "ok"}})
    ridotta = redact_envelope(busta)

    assert ridotta.payload["livello"]["api_key"] != "abc"
    assert ridotta.payload["livello"]["innocuo"] == "ok"


def test_registrazione_troncata_resta_leggibile(tmp_path) -> None:
    """Il caso interessante è proprio quello: il processo ucciso a metà."""
    registratore = SessionRecorder()
    registratore.start()
    registratore.record("in", make_welcome())
    percorso = tmp_path / "s.jcpl"
    registratore.stop().save(percorso)

    with percorso.open("a", encoding="utf-8") as handle:
        handle.write('{"t":1.0,"dir":"in","env":{"rot')  # riga troncata

    riletta = Recording.load(percorso)
    assert len(riletta) == 1  # la riga valida resta


def test_intestazione_mancante_rifiutata(tmp_path) -> None:
    percorso = tmp_path / "vuoto.jcpl"
    percorso.write_text("", encoding="utf-8")
    with pytest.raises(ProtocolError, match="intestazione"):
        Recording.load(percorso)


def test_versione_di_formato_ignota_rifiutata(tmp_path) -> None:
    percorso = tmp_path / "futuro.jcpl"
    percorso.write_text(json.dumps({"jcpl": 99}) + "\n", encoding="utf-8")
    with pytest.raises(ProtocolError, match="versione"):
        Recording.load(percorso)


def test_tetto_ai_messaggi() -> None:
    """Uno stream audio produce sedici messaggi al secondo."""
    registratore = SessionRecorder(limit=3)
    registratore.start()
    for _ in range(10):
        registratore.record("in", make_welcome())

    assert len(registratore.stop()) == 3
    assert registratore.truncated


def test_registratore_fermo_non_registra() -> None:
    registratore = SessionRecorder()
    registratore.record("in", make_welcome())
    assert len(registratore.current) == 0


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


async def test_il_replay_riproduce_solo_l_ingresso() -> None:
    registratore = SessionRecorder()
    registratore.start()
    registratore.record("out", make_hello())
    registratore.record("in", make_welcome())

    replayer = SessionReplayer(registratore.stop(), speed=0)
    await replayer.connect()

    ricevuti = [Envelope.from_wire(m) async for m in replayer.receive()]
    assert [e.type for e in ricevuti] == [MessageType.SESSION_WELCOME]


async def test_il_replay_non_reagisce() -> None:
    """È un limite intrinseco, non un difetto: per reagire c'è la simulazione."""
    registratore = SessionRecorder()
    registratore.start()
    registratore.record("in", make_welcome())

    replayer = SessionReplayer(registratore.stop(), speed=0)
    await replayer.connect()
    await replayer.send({"t": "chat.send", "p": {}})
    await replayer.send({"t": "link.ping", "p": {}})

    assert replayer.client_messages_ignored == 2


async def test_le_pause_lunghe_sono_compresse() -> None:
    """Quaranta secondi di attesa non hanno valore diagnostico."""
    import time

    recording = Recording()
    recording.messages.append(
        __import__("jarvis_sdk.recording", fromlist=["RecordedMessage"]).RecordedMessage(
            0.0, "in", make_welcome()
        )
    )
    recording.messages.append(
        __import__("jarvis_sdk.recording", fromlist=["RecordedMessage"]).RecordedMessage(
            40.0, "in", make_welcome()
        )
    )

    replayer = SessionReplayer(recording, speed=1.0, max_gap=0.05)
    await replayer.connect()
    avvio = time.monotonic()
    _ = [m async for m in replayer.receive()]

    assert time.monotonic() - avvio < 1.0


# --------------------------------------------------------------------------- #
# Plugin
# --------------------------------------------------------------------------- #


def _manifest(**overrides) -> dict:
    base = {
        "id": "acme.meteo",
        "name": "Meteo",
        "version": "1.0.0",
        "api_version": PLUGIN_API_VERSION,
        "entry_point": "plugin:Plugin",
    }
    base.update(overrides)
    return base


def test_manifesto_valido() -> None:
    assert validate_manifest(PluginManifest.from_dict(_manifest())) == []


def test_tutti_i_problemi_insieme() -> None:
    """Correggerne uno per volta scoprendo il successivo è tempo perso."""
    problemi = validate_manifest(
        PluginManifest.from_dict(_manifest(id="Acme Meteo!", name="", version=""))
    )
    campi = {p.field for p in problemi}
    assert {"id", "name", "version"} <= campi


def test_versione_di_api_incompatibile() -> None:
    problemi = validate_manifest(
        PluginManifest.from_dict(_manifest(api_version=PLUGIN_API_VERSION + 1))
    )
    assert any(p.field == "api_version" for p in problemi)


def test_scoperta_senza_importare(tmp_path) -> None:
    """Si può sapere cosa c'è senza eseguirlo."""
    directory = tmp_path / "acme.meteo"
    directory.mkdir()
    (directory / "plugin.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    (directory / "plugin.py").write_text("raise RuntimeError('non deve essere importato')")

    trovati = discover(tmp_path)
    assert [m.id for m in trovati] == ["acme.meteo"]


def test_manifesto_illeggibile_ignorato(tmp_path) -> None:
    directory = tmp_path / "rotto"
    directory.mkdir()
    (directory / "plugin.json").write_text("{{{ non json", encoding="utf-8")
    assert discover(tmp_path) == []


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


class _Adapter(BaseAdapter):
    name = "prova"
    TO_BACKEND: ClassVar[dict[str, str]] = {MessageType.CHAT_SEND: "invia"}
    FROM_BACKEND: ClassVar[dict[str, str]] = {
        "frammento": MessageType.CHAT_DELTA,
        "stato": MessageType.AGENT_STATE,
    }
    CORRELATION_KEY = "rid"

    def translate_outgoing(self, envelope):
        return {"testo": envelope.payload.get("text", "")}

    def translate_incoming(self, jcp_type, data):
        if jcp_type == MessageType.AGENT_STATE:
            noti = {"pensa": "thinking", "parla": "speaking"}
            stato = noti.get(str(data.get("v")))
            return None if stato is None else {"state": stato}
        return {"text": data.get("t", ""), "message_id": data.get("id", "")}


def test_traduzione_nei_due_versi() -> None:
    adapter = _Adapter()
    uscita = adapter.to_backend(Envelope.make(MessageType.CHAT_SEND, {"text": "ciao"}))

    assert uscita[0]["type"] == "invia"
    assert uscita[0]["data"] == {"testo": "ciao"}
    assert "rid" in uscita[0]

    ingresso = adapter.from_backend({"type": "frammento", "data": {"t": "ok", "id": "m1"}})
    assert ingresso[0].type == MessageType.CHAT_DELTA
    assert ingresso[0].payload["text"] == "ok"


def test_tipo_senza_corrispondenza_non_viene_inviato() -> None:
    assert _Adapter().to_backend(Envelope.make(MessageType.PING)) == []


def test_messaggio_sconosciuto_ignorato() -> None:
    assert _Adapter().from_backend({"type": "novita", "data": {}}) == []


def test_valore_non_traducibile_scarta_il_messaggio() -> None:
    """Inventare un payload sarebbe peggio: la GUI mostrerebbe con sicurezza
    qualcosa che nessuno ha dichiarato."""
    assert _Adapter().from_backend({"type": "stato", "data": {"v": "boh"}}) == []


def test_traduzione_che_solleva_non_propaga() -> None:
    class Rotto(_Adapter):
        def translate_incoming(self, jcp_type, data):
            raise RuntimeError("guasto")

    assert Rotto().from_backend({"type": "frammento", "data": {}}) == []


def test_copertura_dei_tipi_richiesti() -> None:
    mancanti = _Adapter().coverage({MessageType.CHAT_SEND, MessageType.SESSION_HELLO})
    assert mancanti == {MessageType.SESSION_HELLO}


# --------------------------------------------------------------------------- #
# Utilità di collaudo
# --------------------------------------------------------------------------- #


async def test_transport_di_raccolta() -> None:
    transport = CollectingTransport([make_welcome()])
    await transport.connect()
    await transport.send(make_hello().to_wire())

    ricevuti = [Envelope.from_wire(m) async for m in transport.receive()]

    assert transport.sent[0].type == MessageType.SESSION_HELLO
    assert ricevuti[0].type == MessageType.SESSION_WELCOME


def test_assert_sequence_tollera_messaggi_intermedi() -> None:
    """L'adiacenza stretta renderebbe i test fragili."""
    buste = [
        Envelope.make(MessageType.SESSION_HELLO),
        Envelope.make(MessageType.AGENT_STATE, {"state": "idle"}),
        Envelope.make(MessageType.CHAT_DELTA, {"text": "x", "message_id": "m"}),
    ]
    assert_sequence(buste, [MessageType.SESSION_HELLO, MessageType.CHAT_DELTA])

    with pytest.raises(AssertionError, match="non trovato"):
        assert_sequence(buste, [MessageType.CHAT_DELTA, MessageType.SESSION_HELLO])
