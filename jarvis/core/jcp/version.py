"""Versione del protocollo e regole di compatibilità.

`major` cambia solo per modifiche incompatibili; `minor` cresce a ogni aggiunta.
La conseguenza pratica è la sola cosa che conta: **GUI e backend possono essere
aggiornati in momenti diversi**. Senza questa regola, ogni modifica al backend
imporrebbe di aggiornare l'interfaccia nello stesso istante, e viceversa — che
in un progetto destinato a durare anni è insostenibile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["PROTOCOL_VERSION", "ProtocolVersion"]


@dataclass(frozen=True, slots=True, order=True)
class ProtocolVersion:
    """Versione nella forma ``major.minor``."""

    major: int
    minor: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    @classmethod
    def parse(cls, raw: str | ProtocolVersion) -> ProtocolVersion:
        """Interpreta una versione testuale.

        :raises ValueError: se la forma non è ``major.minor`` con interi.
        """
        if isinstance(raw, ProtocolVersion):
            return raw
        try:
            major, _, minor = str(raw).partition(".")
            return cls(int(major), int(minor or 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Versione di protocollo non valida: {raw!r}") from exc

    def is_compatible_with(self, other: ProtocolVersion) -> bool:
        """Indica se due versioni possono dialogare.

        Basta che coincida ``major``: un ``minor`` diverso significa che uno dei
        due lati conosce messaggi o campi che l'altro ignora, il che è previsto
        e innocuo. Un ``major`` diverso significa che qualcosa è cambiato di
        significato, e allora indovinare è peggio che rifiutare.
        """
        return self.major == other.major

    def compare_minor(self, other: ProtocolVersion) -> int:
        """``-1`` se questa è più vecchia, ``0`` se pari, ``1`` se più recente."""
        return (self.minor > other.minor) - (self.minor < other.minor)


#: Versione parlata da questa build.
PROTOCOL_VERSION: Final[ProtocolVersion] = ProtocolVersion(1, 0)
