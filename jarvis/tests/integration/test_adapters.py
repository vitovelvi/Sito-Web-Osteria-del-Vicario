"""Test dell'adapter layer.

Verificano la proprietà che giustifica l'intero livello: **il resto
dell'applicazione non deve accorgersi di quale backend stia parlando**. Perciò
i test si concentrano sulla traduzione, non sul dialetto in sé — quello è
provvisorio e cambierà quando il protocollo reale di OpenClaw sarà noto.
"""

from __future__ import annotations

from core.jcp.envelope import Envelope
from core.jcp.messages import MessageType
from core.jcp.version import PROTOCOL_VERSION
from network.adapters.native import NativeJcpAdapter
from network.adapters.openclaw import OpenClawAdapter

# --------------------------------------------------------------------------- #
# Adapter nativo
# --------------------------------------------------------------------------- #


def test_nativo_non_altera_nulla() -> None:
    adapter = NativeJcpAdapter()
    originale = Envelope.make(MessageType.CHAT_SEND, {"text": "ciao", "message_id": "m1"})

    inviato = adapter.to_backend(originale)[0]
    tornato = adapter.from_backend(inviato)[0]

    assert tornato.type == originale.type
    assert tornato.id == originale.id
    assert tornato.payload == originale.payload


def test_nativo_scarta_una_busta_malformata() -> None:
    """Un messaggio rotto produce zero buste, non un'eccezione."""
    assert NativeJcpAdapter().from_backend({"non": "una busta"}) == []


# --------------------------------------------------------------------------- #
# Adapter OpenClaw
# --------------------------------------------------------------------------- #


def test_traduce_il_messaggio_utente() -> None:
    adapter = OpenClawAdapter()
    envelope = Envelope.make(MessageType.CHAT_SEND, {"text": "ciao", "message_id": "m1"})

    messaggio = adapter.to_backend(envelope)[0]

    assert messaggio["type"] == "message"
    assert messaggio["data"] == {"content": "ciao", "id": "m1"}
    assert messaggio["request_id"] == envelope.id


def test_tipo_senza_corrispondenza_non_viene_inviato() -> None:
    """Non tutti i backend hanno un equivalente per ogni messaggio JCP."""
    adapter = OpenClawAdapter()
    assert adapter.to_backend(Envelope.make(MessageType.TELEMETRY_SYSTEM, {})) == []


def test_traduce_il_vocabolario_degli_stati() -> None:
    """Il vocabolario di un backend specifico non deve arrivare al nucleo."""
    adapter = OpenClawAdapter()

    for backend_state, atteso in (
        ("processing", "thinking"),
        ("tool_use", "executing"),
        ("responding", "speaking"),
        ("ready", "idle"),
    ):
        buste = adapter.from_backend({"type": "status", "data": {"value": backend_state}})
        assert buste[0].payload["state"] == atteso


def test_stato_sconosciuto_non_viene_indovinato() -> None:
    """Meglio restare sull'ultimo stato confermato che inventarne uno."""
    adapter = OpenClawAdapter()
    assert adapter.from_backend({"type": "status", "data": {"value": "boh"}}) == []


def test_traduce_le_capability() -> None:
    adapter = OpenClawAdapter()
    buste = adapter.from_backend(
        {
            "type": "connected",
            "data": {"version": "2.4", "model": "m", "features": ["streaming", "voice"]},
        }
    )
    capability = buste[0].payload["capabilities"]

    assert "chat.stream" in capability
    assert "tts.stream" in capability
    assert buste[0].payload["protocol"]["major"] == PROTOCOL_VERSION.major


def test_capability_dichiarate_anche_in_uscita() -> None:
    """Senza traduzione in uscita la negoziazione sarebbe asimmetrica."""
    adapter = OpenClawAdapter()
    hello = Envelope.make(
        MessageType.SESSION_HELLO,
        {
            "client": {"name": "jarvis-desktop", "version": "1"},
            "capabilities": ["chat.stream", "tts.stream"],
            "auth": {"scheme": "none"},
        },
    )

    features = adapter.to_backend(hello)[0]["data"]["features"]

    assert set(features) == {"streaming", "voice"}


def test_primo_blocco_audio_produce_apertura_e_dato() -> None:
    """Emettere solo l'apertura perderebbe il primo frammento di audio.

    È il difetto che all'ascolto si nota appena, e per questo è tanto più
    insidioso: senza questo test, sarebbe passato inosservato fino al primo
    collegamento al backend reale.
    """
    adapter = OpenClawAdapter()

    buste = adapter.from_backend(
        {"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "AAAA"}}
    )

    assert [b.type for b in buste] == [MessageType.STREAM_OPEN, MessageType.STREAM_DATA]
    assert buste[1].payload["data"] == "AAAA"


def test_blocchi_successivi_non_riaprono_lo_stream() -> None:
    adapter = OpenClawAdapter()
    adapter.from_backend({"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}})

    buste = adapter.from_backend(
        {"type": "speech", "data": {"id": "s1", "seq": 1, "audio": "B"}}
    )

    assert [b.type for b in buste] == [MessageType.STREAM_DATA]
    assert buste[0].payload["seq"] == 1


def test_chiusura_stream_e_riapertura() -> None:
    adapter = OpenClawAdapter()
    adapter.from_backend({"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}})
    chiusura = adapter.from_backend({"type": "speech_end", "data": {"id": "s1"}})

    assert chiusura[0].type == MessageType.STREAM_CLOSE

    # Un nuovo stream con lo stesso identificativo deve riaprirsi.
    riapertura = adapter.from_backend(
        {"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}}
    )
    assert riapertura[0].type == MessageType.STREAM_OPEN


def test_reset_azzera_lo_stato_di_traduzione() -> None:
    """Alla caduta della sessione l'adapter non deve ricordare gli stream aperti."""
    adapter = OpenClawAdapter()
    adapter.from_backend({"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}})

    adapter.reset()
    buste = adapter.from_backend(
        {"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}}
    )

    assert buste[0].type == MessageType.STREAM_OPEN


def test_messaggio_sconosciuto_ignorato() -> None:
    assert OpenClawAdapter().from_backend({"type": "novita_del_futuro", "data": {}}) == []


def test_messaggio_senza_tipo_ignorato() -> None:
    assert OpenClawAdapter().from_backend({"data": {}}) == []


def test_dati_non_dizionario_tollerati() -> None:
    """Un campo 'data' della forma sbagliata non deve far cadere il canale."""
    buste = OpenClawAdapter().from_backend({"type": "status", "data": "non un oggetto"})
    assert buste == []  # stato mancante → nessuna traduzione, nessuna eccezione


def test_describe_espone_lo_stato_per_la_console() -> None:
    adapter = OpenClawAdapter()
    adapter.from_backend({"type": "speech", "data": {"id": "s1", "seq": 0, "audio": "A"}})

    info = adapter.describe()

    assert info["name"] == "openclaw"
    assert info["translates"] is True
    assert info["open_streams"] == 1
