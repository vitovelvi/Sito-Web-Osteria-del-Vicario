"""Tabelle delle transizioni consentite.

Le transizioni sono **dati, non codice sparso**: un'unica tabella per macchina,
leggibile in dieci secondi, verificabile con un test. Aggiungere uno stato in
futuro significa aggiungere una riga, non cercare gli ``if`` nell'interfaccia.

Una transizione non consentita **non solleva un'eccezione**: la GUI non deve mai
crashare per un messaggio inatteso del backend. Viene rifiutata, loggata e
pubblicata come :data:`~core.events.EventType.STATE_TRANSITION_REJECTED`, cosi'
diventa visibile nel pannello Log senza fermare nulla. In sviluppo la si puo'
alzare a errore per scoprire i bug di protocollo (``strict=True``).
"""

from __future__ import annotations

from typing import Final, TypeVar

from core.state.machines import AgentState, AppState, LinkState

__all__ = ["AGENT_TRANSITIONS", "APP_TRANSITIONS", "LINK_TRANSITIONS", "is_allowed"]

StateT = TypeVar("StateT")

#: Il ciclo di vita e' sostanzialmente lineare. Si ammette ``STANDBY`` ⇄
#: ``RUNNING`` perche' la sospensione e' reversibile; da qualunque stato si puo'
#: andare in chiusura.
APP_TRANSITIONS: Final[dict[AppState, frozenset[AppState]]] = {
    AppState.BOOTING: frozenset({AppState.RUNNING, AppState.SHUTTING_DOWN}),
    AppState.RUNNING: frozenset({AppState.STANDBY, AppState.SHUTTING_DOWN}),
    AppState.STANDBY: frozenset({AppState.RUNNING, AppState.SHUTTING_DOWN}),
    AppState.SHUTTING_DOWN: frozenset(),
}

#: La connessione e' ciclica: si puo' sempre ricadere in ``CONNECTING`` perche'
#: la riconnessione automatica e' la norma, non l'eccezione.
LINK_TRANSITIONS: Final[dict[LinkState, frozenset[LinkState]]] = {
    LinkState.OFFLINE: frozenset({LinkState.CONNECTING}),
    LinkState.CONNECTING: frozenset(
        {LinkState.ONLINE, LinkState.OFFLINE, LinkState.CONNECTING}
    ),
    LinkState.ONLINE: frozenset(
        {LinkState.DEGRADED, LinkState.OFFLINE, LinkState.CONNECTING}
    ),
    LinkState.DEGRADED: frozenset(
        {LinkState.ONLINE, LinkState.OFFLINE, LinkState.CONNECTING}
    ),
}

#: Il ciclo dell'assistente. ``IDLE`` e' raggiungibile da ovunque: un'interruzione
#: dell'utente o un errore del backend devono sempre poter riportare a riposo,
#: altrimenti la GUI resta bloccata in un'animazione che non finisce mai.
AGENT_TRANSITIONS: Final[dict[AgentState, frozenset[AgentState]]] = {
    AgentState.IDLE: frozenset(
        {AgentState.LISTENING, AgentState.THINKING, AgentState.EXECUTING, AgentState.SPEAKING}
    ),
    AgentState.LISTENING: frozenset({AgentState.THINKING, AgentState.IDLE}),
    AgentState.THINKING: frozenset(
        {AgentState.EXECUTING, AgentState.SPEAKING, AgentState.IDLE}
    ),
    AgentState.EXECUTING: frozenset(
        {AgentState.SPEAKING, AgentState.THINKING, AgentState.IDLE}
    ),
    AgentState.SPEAKING: frozenset(
        {AgentState.IDLE, AgentState.LISTENING, AgentState.THINKING}
    ),
}


def is_allowed(
    table: dict[StateT, frozenset[StateT]], current: StateT, target: StateT
) -> bool:
    """Verifica se una transizione e' ammessa.

    Restare nello stesso stato e' sempre lecito: un backend che ribadisce lo
    stato corrente non deve produrre rumore nel log.
    """
    if current == target:
        return True
    return target in table.get(current, frozenset())
