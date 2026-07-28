"""Livello operativo: missioni, azioni, conferme, strumenti.

Proiezione degli eventi JCP, non un secondo cervello: il motore registra cio'
che il backend dichiara e non decide nulla. Vedi la nota in cima a
:mod:`core.missions.engine`.
"""

from core.missions.engine import MissionEngine
from core.missions.models import Action, ConfirmRequest, Mission, ToolInfo

__all__ = ["Action", "ConfirmRequest", "Mission", "MissionEngine", "ToolInfo"]
