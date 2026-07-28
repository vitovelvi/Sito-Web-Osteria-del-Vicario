"""Busta JCP: la struttura comune a ogni messaggio.

I nomi dei campi sul filo sono brevi (``v``, ``t``, ``p``) mentre in Python
sono estesi (``version``, ``type``, ``payload``). Non è vezzo: la busta si
ripete su **ogni** frame di uno stream audio, dove il rapporto fra intestazione
e contenuto è misurabile; nel codice, invece, la leggibilità vale più di sei
caratteri.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jarvis_protocol.errors import ProtocolError
from jarvis_protocol.version import PROTOCOL_VERSION, ProtocolVersion

__all__ = ["Envelope", "new_message_id"]

_ID_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
_ID_RANDOM_BITS: Final[int] = 80
_ID_RANDOM_MASK: Final[int] = (1 << _ID_RANDOM_BITS) - 1

_id_lock = threading.Lock()
_id_last_ms = 0
_id_last_random = 0


def new_message_id() -> str:
    """Genera un identificativo ordinabile nel tempo, stile ULID monotono.

    L'ordinabilità non è un vezzo: in un log di sessione gli id ordinati
    alfabeticamente sono anche in ordine cronologico, il che rende
    ricostruibile una conversazione senza incrociare i timestamp.

    La parte casuale da sola non basta: due messaggi emessi nello stesso
    millisecondo — normale in uno stream token per token — otterrebbero un
    ordine arbitrario. Entro lo stesso millisecondo la componente casuale viene
    quindi incrementata invece che risorteggiata.
    """
    global _id_last_ms, _id_last_random

    with _id_lock:
        now_ms = int(time.time() * 1000)
        if now_ms == _id_last_ms:
            _id_last_random = (_id_last_random + 1) & _ID_RANDOM_MASK
        else:
            # Il tempo può tornare indietro (correzione NTP): in quel caso si
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
    """Busta comune a ogni messaggio JCP."""

    # ``populate_by_name`` consente di costruire con i nomi estesi e serializzare
    # con quelli brevi: il codice resta leggibile, il filo resta compatto.
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    version: str = Field(default=str(PROTOCOL_VERSION), alias="v")
    id: str = Field(default_factory=new_message_id)
    type: str = Field(alias="t", min_length=1)
    ts: float = Field(default_factory=time.time)
    payload: dict[str, Any] = Field(default_factory=dict, alias="p")
    corr: str | None = Field(default=None, alias="c")

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        ProtocolVersion.parse(value)  # solleva se malformata
        return value

    # -- versione ---------------------------------------------------------- #

    @property
    def protocol(self) -> ProtocolVersion:
        """Versione dichiarata dal mittente."""
        return ProtocolVersion.parse(self.version)

    @property
    def is_compatible(self) -> bool:
        """Vero se la versione dichiarata è dialogabile con questa build."""
        return self.protocol.is_compatible_with(PROTOCOL_VERSION)

    # -- serializzazione --------------------------------------------------- #

    def to_json(self) -> str:
        """Serializza per l'invio, con i nomi brevi."""
        return self.model_dump_json(by_alias=True, exclude_none=True)

    def to_wire(self) -> dict[str, Any]:
        """Rappresentazione a dizionario con i nomi brevi."""
        return self.model_dump(by_alias=True, exclude_none=True)

    @classmethod
    def from_json(cls, raw: str | bytes) -> Envelope:
        """Deserializza e valida un messaggio in arrivo.

        :raises ProtocolError: se il testo non è JSON valido, non è un oggetto o
            non rispetta lo schema. Il chiamante logga e scarta: un messaggio
            malformato non deve poter chiudere il canale.
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError(f"Messaggio non decodificabile: {exc}") from exc

        if not isinstance(data, dict):
            raise ProtocolError(
                f"Messaggio di tipo {type(data).__name__}: atteso un oggetto JSON"
            )
        return cls.from_wire(data)

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> Envelope:
        """Valida un messaggio già decodificato.

        Usata dagli adapter, che ricevono dizionari e non testo.
        """
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ProtocolError(f"Busta non conforme: {exc.error_count()} errori") from exc

    # -- costruzione ------------------------------------------------------- #

    @classmethod
    def make(
        cls, type_: str, payload: dict[str, Any] | None = None, *, corr: str | None = None
    ) -> Envelope:
        """Costruisce una busta con la versione di questa build."""
        return cls(t=type_, p=payload or {}, c=corr)

    def reply(self, type_: str, payload: dict[str, Any] | None = None) -> Envelope:
        """Costruisce una risposta correlata a questo messaggio."""
        return Envelope.make(type_, payload, corr=self.id)

    def __str__(self) -> str:  # pragma: no cover - diagnostica
        return f"{self.type}#{self.id[-6:]}"
