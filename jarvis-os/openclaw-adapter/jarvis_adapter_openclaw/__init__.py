"""Adapter fra JCP e il dialetto di OpenClaw.

Pacchetto separato di proposito: dipende solo da ``jarvis-protocol``, non dalla
GUI. Chiunque scriva un client JCP può riusarlo, e il giorno in cui il
protocollo di OpenClaw cambia si aggiorna qui senza toccare l'interfaccia.
"""

from jarvis_adapter_openclaw.adapter import OpenClawAdapter

__all__ = ["OpenClawAdapter"]
