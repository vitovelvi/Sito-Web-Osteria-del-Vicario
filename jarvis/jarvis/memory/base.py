"""Contratti del Memory System.

Ogni memoria (working, episodic, semantic, preference, operational) è uno store
logico su un :class:`MemoryBackend` sostituibile. Per cambiare persistenza è
sufficiente implementare il protocollo e registrare il backend nel manager.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass(slots=True)
class MemoryRecord:
    """Unità di memoria.

    Attributes:
        record_id: identificativo univoco.
        store: nome dello store logico di appartenenza.
        content: contenuto serializzabile in JSON.
        tags: etichette per il recupero.
        importance: rilevanza 0.0–1.0 (guida eviction e recall).
        created_at: istante di creazione (ISO-8601 UTC).
    """

    store: str
    content: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "store": self.store,
            "content": self.content,
            "tags": self.tags,
            "importance": self.importance,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(
            store=data["store"],
            content=data.get("content", {}),
            tags=list(data.get("tags", [])),
            importance=float(data.get("importance", 0.5)),
            record_id=data.get("record_id", uuid.uuid4().hex),
            created_at=data.get("created_at", _now_iso()),
        )


class MemoryBackend(ABC):
    """Backend di persistenza sostituibile.

    Implementazioni incluse: in-memory, JSON su file, SQLite.
    Backend futuri (Redis, vector store, ...) implementano questa interfaccia.
    """

    @abstractmethod
    def add(self, record: MemoryRecord) -> None:
        """Inserisce (o sovrascrive per ``record_id``) un record."""

    @abstractmethod
    def get(self, store: str, record_id: str) -> MemoryRecord | None:
        """Recupera un record per id, o ``None``."""

    @abstractmethod
    def query(
        self,
        store: str,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """Ricerca per tag (tutti richiesti) e/o testo nel contenuto.

        Ritorna i record più recenti per primi.
        """

    @abstractmethod
    def delete(self, store: str, record_id: str) -> bool:
        """Elimina un record; ``True`` se esisteva."""

    @abstractmethod
    def count(self, store: str) -> int:
        """Numero di record nello store."""

    @abstractmethod
    def prune(self, store: str, max_records: int) -> int:
        """Riduce lo store a ``max_records`` scartando i record meno
        importanti e più vecchi. Ritorna quanti sono stati rimossi."""

    def flush(self) -> None:  # noqa: B027 - opzionale per i backend volatili
        """Persiste su disco ciò che è in memoria (no-op se non serve)."""
