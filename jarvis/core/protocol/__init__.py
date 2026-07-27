"""Contratto di comunicazione con OpenClaw: busta, tipi, capability.

Questo pacchetto definisce il **dialetto canonico interno**. Il trasporto
(:mod:`network.transport`) lo spedisce, l'adapter (:mod:`network.adapters`) lo
traduce nel dialetto reale del backend. Nessun altro modulo dell'applicazione
conosce il formato dei messaggi.
"""

from core.protocol.capabilities import CLIENT_CAPABILITIES, Capability
from core.protocol.envelope import (
    MIN_SUPPORTED_VERSION,
    PROTOCOL_VERSION,
    Envelope,
    new_message_id,
)
from core.protocol.messages import MessageType, parse_payload

__all__ = [
    "CLIENT_CAPABILITIES",
    "MIN_SUPPORTED_VERSION",
    "PROTOCOL_VERSION",
    "Capability",
    "Envelope",
    "MessageType",
    "new_message_id",
    "parse_payload",
]
