"""Adapter identità, per i backend che parlano JCP nativamente.

Serve a due cose. La prima è pratica: un backend conforme non ha bisogno di
traduzione, e senza questo adapter il servizio di rete dovrebbe avere un ramo
"con adapter / senza adapter" — cioè due percorsi da mantenere e testare.

La seconda è didattica: mostra quanto poco un adapter deve fare. Se un adapter
concreto risulta molto più lungo di questo, vale la pena chiedersi se stia
traducendo o se abbia iniziato a decidere.
"""

from __future__ import annotations

from typing import Any

from jarvis_protocol.envelope import Envelope

from core.errors import ProtocolError
from core.logging_setup import LogCategory, get_logger

__all__ = ["NativeJcpAdapter"]

_log = get_logger(LogCategory.PROTOCOL, "adapter.native")


class NativeJcpAdapter:
    """Passa i messaggi senza modificarli."""

    @property
    def name(self) -> str:
        return "jcp-native"

    def to_backend(self, envelope: Envelope) -> list[dict[str, Any]]:
        return [envelope.to_wire()]

    def from_backend(self, raw: dict[str, Any]) -> list[Envelope]:
        try:
            return [Envelope.from_wire(raw)]
        except ProtocolError as exc:
            _log.warning("Messaggio scartato: %s", exc)
            return []

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "translates": False,
            "note": "Il backend parla JCP direttamente: nessuna traduzione.",
        }
