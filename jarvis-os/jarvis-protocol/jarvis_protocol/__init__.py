"""JARVIS Communication Protocol (JCP) — versione 1.0.

Protocollo fra l'interfaccia desktop e un backend conversazionale, **definito
indipendentemente da qualunque backend**. OpenClaw è il primo a essere
collegato, tramite un adapter; se domani cambia, si scrive un altro adapter e
nient'altro dell'applicazione se ne accorge.

La specifica completa è in ``jarvis-docs/01-jcp-specifica.md``. Il backend simulato in
``network/mock/`` ne è il riferimento eseguibile.
"""

from jarvis_protocol.auth import AuthScheme, Credentials, load_credentials
from jarvis_protocol.capabilities import CLIENT_CAPABILITIES, Capability
from jarvis_protocol.envelope import Envelope, new_message_id
from jarvis_protocol.errors import (
    ErrorCode,
    ProtocolError,
    TransportError,
    is_retryable,
)
from jarvis_protocol.messages import (
    EXT_PREFIX,
    MessageType,
    is_extension,
    parse_payload,
)
from jarvis_protocol.missions import (
    ActionStatus,
    MissionStatus,
    MissionType,
    RiskLevel,
    coerce_status,
)
from jarvis_protocol.version import PROTOCOL_VERSION, ProtocolVersion

__all__ = [
    "CLIENT_CAPABILITIES",
    "EXT_PREFIX",
    "PROTOCOL_VERSION",
    "ActionStatus",
    "AuthScheme",
    "Capability",
    "Credentials",
    "Envelope",
    "ErrorCode",
    "MessageType",
    "MissionStatus",
    "MissionType",
    "ProtocolError",
    "ProtocolVersion",
    "RiskLevel",
    "TransportError",
    "coerce_status",
    "is_extension",
    "is_retryable",
    "load_credentials",
    "new_message_id",
    "parse_payload",
]
