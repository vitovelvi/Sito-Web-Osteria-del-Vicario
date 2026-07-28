"""Test del Mission Engine e del livello operativo.

La proprietà centrale sotto verifica è una sola: **il motore non decide nulla**.
Registra ciò che il backend dichiara e, quando il canale cade, ammette di non
sapere invece di inventare un esito.
"""

from __future__ import annotations

import time

import pytest
from jarvis_protocol.missions import ActionStatus, MissionStatus, MissionType, RiskLevel

from core.events import EventType
from core.missions import MissionEngine


@pytest.fixture
def engine(bus):
    return MissionEngine(bus)


class _Sender:
    """Mittente finto: registra ciò che il motore prova a inviare."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, dict]] = []

    def send(self, message_type: str, payload: dict | None = None) -> bool:
        self.sent.append((message_type, payload or {}))
        return self.ok


def _mission(engine: MissionEngine, mission_id: str = "m1") -> None:
    engine.apply(
        MissionType.MISSION_STARTED, {"mission_id": mission_id, "title": "Verifica sistemi"}
    )


def _action(engine: MissionEngine, action_id: str = "a1", **extra) -> None:
    payload = {
        "action_id": action_id,
        "tool": "fs.read_file",
        "title": "Legge un file",
        "mission_id": "m1",
    }
    payload.update(extra)
    engine.apply(MissionType.ACTION_QUEUED, payload)


# --------------------------------------------------------------------------- #
# Missioni
# --------------------------------------------------------------------------- #


def test_missione_avviata_e_conclusa(engine: MissionEngine) -> None:
    _mission(engine)
    assert len(engine.active_missions()) == 1

    engine.apply(
        MissionType.MISSION_FINISHED, {"mission_id": "m1", "status": "completed"}
    )

    assert engine.active_missions() == ()
    assert engine.mission_history()[0].status is MissionStatus.COMPLETED


def test_stato_sconosciuto_ricade_sul_default(engine: MissionEngine) -> None:
    """Un backend più recente può inventare stati: si ricade, non si esplode."""
    _mission(engine)
    engine.apply(MissionType.MISSION_FINISHED, {"mission_id": "m1", "status": "trasfigurata"})
    assert engine.mission_history()[0].status is MissionStatus.COMPLETED


def test_messaggio_per_missione_inesistente_ignorato(engine: MissionEngine) -> None:
    engine.apply(MissionType.MISSION_UPDATED, {"mission_id": "mai-vista", "progress": 0.5})
    assert engine.active_missions() == ()


def test_avanzamento_dichiarato_vince_su_quello_dedotto(engine: MissionEngine) -> None:
    """Una stima non deve mai coprire un dato reale."""
    _mission(engine)
    _action(engine, "a1")
    _action(engine, "a2")
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "ok"})

    attive = {a.action_id: a for a in engine.active_actions()}
    mission = engine.active_missions()[0]
    # a1 conclusa, a2 ancora attiva: meta' del lavoro.
    assert mission.derived_progress(attive) == pytest.approx(0.5)

    engine.apply(MissionType.MISSION_UPDATED, {"mission_id": "m1", "progress": 0.9})
    mission = engine.active_missions()[0]
    assert mission.derived_progress(attive) == pytest.approx(0.9)


def test_avanzamento_dedotto_non_scende_quando_un_azione_finisce(engine: MissionEngine) -> None:
    """Il conteggio si basa sull'assenza dalle attive, non sulla presenza.

    Cercare le concluse fra le attive le farebbe sparire dal denominatore, e
    l'avanzamento *scenderebbe* a ogni azione completata.
    """
    _mission(engine)
    _action(engine, "a1")
    _action(engine, "a2")

    letture = []
    for action_id in ("a1", "a2"):
        engine.apply(MissionType.ACTION_FINISHED, {"action_id": action_id, "status": "ok"})
        attive = {a.action_id: a for a in engine.active_actions()}
        letture.append(engine.active_missions()[0].derived_progress(attive))

    assert letture == [pytest.approx(0.5), pytest.approx(1.0)]


def test_evento_dichiara_se_l_avanzamento_e_dedotto(engine: MissionEngine, collected) -> None:
    _mission(engine)
    eventi = [e for e in collected if e.type is EventType.MISSION_CHANGED]
    assert eventi[-1].payload.progress_is_derived is True


# --------------------------------------------------------------------------- #
# Azioni
# --------------------------------------------------------------------------- #


def test_ciclo_completo_di_un_azione(engine: MissionEngine) -> None:
    _mission(engine)
    _action(engine)
    assert engine.active_actions()[0].status is ActionStatus.QUEUED

    engine.apply(MissionType.ACTION_STARTED, {"action_id": "a1"})
    assert engine.active_actions()[0].status is ActionStatus.RUNNING

    engine.apply(
        MissionType.ACTION_FINISHED,
        {"action_id": "a1", "status": "ok", "duration_ms": 120.0},
    )
    assert engine.active_actions() == ()
    assert engine.action_history()[0].succeeded


def test_azione_in_coda_non_ha_durata(engine: MissionEngine) -> None:
    _action(engine)
    assert engine.active_actions()[0].wall_duration_ms is None


def test_attesa_in_coda_misurata(engine: MissionEngine) -> None:
    """Attesa e durata si correggono in modi opposti: vanno misurate separate."""
    _action(engine)
    time.sleep(0.02)
    engine.apply(MissionType.ACTION_STARTED, {"action_id": "a1"})

    attesa = engine.active_actions()[0].queue_wait_ms
    assert attesa is not None and attesa >= 15


def test_azione_registrata_sullo_strumento(engine: MissionEngine) -> None:
    _action(engine)
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "error"})

    tool = next(t for t in engine.tools() if t.name == "fs.read_file")
    assert tool.invocations == 1
    assert tool.failed == 1
    assert tool.success_rate == 0.0


def test_azioni_di_una_missione_recuperabili(engine: MissionEngine) -> None:
    _mission(engine)
    _action(engine, "a1")
    _action(engine, "a2")
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "ok"})

    assert {a.action_id for a in engine.actions_of("m1")} == {"a1", "a2"}


# --------------------------------------------------------------------------- #
# Conferme
# --------------------------------------------------------------------------- #


def test_conferma_mette_l_azione_in_attesa(engine: MissionEngine, collected) -> None:
    _action(engine, "a1", risk="destructive")
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {"request_id": "c1", "action_id": "a1", "title": "Autorizzi?", "risk": "destructive"},
    )

    assert engine.active_actions()[0].status is ActionStatus.WAITING_CONFIRMATION
    assert engine.pending_confirmations()[0].risk is RiskLevel.DESTRUCTIVE
    assert [e for e in collected if e.type is EventType.CONFIRM_REQUESTED]


def test_risposta_inoltrata_al_backend(engine: MissionEngine) -> None:
    """È l'unica decisione che viaggia verso il backend."""
    sender = _Sender()
    engine.attach_sender(sender)
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {"request_id": "c1", "action_id": "a1", "title": "Autorizzi?"},
    )

    assert engine.resolve_confirmation("c1", approved=True, remember=True)

    tipo, payload = sender.sent[-1]
    assert tipo == MissionType.ACTION_CONFIRM_REPLY
    assert payload["approved"] is True
    assert payload["remember"] is True


