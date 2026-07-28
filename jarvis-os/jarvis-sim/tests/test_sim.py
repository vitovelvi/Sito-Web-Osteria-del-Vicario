"""Test dell'ambiente di simulazione e della verifica di conformità."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import replace

import pytest
from jarvis_protocol.envelope import Envelope
from jarvis_protocol.errors import TransportError
from jarvis_protocol.messages import MessageType
from jarvis_protocol.missions import MissionType
from jarvis_protocol.version import PROTOCOL_VERSION
from jarvis_sdk.conformance import Outcome, run_conformance

from jarvis_sim import Scenario, SimTransport, by_name, names
from jarvis_sim.library import NOMINAL


def _fast(scenario: Scenario, **behaviour) -> Scenario:
    """Scenario senza attese: i test devono essere rapidi e deterministici.

    Azzera anche ``confirm_probability``: una conferma senza risposta attende
    il proprio timeout, e un test che non parla di conferme non deve pagarlo.
    Chi le vuole le riattiva esplicitamente.
    """
    comportamento = {"step_delay": 0.01, "confirm_probability": 0.0}
    comportamento.update(behaviour)
    return scenario.with_channel(latency=0.0, handshake_delay=0.0).with_behaviour(
        **comportamento
    )


async def _run(
    scenario: Scenario, *, until: str, timeout: float = 20.0, chat: bool = True
) -> list[Envelope]:
    """Esegue una sessione e raccoglie fino al messaggio atteso.

    :param chat: se inviare anche un messaggio dell'utente. Va disattivato
        quando si osserva il solo handshake: un backend che non si presenta
        puo' comunque reagire alla chat, e il rumore nasconderebbe la prova.
    """
    transport = SimTransport(scenario)
    await transport.connect()
    await transport.send(Envelope.make(MessageType.SESSION_HELLO).to_wire())
    if chat:
        await transport.send(
            Envelope.make(MessageType.CHAT_SEND, {"text": "x", "message_id": "m1"}).to_wire()
        )

    ricevuti: list[Envelope] = []

    async def pump() -> None:
        async for messaggio in transport.receive():
            busta = Envelope.from_wire(messaggio)
            ricevuti.append(busta)
            if busta.type == until:
                return

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(pump(), timeout)
    await transport.close()
    return ricevuti


# --------------------------------------------------------------------------- #
# Scenari
# --------------------------------------------------------------------------- #


def test_la_libreria_non_e_vuota() -> None:
    assert len(names()) >= 10
    assert "nominale" in names()


def test_nome_sconosciuto_elenca_i_validi() -> None:
    """Un errore che dice solo 'non trovato' costringe a cercare altrove."""
    with pytest.raises(KeyError, match="Disponibili"):
        by_name("inesistente")


def test_composizione_per_parametri() -> None:
    """Evita di scrivere uno scenario per ogni combinazione."""
    composto = NOMINAL.with_channel(drop_after=2.0).with_behaviour(failure_rate=0.9)

    assert composto.channel.drop_after == 2.0
    assert composto.behaviour.failure_rate == 0.9
    assert NOMINAL.channel.drop_after is None  # l'originale non è toccato


def test_serializzazione(tmp_path) -> None:
    percorso = tmp_path / "s.json"
    by_name("rete-instabile").save(percorso)
    riletto = Scenario.load(percorso)

    assert riletto.name == "rete-instabile"
    assert riletto.channel.jitter == by_name("rete-instabile").channel.jitter


def test_campi_sconosciuti_ignorati() -> None:
    """Uno scenario scritto per una versione più recente resta caricabile."""
    dati = {**NOMINAL.to_dict(), "funzione_del_futuro": True}
    assert Scenario.from_dict(dati).name == "nominale"


# --------------------------------------------------------------------------- #
# Determinismo
# --------------------------------------------------------------------------- #


async def test_stesso_seme_stessa_sessione() -> None:
    """È ciò che rende uno scenario una prova ripetibile invece di un aneddoto."""
    prima = await _run(_fast(NOMINAL), until=MessageType.CHAT_DONE)
    seconda = await _run(_fast(NOMINAL), until=MessageType.CHAT_DONE)

    assert [e.type for e in prima] == [e.type for e in seconda]


async def test_semi_diversi_sessioni_diverse() -> None:
    """Il confronto e' sugli strumenti scelti, non sulla forma della sequenza:
    due piani diversi possono avere la stessa successione di tipi."""

    async def strumenti(seme: int) -> list[str]:
        ricevuti = await _run(
            _fast(replace(NOMINAL, seed=seme)), until=MessageType.CHAT_DONE
        )
        return [
            e.payload["tool"] for e in ricevuti if e.type == MissionType.ACTION_QUEUED
        ]

    assert await strumenti(1) != await strumenti(99)


# --------------------------------------------------------------------------- #
# Comportamento
# --------------------------------------------------------------------------- #


async def test_missione_completa() -> None:
    ricevuti = await _run(_fast(NOMINAL), until=MessageType.CHAT_DONE)
    tipi = [e.type for e in ricevuti]

    for atteso in (
        MessageType.SESSION_WELCOME,
        MissionType.TOOL_REGISTRY,
        MissionType.MISSION_STARTED,
        MissionType.ACTION_QUEUED,
        MissionType.ACTION_FINISHED,
        MissionType.MISSION_FINISHED,
    ):
        assert atteso in tipi, f"manca {atteso}"


async def test_audio_su_stream_generici() -> None:
    ricevuti = await _run(_fast(NOMINAL), until=MessageType.STREAM_CLOSE)
    apertura = next(e for e in ricevuti if e.type == MessageType.STREAM_OPEN)

    assert apertura.payload["kind"] == "audio"
    assert apertura.payload["related_id"] == "m1"


async def test_scenario_minimale_non_emette_missioni() -> None:
    ricevuti = await _run(_fast(by_name("minimale")), until=MessageType.CHAT_DONE)
    assert MissionType.MISSION_STARTED not in [e.type for e in ricevuti]


async def test_scenario_task_legacy() -> None:
    """La forma semplice deve restare supportata."""
    ricevuti = await _run(_fast(by_name("task-legacy")), until=MessageType.CHAT_DONE)
    assert MessageType.TASK_UPDATE in [e.type for e in ricevuti]


async def test_la_simulazione_reagisce_alle_conferme() -> None:
    """È la differenza rispetto al replay: qui la risposta cambia il seguito."""
    scenario = _fast(
        by_name("conferme-distruttive"),
        confirm_probability=1.0,
        confirm_timeout_s=3.0,
        actions_min=2,
        actions_max=2,
    )
    transport = SimTransport(scenario)
    await transport.connect()
    await transport.send(Envelope.make(MessageType.SESSION_HELLO).to_wire())
    await transport.send(
        Envelope.make(MessageType.CHAT_SEND, {"text": "x", "message_id": "m1"}).to_wire()
    )

    esiti: list[str] = []

    async def pump() -> None:
        async for messaggio in transport.receive():
            busta = Envelope.from_wire(messaggio)
            if busta.type == MissionType.ACTION_CONFIRM_REQUEST:
                await transport.send(
                    Envelope.make(
                        MissionType.ACTION_CONFIRM_REPLY,
                        {"request_id": busta.payload["request_id"], "approved": False},
                    ).to_wire()
                )
            elif busta.type == MissionType.ACTION_FINISHED:
                esiti.append(busta.payload["status"])
            elif busta.type == MissionType.MISSION_FINISHED:
                return

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(pump(), 25)
    await transport.close()

    assert "denied" in esiti


async def test_annullamento_interrompe_l_azione() -> None:
    scenario = _fast(NOMINAL, step_delay=0.05)
    transport = SimTransport(scenario)
    await transport.connect()
    await transport.send(Envelope.make(MessageType.SESSION_HELLO).to_wire())
    await transport.send(
        Envelope.make(MessageType.CHAT_SEND, {"text": "x", "message_id": "m1"}).to_wire()
    )

    esiti: list[str] = []

    async def pump() -> None:
        async for messaggio in transport.receive():
            busta = Envelope.from_wire(messaggio)
            if busta.type == MissionType.ACTION_STARTED:
                await transport.send(
                    Envelope.make(
                        MissionType.ACTION_CANCEL, {"action_id": busta.payload["action_id"]}
                    ).to_wire()
                )
            elif busta.type == MissionType.ACTION_FINISHED:
                esiti.append(busta.payload["status"])
            elif busta.type == MissionType.MISSION_FINISHED:
                return

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(pump(), 25)
    await transport.close()

    assert "cancelled" in esiti


# --------------------------------------------------------------------------- #
# Guasti del canale
# --------------------------------------------------------------------------- #


async def test_connessione_rifiutata_e_un_errore_di_trasporto() -> None:
    """Un guasto simulato deve essere indistinguibile da uno reale."""
    with pytest.raises(TransportError):
        await SimTransport(by_name("irraggiungibile")).connect()


async def test_handshake_omesso() -> None:
    ricevuti = await _run(
        _fast(by_name("muto")),
        until=MessageType.SESSION_WELCOME,
        timeout=0.5,
        chat=False,
    )
    assert ricevuti == []


async def test_autenticazione_rifiutata() -> None:
    ricevuti = await _run(
        _fast(by_name("autenticazione-richiesta")),
        until=MessageType.SESSION_DENIED,
        timeout=2.0,
        chat=False,
    )
    assert ricevuti[-1].type == MessageType.SESSION_DENIED
    assert ricevuti[-1].payload["retryable"] is False


async def test_protocollo_incompatibile_dichiarato() -> None:
    ricevuti = await _run(
        _fast(by_name("protocollo-incompatibile")),
        until=MessageType.SESSION_WELCOME,
        timeout=2.0,
        chat=False,
    )
    assert ricevuti[-1].payload["protocol"]["major"] != PROTOCOL_VERSION.major


async def test_messaggi_malformati_non_interrompono() -> None:
    scenario = _fast(by_name("rumoroso"), emit_audio=False)
    ricevuti = await _run(scenario, until=MessageType.CHAT_DONE)
    assert any("__malformato__" in e.payload for e in ricevuti)
    assert ricevuti[-1].type == MessageType.CHAT_DONE  # la sessione è arrivata in fondo


# --------------------------------------------------------------------------- #
# Conformità
# --------------------------------------------------------------------------- #


async def test_lo_scenario_nominale_e_conforme() -> None:
    """Il simulatore è il riferimento eseguibile della specifica: se non fosse
    conforme lui, la suite non varrebbe nulla."""
    scenario = _fast(NOMINAL, emit_audio=False, emit_missions=False)
    report = await run_conformance(lambda: SimTransport(scenario), timeout=3.0)

    assert report.conforms, report.as_text()


async def test_il_backend_muto_fallisce_l_handshake() -> None:
    report = await run_conformance(
        lambda: SimTransport(_fast(by_name("muto"))), timeout=0.25
    )

    handshake = next(r for r in report.results if r.id == "handshake")
    assert handshake.outcome is Outcome.FAIL
    assert not report.conforms


async def test_ogni_controllo_e_indipendente() -> None:
    """Sapere quante cose sono rotte vale più che sapere quale si è rotta prima."""
    report = await run_conformance(
        lambda: SimTransport(_fast(by_name("muto"))), timeout=0.25
    )
    assert len(report.results) == 6  # tutti eseguiti, nessuno interrotto a catena
