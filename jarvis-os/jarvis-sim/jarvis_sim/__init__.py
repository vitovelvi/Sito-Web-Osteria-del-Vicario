"""Ambiente di simulazione JCP.

**La simulazione reagisce, il replay riproduce.** Uno scenario risponde a ciò
che il client fa; una registrazione ripete una sequenza fissa. Sono strumenti
diversi e vanno scelti in base alla domanda: "l'interfaccia si comporta bene
quando il backend fa X?" è simulazione, "perché ieri è successo questo?" è
replay.

Il replay vive nell'SDK (:mod:`jarvis_sdk.recording`), perché non richiede
questo pacchetto.
"""

from jarvis_sim.library import ALL, by_name, names
from jarvis_sim.scenario import Behaviour, Channel, Scenario, ToolSpec
from jarvis_sim.transport import SimTransport, SimulationError

__version__ = "1.0.0"

__all__ = [
    "ALL",
    "Behaviour",
    "Channel",
    "Scenario",
    "SimTransport",
    "SimulationError",
    "ToolSpec",
    "__version__",
    "by_name",
    "names",
]
