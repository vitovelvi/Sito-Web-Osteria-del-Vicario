"""Envelope versionato dei messaggi scambiati con OpenClaw.

Il brief chiedeva che la GUI non conoscesse i dettagli del backend, ma non
definiva il **contratto**. Senza contratto scritto ogni modifica a OpenClaw
rompe l'interfaccia in silenzio, e il disaccoppiamento resta teorico.

Ogni messaggio, in entrambe le direzioni, ha la stessa busta::

    {"v": 1, "id": "01J...", "type": "chat.delta", "ts": 1730000000.1,
     "payload": {...}, "corr": "01J..."}

* ``v``   — versione del protocollo; consente di rifiutare o adattare.
* ``id``  — identificativo ordinabile del messaggio.
* ``corr``— id del messaggio a cui si risponde: e' cio' che permette
  ``send_and_wait`` senza che il chiamante gestisca la correlazione.

Un payload non conforme viene **scartato e loggato**, mai propagato: un backend
che sbaglia non deve poter chiudere l'interfaccia.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.errors import ProtocolError

__all__ = [
    "MIN_SUPPORTED_VERSION",
    "PROTOCOL_VERSION",
    "Envelope",
    "new_message_id",
]

#: Versione parlata da questa build della GUI.
PROTOCOL_VERSION: Final[int] = 1

#: Versione piu' vecchia con cui si accetta di dialogare. Tenere una finestra di
#: compatibilita' e' cio' che permette di aggiornare GUI e backend in momenti
#: diversi senza fermare tutto.
MIN_SUPPORTED_VERSION: Final[int] = 1

_ID_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_ID_RANDOM_BITS: Final[int] = 80
_ID_RANDOM_MASK: Final[int] = (1 << _ID_RANDOM_BITS) - 1

_id_lock = threading.Lock()
_id_last_ms = 0
_id_last_random = 0


def new_message_id() -> str:
    """Genera un identificativo ordinabile nel tempo, stile ULID monotono.

    L'ordinabilita' non e' un vezzo: leggendo un log di sessione, gli id
    ordinati alfabeticamente sono anche in ordine cronologico, il che rende
    ricostruibile una conversazione senza incrociare i timestamp.

    La parte casuale da sola non basta a garantirlo: due messaggi emessi nello
    stesso millisecondo — normale in uno stream token-per-token — otterrebbero
    un ordine arbitrario. Entro lo stesso millisecondo la componente casuale
    viene quindi **incrementata** invece che risorteggiata, come previsto dalla
    variante monotona di ULID.
    """
    global _id_last_ms, _id_last_random

    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms == _id_last_ms:
            _id_last_random = (_id_last_random + 1) & _ID_RANDOM_MASK
        else:
            # Il tempo puo' tornare indietro (correzione NTP): in quel caso si
            # resta sull'ultimo millisecondo noto per non rompere l'ordinamento.
            _id_last_ms = max(now_ms, _id_last_ms)
            _id_last_random = int.from_bytes(os.urandom(10), "big")
        value = (_id_last_ms << _ID_RANDOM_BITS) | _id_last_random

    chars: list[str] = []
    for _ in range(26):
        chars.append(_ID_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


class Envelope(BaseModel):
    """Busta comune a ogni messaggio del protocollo."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    v: int = Field(default=PROTOCOL_VERSION, description="Versione del protocollo")
    id: str = Field(default_factory=new_message_id)
    type: str = Field(min_length=1, description="Tipo puntato, es. 'chat.delta'")
    ts: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict)
    corr: str | None = Field(default=None, description="Id del messaggio correlato")

    # -- serializzazione -------------------------------------------------- #

    def to_json(self) -> str:
        """Serializza per l'invio sul trasporto."""
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_json(cls, raw: str | bytes) -> Envelope:
        """Deserializza e valida un messaggio in arrivo.

        :raises ProtocolError: se il testo non e' JSON valido, non e' un oggetto
            o non rispetta lo schema della busta. Il chiamante logga e scarta.
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError(f"Messaggio non decodificabile: {exc}") from exc

        if not isinstance(data, dict):
            raise ProtocolError(
                f"Messaggio di tipo {type(data).__name__}: atteso un oggetto JSON"
            )

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ProtocolError(f"Busta non conforme: {exc.error_count()} errori") from exc

    # -- compatibilita' di versione --------------------------------------- #

    @property
    def is_supported(self) -> bool:
        """Indica se la versione dichiarata rientra nella finestra supportata."""
        return MIN_SUPPORTED_VERSION <= self.v <= PROTOCOL_VERSION

    def reply(self, type_: str, payload: dict[str, Any] | None = None) -> Envelope:
        """Costruisce una risposta correlata a questo messaggio."""
        return Envelope(type=type_, payload=payload or {}, corr=self.id)
