"""Risoluzione delle tre macchine a stati in un'unica modalita' visiva.

Separare gli assi (docs §2.3) ha un costo: qualcuno deve decidere cosa mostrare
quando dicono cose diverse — connessione in caduta *mentre* l'assistente parla,
errore *durante* il boot. Se quella decisione vive nei widget, in due anni ogni
pannello ha la propria idea di precedenza e l'interfaccia diventa incoerente.

Vive quindi qui, in un unico punto, come **tabella di precedenza dichiarata**.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Final

from core.errors import ErrorCondition, ErrorSeverity
from core.state.machines import AgentState, AppState, LinkState, VisualMode

__all__ = ["StateSnapshot", "resolve_visual_mode", "transition_duration"]


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """Fotografia coerente dei tre assi piu' le condizioni sovrapposte.

    Immutabile: i consumatori ne ricevono una copia e non possono alterare lo
    stato altrui.
    """

    app: AppState = AppState.BOOTING
    link: LinkState = LinkState.OFFLINE
    agent: AgentState = AgentState.IDLE
    error: ErrorCondition | None = None
    #: Istante (monotonic) fino al quale mostrare il lampo di conferma.
    success_until: float = 0.0

    def with_error(self, condition: ErrorCondition | None) -> StateSnapshot:
        """Copia con una diversa condizione d'errore."""
        return replace(self, error=condition)

    @property
    def is_link_healthy(self) -> bool:
        """Vero quando il canale e' utilizzabile, anche se lento."""
        return self.link in (LinkState.ONLINE, LinkState.DEGRADED)


#: Corrispondenza diretta fra stato dell'assistente e modalita' visiva. Esiste
#: solo per l'ultimo livello di precedenza, quando nessuna condizione prevale.
_AGENT_TO_VISUAL: Final[dict[AgentState, VisualMode]] = {
    AgentState.IDLE: VisualMode.IDLE,
    AgentState.LISTENING: VisualMode.LISTENING,
    AgentState.THINKING: VisualMode.THINKING,
    AgentState.EXECUTING: VisualMode.EXECUTING,
    AgentState.SPEAKING: VisualMode.SPEAKING,
}


def resolve_visual_mode(snapshot: StateSnapshot, now: float | None = None) -> VisualMode:
    """Riduce lo stato globale a una singola modalita' visiva.

    Ordine di precedenza, dal piu' forte al piu' debole:

    1. **Chiusura** — durante lo spegnimento non interessa altro.
    2. **Errore critico** — prevale anche sul boot: un guasto grave va visto
       subito, non dopo la sequenza di avvio.
    3. **Boot** — finche' i servizi non sono pronti non c'e' nulla di reale da
       riflettere.
    4. **Standby** — sospensione volontaria dell'utente, che ha priorita' sui
       fatti di rete: se ho messo Jarvis a riposo non voglio vederlo agitarsi
       per una riconnessione.
    5. **Errore non critico**.
    6. **Lampo di conferma** — transitorio, breve.
    7. **Canale non utilizzabile** — offline o in connessione: senza backend,
       lo stato dell'assistente e' informazione vecchia e mostrarla mentirebbe.
    8. **Stato dell'assistente** — il caso normale.

    ``DEGRADED`` non compare: un canale lento resta utilizzabile, quindi si
    continua a mostrare l'assistente. La degradazione viene segnalata dall'HUD,
    non dal nucleo.
    """
    now = time.monotonic() if now is None else now

    if snapshot.app is AppState.SHUTTING_DOWN:
        return VisualMode.STANDBY

    error = snapshot.error
    if error is not None and not error.is_expired(now):
        if error.severity >= ErrorSeverity.CRITICAL:
            return VisualMode.ERROR
    else:
        error = None

    if snapshot.app is AppState.BOOTING:
        return VisualMode.BOOT

    if snapshot.app is AppState.STANDBY:
        return VisualMode.STANDBY

    if error is not None and error.severity >= ErrorSeverity.ERROR:
        return VisualMode.ERROR

    if now < snapshot.success_until:
        return VisualMode.SUCCESS

    if snapshot.link is LinkState.OFFLINE:
        return VisualMode.OFFLINE
    if snapshot.link is LinkState.CONNECTING:
        return VisualMode.CONNECTING

    return _AGENT_TO_VISUAL[snapshot.agent]


#: Durate di dissolvenza fra modalita', in millisecondi.
#:
#: Il brief assegnava un'animazione a ogni stato ma non diceva nulla su cosa
#: accade *fra* due stati. Senza dissolvenza il passaggio e' uno scatto, ed e'
#: la differenza percepita fra un'interfaccia cinematografica e una demo.
_DEFAULT_TRANSITION_MS: Final[int] = 320

_TRANSITION_OVERRIDES: Final[dict[tuple[VisualMode, VisualMode], int]] = {
    # L'errore deve arrivare addosso: nessuna eleganza, e' un allarme.
    (VisualMode.IDLE, VisualMode.ERROR): 120,
    (VisualMode.THINKING, VisualMode.ERROR): 120,
    (VisualMode.EXECUTING, VisualMode.ERROR): 120,
    (VisualMode.SPEAKING, VisualMode.ERROR): 120,
    (VisualMode.LISTENING, VisualMode.ERROR): 120,
    # L'ascolto deve sembrare istantaneo: e' la risposta a un gesto dell'utente,
    # e ogni millisecondo percepito qui e' latenza attribuita a Jarvis.
    (VisualMode.IDLE, VisualMode.LISTENING): 160,
    # Il ritorno a riposo puo' permettersi di respirare.
    (VisualMode.SPEAKING, VisualMode.IDLE): 480,
    (VisualMode.SUCCESS, VisualMode.IDLE): 600,
    # Boot e standby sono cambi di scena, non di stato.
    (VisualMode.BOOT, VisualMode.CONNECTING): 700,
    (VisualMode.BOOT, VisualMode.IDLE): 700,
    (VisualMode.STANDBY, VisualMode.IDLE): 800,
    (VisualMode.IDLE, VisualMode.STANDBY): 800,
}


def transition_duration(previous: VisualMode, current: VisualMode) -> int:
    """Durata della dissolvenza fra due modalita', in millisecondi."""
    if previous is current:
        return 0
    return _TRANSITION_OVERRIDES.get((previous, current), _DEFAULT_TRANSITION_MS)
