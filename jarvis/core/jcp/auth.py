"""Credenziali per l'handshake JCP.

Il segreto **non sta nella configurazione né nel codice**: vive nel keyring
dell'OS e viene letto all'avvio. Il file ``.env`` è accettato come ripiego di
sviluppo, con avviso esplicito, perché un segreto in chiaro sul disco resta un
segreto in chiaro sul disco.

Nota onesta sul modello di minaccia: con un backend su ``localhost``,
l'autenticazione non protegge dalla rete ma da **altri processi locali** che
potrebbero connettersi alla stessa porta. Su una macchina personale a utente
singolo è una protezione modesta; diventa necessaria appena il backend ascolta
su un'interfaccia non locale. Per questo lo schema è configurabile e ``none``
resta il default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from core.logging_setup import LogCategory, get_logger

__all__ = ["AuthScheme", "Credentials", "load_credentials"]

_log = get_logger(LogCategory.PROTOCOL, "auth")

#: Servizio e voce nel keyring dell'OS.
_KEYRING_SERVICE = "jarvis-desktop"
_KEYRING_ENTRY = "backend-token"

#: Variabile d'ambiente di ripiego, per lo sviluppo.
_ENV_VAR = "JARVIS_BACKEND_TOKEN"


class AuthScheme(StrEnum):
    """Schemi previsti dalla specifica."""

    NONE = "none"
    """Backend locale in ambiente fidato. Default."""

    TOKEN = "token"
    """Segreto condiviso, inviato nell'handshake."""

    CHALLENGE = "challenge"
    """Riservato: il server invia un nonce, il client risponde con un HMAC.
    Definito ora per non doverlo infilare a forza in una versione futura."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """Credenziali da presentare nell'handshake."""

    scheme: AuthScheme = AuthScheme.NONE
    token: str | None = None
    source: str = "nessuna"
    """Provenienza del segreto, per la diagnostica. Mai il segreto stesso."""

    def to_payload(self) -> dict[str, str]:
        """Campo ``auth`` del messaggio ``session.hello``."""
        if self.scheme is AuthScheme.NONE or not self.token:
            return {"scheme": AuthScheme.NONE.value}
        return {"scheme": self.scheme.value, "token": self.token}

    def describe(self) -> str:
        """Descrizione priva di segreti, adatta a log e Developer Console."""
        if self.scheme is AuthScheme.NONE:
            return "nessuna autenticazione"
        return f"{self.scheme.value} (da {self.source})"


def load_credentials(scheme: str = AuthScheme.NONE.value) -> Credentials:
    """Carica le credenziali per lo schema richiesto.

    Ordine di ricerca: keyring dell'OS, poi variabile d'ambiente. Se lo schema
    richiede un segreto e non se ne trova uno, si ricade su ``none`` **con un
    avviso**: è preferibile un handshake rifiutato con un messaggio chiaro a un
    tentativo con un token vuoto, che produrrebbe un errore generico.
    """
    try:
        resolved = AuthScheme(scheme)
    except ValueError:
        _log.warning("Schema di autenticazione sconosciuto '%s': si usa 'none'", scheme)
        return Credentials()

    if resolved is AuthScheme.NONE:
        return Credentials()

    if resolved is AuthScheme.CHALLENGE:
        _log.warning("Schema 'challenge' non ancora implementato: si usa 'none'")
        return Credentials()

    token = _from_keyring()
    if token:
        return Credentials(scheme=resolved, token=token, source="keyring")

    token = os.environ.get(_ENV_VAR)
    if token:
        _log.warning(
            "Token letto dall'ambiente: in produzione va conservato nel keyring dell'OS"
        )
        return Credentials(scheme=resolved, token=token, source="ambiente")

    _log.error(
        "Schema '%s' richiesto ma nessun token disponibile (né keyring né %s): "
        "la sessione partirà senza autenticazione e il backend potrebbe rifiutarla",
        resolved.value,
        _ENV_VAR,
    )
    return Credentials()


def _from_keyring() -> str | None:
    """Legge il token dal keyring, se la libreria è disponibile."""
    try:
        import keyring
    except ImportError:
        _log.debug("Pacchetto 'keyring' non installato: si prova l'ambiente")
        return None

    try:
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_ENTRY)
    except Exception as exc:
        # Su Linux senza Secret Service, o con la sessione bloccata, la lettura
        # fallisce: non è un guasto dell'applicazione.
        _log.warning("Keyring non accessibile (%s): si prova l'ambiente", exc)
        return None


def store_token(token: str) -> bool:
    """Salva il token nel keyring dell'OS.

    Esposta per uno strumento di configurazione: non viene mai chiamata durante
    il normale funzionamento, perché la GUI legge le credenziali e non le
    scrive.
    """
    try:
        import keyring

        keyring.set_password(_KEYRING_SERVICE, _KEYRING_ENTRY, token)
    except Exception as exc:
        _log.error("Token non salvato nel keyring: %s", exc)
        return False
    _log.info("Token salvato nel keyring dell'OS")
    return True
