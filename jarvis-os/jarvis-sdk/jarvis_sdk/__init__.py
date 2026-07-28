"""SDK ufficiale di J.A.R.V.I.S.

Contiene ciò che serve per **estendere** la piattaforma senza dipendere
dall'interfaccia:

* :mod:`jarvis_sdk.adapter` — base per collegare un backend con un dialetto proprio;
* :mod:`jarvis_sdk.plugins` — contratto dei plugin, manifesto e validazione;
* :mod:`jarvis_sdk.recording` — registrazione e replay delle sessioni JCP;
* :mod:`jarvis_sdk.conformance` — verifica eseguibile della specifica;
* :mod:`jarvis_sdk.testing` — utilità per collaudare estensioni.

L'unica dipendenza è ``jarvis-protocol``. Chi scrive un plugin o un adapter non
deve installare Qt, audio o visione — che è la differenza fra una piattaforma
estendibile e un'applicazione con dei ganci.
"""

from jarvis_sdk.adapter import BaseAdapter
from jarvis_sdk.conformance import ConformanceReport, Outcome, run_conformance
from jarvis_sdk.plugins import (
    PLUGIN_API_VERSION,
    IPlugin,
    PluginContext,
    PluginManifest,
    discover,
    validate_manifest,
)
from jarvis_sdk.recording import (
    JCPL_VERSION,
    Recording,
    SessionRecorder,
    SessionReplayer,
)

__version__ = "1.0.0"

__all__ = [
    "JCPL_VERSION",
    "PLUGIN_API_VERSION",
    "BaseAdapter",
    "ConformanceReport",
    "IPlugin",
    "Outcome",
    "PluginContext",
    "PluginManifest",
    "Recording",
    "SessionRecorder",
    "SessionReplayer",
    "__version__",
    "discover",
    "run_conformance",
    "validate_manifest",
]