def test_risposta_non_inviata_avvisa_l_utente(engine: MissionEngine, collected) -> None:
    """Non deve restare convinto di aver autorizzato qualcosa."""
    engine.attach_sender(_Sender(ok=False))
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {"request_id": "c1", "action_id": "a1", "title": "Autorizzi?"},
    )

    assert engine.resolve_confirmation("c1", approved=True) is False
    notifiche = [e for e in collected if e.type is EventType.NOTIFICATION_REQUESTED]
    assert notifiche and notifiche[-1].payload.kind == "error"


def test_seconda_risposta_ignorata(engine: MissionEngine) -> None:
    sender = _Sender()
    engine.attach_sender(sender)
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {"request_id": "c1", "action_id": "a1", "title": "Autorizzi?"},
    )

    engine.resolve_confirmation("c1", approved=True)
    assert engine.resolve_confirmation("c1", approved=False) is False
    assert len(sender.sent) == 1


def test_conferma_scaduta_ritirata(engine: MissionEngine, collected) -> None:
    """Una conferma per un'operazione già abbandonata invita a un gesto inutile."""
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {
            "request_id": "c1",
            "action_id": "a1",
            "title": "Autorizzi?",
            "expires_in_s": 0.01,
        },
    )
    time.sleep(0.05)

    assert engine.sweep_expired_confirmations() == 1
    assert engine.pending_confirmations() == ()
    assert [e for e in collected if e.type is EventType.CONFIRM_RESOLVED]


# --------------------------------------------------------------------------- #
# Strumenti
# --------------------------------------------------------------------------- #


def test_registro_strumenti(engine: MissionEngine) -> None:
    engine.apply(
        MissionType.TOOL_REGISTRY,
        {
            "tools": [
                {"name": "shell.run", "title": "Comando", "risk": "destructive"},
                {"name": "web.search", "title": "Ricerca"},
            ]
        },
    )
    per_nome = {t.name: t for t in engine.tools()}

    assert per_nome["shell.run"].risk is RiskLevel.DESTRUCTIVE
    assert per_nome["shell.run"].declared
    assert per_nome["web.search"].risk is RiskLevel.LOW


