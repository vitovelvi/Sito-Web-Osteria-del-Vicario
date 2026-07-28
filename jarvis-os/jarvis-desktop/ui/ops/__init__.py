"""Livello operativo dell'interfaccia.

Rappresenta cio' che il backend **sta facendo**: missioni, azioni, strumenti,
conferme, metriche. Tutti i pannelli sono alimentati esclusivamente dagli
eventi del bus prodotti dal Mission Engine, che a sua volta e' una proiezione
degli eventi JCP. Nessun pannello interroga il backend e nessuno deduce esiti.
"""

from ui.ops.action_queue import ActionQueue
from ui.ops.confirmations import ConfirmationLayer
from ui.ops.metrics_dashboard import MetricsDashboard
from ui.ops.mission_panel import MissionPanel
from ui.ops.sidebar import OperationsSidebar
from ui.ops.tool_inspector import ToolInspector

__all__ = [
    "ActionQueue",
    "ConfirmationLayer",
    "MetricsDashboard",
    "MissionPanel",
    "OperationsSidebar",
    "ToolInspector",
]
