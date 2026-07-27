"""Test delle tre macchine a stati e della risoluzione visiva.

Sono i test che giustificano la divergenza dal brief (docs §2.3): verificano
proprio i casi che un enum unico non saprebbe rappresentare.
"""

from __future__ import annotations

import time

from core.errors import ErrorCondition, ErrorSeverity
from core.eventbus import EventBus
from core.events import EventType
from core.state import AgentState, AppState, LinkState, StateManager, VisualMode
from core.state.resolver import StateSnapshot, resolve_visual_mode, transition_duration
from core.state.transitions import AGENT_TRANSITIONS, is_allowed


def test_transizione_valida(state: StateManager) -> None:
    assert state.set_app_state(AppState.RUNNING)
    assert state.app_state is AppState.RUNNING


def test_transizione_illegale_rifiutata_senza_eccezione(
    state: StateManager, collected: list
) -> None:
    """Un backend che sbaglia non deve poter chiudere l'interfaccia."""
    state.set_app_state(AppState.RUNNING)
    state.set_app_state(AppState.SHUTTING_DOWN)

    assert state.set_app_state(AppState.RUNNING) is False
    assert state.app_state is AppState.SHUTTING_DOWN
    assert any(e.type is EventType.STATE_TRANSITION_REJECTED for e in collected)


def test_stesso_stato_non_genera_rumore(state: StateManager, collected: list) -> None:
    """Un backend che ribadisce lo stato corrente non deve riempire il log."""
    state.set_app_state(AppState.RUNNING)
    prima = len(collected)
    assert state.set_app_state(AppState.RUNNING) is False
    assert len(collected) == prima


def test_idle_raggiungibile_da_ogni_stato() -> None:
    """Senza questa proprieta' la GUI puo' restare bloccata in un'animazione."""
    for stato in AgentState:
        assert is_allowed(AGENT_TRANSITIONS, stato, AgentState.IDLE)


def test_assi_indipendenti(state: StateManager) -> None:
    """La caduta del canale non cancella cosa stava facendo l'assistente.

    E' il difetto che l'enum unico del brief avrebbe introdotto.
    """
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)
    state.set_agent_state(AgentState.SPEAKING)

    state.set_link_state(LinkState.OFFLINE)

    assert state.agent_state is AgentState.SPEAKING  # informazione conservata
    assert state.visual_mode is VisualMode.OFFLINE  # ma non la si mostra come attiva


def test_errore_non_cancella_lo_stato_dell_assistente(state: StateManager) -> None:
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)
    state.set_agent_state(AgentState.SPEAKING)

    state.raise_error(ErrorCondition(source="audio", message="dispositivo assente"))
    assert state.visual_mode is VisualMode.ERROR
    assert state.agent_state is AgentState.SPEAKING

    state.clear_error("audio")
    assert state.visual_mode is VisualMode.SPEAKING  # si torna dove si era


def test_errore_di_gravita_bassa_non_diventa_modalita_errore(state: StateManager) -> None:
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    state.raise_error(
        ErrorCondition(source="vision", message="webcam assente", severity=ErrorSeverity.WARNING)
    )

    assert state.visual_mode is VisualMode.IDLE


def test_una_condizione_per_sorgente(state: StateManager) -> None:
    """Un servizio che fallisce di continuo aggiorna la sua condizione, non ne accumula."""
    for i in range(5):
        state.raise_error(ErrorCondition(source="network", message=f"tentativo {i}"))
    assert len(state.active_errors()) == 1


def test_condizione_scaduta_ignorata() -> None:
    scaduta = ErrorCondition(
        source="audio", message="temporaneo", expires_at=time.monotonic() - 1.0
    )
    snapshot = StateSnapshot(
        app=AppState.RUNNING, link=LinkState.ONLINE, agent=AgentState.IDLE, error=scaduta
    )
    assert resolve_visual_mode(snapshot) is VisualMode.IDLE


def test_precedenza_errore_critico_sul_boot() -> None:
    """Un guasto grave va visto subito, non dopo la sequenza di avvio."""
    critico = ErrorCondition(
        source="core", message="guasto", severity=ErrorSeverity.CRITICAL
    )
    snapshot = StateSnapshot(app=AppState.BOOTING, error=critico)
    assert resolve_visual_mode(snapshot) is VisualMode.ERROR


def test_standby_prevale_sulla_riconnessione() -> None:
    """Se ho messo Jarvis a riposo non voglio vederlo agitarsi per la rete."""
    snapshot = StateSnapshot(app=AppState.STANDBY, link=LinkState.CONNECTING)
    assert resolve_visual_mode(snapshot) is VisualMode.STANDBY


def test_canale_degradato_mostra_comunque_l_assistente() -> None:
    """Lento non e' assente: si continua a mostrare cosa sta facendo."""
    snapshot = StateSnapshot(
        app=AppState.RUNNING, link=LinkState.DEGRADED, agent=AgentState.THINKING
    )
    assert resolve_visual_mode(snapshot) is VisualMode.THINKING


def test_stato_anticipato_riconciliato(state: StateManager, qt_app) -> None:
    """Se il backend non conferma entro il timeout, si torna indietro.

    E' la regola che impedisce a GUI e backend di divergere.
    """
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    state.set_agent_state(AgentState.LISTENING, authoritative=False, reconcile_ms=30)
    assert state.agent_state is AgentState.LISTENING

    deadline = time.monotonic() + 2.0
    while state.agent_state is AgentState.LISTENING and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)

    assert state.agent_state is AgentState.IDLE


def test_conferma_del_backend_annulla_la_riconciliazione(
    state: StateManager, qt_app
) -> None:
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    state.set_agent_state(AgentState.LISTENING, authoritative=False, reconcile_ms=40)
    state.set_agent_state(AgentState.LISTENING, authoritative=True)

    for _ in range(20):
        qt_app.processEvents()
        time.sleep(0.005)

    assert state.agent_state is AgentState.LISTENING


def test_evento_modalita_visiva_porta_la_durata(state: StateManager, collected: list) -> None:
    """La dissolvenza fra stati e' un dato del modello, non una scelta del widget."""
    state.set_app_state(AppState.RUNNING)
    eventi = [e for e in collected if e.type is EventType.VISUAL_MODE_CHANGED]
    assert eventi
    assert eventi[-1].payload.transition_ms > 0


def test_durata_transizione_asimmetrica() -> None:
    """L'errore deve arrivare addosso; il ritorno a riposo puo' respirare."""
    verso_errore = transition_duration(VisualMode.SPEAKING, VisualMode.ERROR)
    verso_riposo = transition_duration(VisualMode.SPEAKING, VisualMode.IDLE)
    assert verso_errore < verso_riposo
    assert transition_duration(VisualMode.IDLE, VisualMode.IDLE) == 0


def test_flash_success(state: StateManager) -> None:
    state.set_app_state(AppState.RUNNING)
    state.set_link_state(LinkState.CONNECTING)
    state.set_link_state(LinkState.ONLINE)

    state.flash_success(duration=5.0)
    assert state.visual_mode is VisualMode.SUCCESS


def test_link_state_pubblica_payload_di_canale(bus: EventBus, state: StateManager) -> None:
    """Chi ascolta il canale ha bisogno di endpoint e motivo, non di una transizione generica."""
    ricevuti: list = []
    bus.subscribe(EventType.LINK_STATE_CHANGED, ricevuti.append)

    state.set_link_state(LinkState.CONNECTING, reason="avvio")

    assert ricevuti[-1].payload.state == "connecting"
    assert ricevuti[-1].payload.reason == "avvio"
