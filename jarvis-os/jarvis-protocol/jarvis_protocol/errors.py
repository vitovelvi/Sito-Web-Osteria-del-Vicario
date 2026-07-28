"""Codici di errore JCP.

``retryable`` non è una cortesia informativa: distingue "riprova fra poco" da
"smetti e dillo all'utente". Insistere con un token sbagliato non lo rende
valido, riempie solo i log e ritarda il momento in cui l'utente capisce il
problema.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = ["ErrorCode", "ProtocolError", "is_retryable"]


class ProtocolError(Exception):
    """Messaggio non conforme al contratto (versione o schema).

    Vive qui e non nell'applicazione perche' e' parte del **contratto**: chi
    implementa un backend o un adapter deve poterla catturare senza dipendere
    dalla GUI.
    """


class ErrorCode(StrEnum):
    """Codici definiti da JCP 1.0."""

    PROTOCOL_UNSUPPORTED = "protocol.unsupported"
    PROTOCOL_MALFORMED = "protocol.malformed"
    AUTH_REQUIRED = "auth.required"
    AUTH_DENIED = "auth.denied"
    CAPABILITY_MISSING = "capability.missing"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


#: Codici per i quali insistere è inutile: la causa non cambia da sola.
_PERMANENT: Final[frozenset[str]] = frozenset(
    {
        ErrorCode.PROTOCOL_UNSUPPORTED.value,
        ErrorCode.AUTH_REQUIRED.value,
        ErrorCode.AUTH_DENIED.value,
        ErrorCode.CAPABILITY_MISSING.value,
    }
)


def is_retryable(code: str) -> bool:
    """Indica se ha senso riprovare dopo un errore con questo codice.

    I codici sconosciuti sono considerati ritentabili: è la scelta prudente,
    perché un backend più recente potrebbe introdurne di transitori.
    """
    return code not in _PERMANENT
