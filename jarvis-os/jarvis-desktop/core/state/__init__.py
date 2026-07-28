"""Stato globale di J.A.R.V.I.S.: tre macchine ortogonali e la loro risoluzione."""

from core.state.machines import AgentState, AppState, LinkState, VisualMode
from core.state.manager import StateManager
from core.state.resolver import StateSnapshot, resolve_visual_mode, transition_duration

__all__ = [
    "AgentState",
    "AppState",
    "LinkState",
    "StateManager",
    "StateSnapshot",
    "VisualMode",
    "resolve_visual_mode",
    "transition_duration",
]