def test_strumento_usato_ma_non_dichiarato(engine: MissionEngine) -> None:
    """O il registro è incompleto, o il backend fa cose non annunciate.

    In entrambi i casi va visto, non accorpato in silenzio.
    """
    _action(engine, "a1", tool="misterioso.strumento")

    tool = next(t for t in engine.tools() if t.name == "misterioso.strumento")
    assert not tool.declared


def test_statistiche_sopravvivono_al_nuovo_registro(engine: MissionEngine) -> None:
    """Descrivono la sessione, non il backend: cancellarle renderebbe la
    dashboard inutile proprio dopo una riconnessione."""
    _action(engine, "a1")
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "ok"})

    engine.apply(MissionType.TOOL_REGISTRY, {"tools": [{"name": "altro"}], "replace": True})

    tool = next(t for t in engine.tools() if t.name == "fs.read_file")
    assert tool.invocations == 1
    assert not tool.declared  # non è più nel registro, ma le misure restano


# --------------------------------------------------------------------------- #
# Caduta del canale
# --------------------------------------------------------------------------- #


def test_caduta_rende_ignote_le_operazioni_attive(engine: MissionEngine) -> None:
    """Non è una deduzione sull'esito: è l'ammissione di non conoscerlo.

    Marcarle fallite sarebbe inventare; lasciarle in corso sarebbe mentire.
    """
    _mission(engine)
    _action(engine, "a1")
    engine.apply(MissionType.ACTION_STARTED, {"action_id": "a1"})

    engine.on_link_lost()

    assert engine.active_missions() == ()
    assert engine.active_actions() == ()
    assert engine.mission_history()[0].status is MissionStatus.UNKNOWN
    assert engine.action_history()[0].status is ActionStatus.UNKNOWN


def test_azioni_ignote_escluse_dal_tasso_di_successo(engine: MissionEngine) -> None:
    """Contarle come fallite falserebbe la metrica per colpa della rete."""
    _action(engine, "a1")
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "ok"})
    _action(engine, "a2")
    engine.on_link_lost()

    metriche = engine.metrics()
    assert metriche.actions_completed == 1
    assert metriche.success_rate == 1.0


def test_conferme_pendenti_ritirate_alla_caduta(engine: MissionEngine) -> None:
    engine.apply(
        MissionType.ACTION_CONFIRM_REQUEST,
        {"request_id": "c1", "action_id": "a1", "title": "Autorizzi?"},
    )
    engine.on_link_lost()
    assert engine.pending_confirmations() == ()


# --------------------------------------------------------------------------- #
# Metriche
# --------------------------------------------------------------------------- #


def test_metriche_di_base(engine: MissionEngine) -> None:
    _mission(engine)
    for i in range(4):
        _action(engine, f"a{i}")
    engine.apply(MissionType.ACTION_STARTED, {"action_id": "a0"})
    engine.apply(
        MissionType.ACTION_FINISHED,
        {"action_id": "a0", "status": "ok", "duration_ms": 100.0},
    )

    m = engine.metrics()
    assert m.missions_active == 1
    assert m.queue_depth == 3
    assert m.actions_completed == 1
    assert m.success_rate == 1.0


def test_p95_riflette_le_code_lente(engine: MissionEngine) -> None:
    """La media da sola nasconde proprio il caso che rende un assistente
    frustrante da usare."""
    for i in range(20):
        durata = 2000.0 if i == 19 else 50.0
        _action(engine, f"a{i}")
        engine.apply(
            MissionType.ACTION_FINISHED,
            {"action_id": f"a{i}", "status": "ok", "duration_ms": durata},
        )

    m = engine.metrics()
    assert m.avg_duration_ms is not None and m.avg_duration_ms < 200
    assert m.p95_duration_ms == 2000.0


def test_metriche_pubblicate_sul_bus(engine: MissionEngine, collected) -> None:
    _action(engine)
    engine.apply(MissionType.ACTION_FINISHED, {"action_id": "a1", "status": "ok"})
    assert [e for e in collected if e.type is EventType.OPERATIONS_METRICS]


def test_payload_malformato_non_solleva(engine: MissionEngine) -> None:
    engine.apply(MissionType.ACTION_QUEUED, {"manca": "tutto"})
    engine.apply(MissionType.MISSION_STARTED, {})
    assert engine.active_actions() == ()
