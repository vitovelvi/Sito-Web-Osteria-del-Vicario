"""JARVIS Communication Protocol (JCP) — versione 1.0.

Protocollo fra l'interfaccia desktop e un backend conversazionale, **definito
indipendentemente da qualunque backend**. OpenClaw è il primo a essere
collegato, tramite un adapter; se domani cambia, si scrive un altro adapter e
nient'altro dell'applicazione se ne accorge.

La specifica completa è in ``docs/01-jcp-specifica.md``. Il backend simulato in
``network/mock/`` ne è il riferimento eseguibile.
"""

from core.jcp.auth import AuthScheme, Credentials, load_credentials
from core.jcp.capabilities import CLIENT_CAPABILITIES, Capability
from core.jcp.envelope import Envelope, new_message_id
from core.jcp.errors import ErrorCode, is_retryable
from core.jcp.messages import EXT_PREFIX, MessageType, is_extension, parse_payload
from core.jcp.version import PROTOCOL_VERSION, ProtocolVersion

__all__ = [
    "CLIENT_CAPABILITIES",
    "EXT_PREFIX",
    "PROTOCOL_VERSION",
    "AuthScheme",
    "Capability",
    "Credentials",
    "Envelope",
    "ErrorCode",
    "MessageType",
    "ProtocolVersion",
    "is_extension",
    "is_retryable",
    "load_credentials",
    "new_message_id",
    "parse_payload",
]
