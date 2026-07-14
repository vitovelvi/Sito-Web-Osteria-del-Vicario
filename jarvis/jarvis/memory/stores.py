"""Store logici del Memory System.

Cinque memorie separate, ognuna con semantica propria:
    - :class:`WorkingMemory`     — contesto a breve termine, con capacità e TTL;
    - :class:`EpisodicMemory`    — cosa è successo (eventi, interazioni);
    - :class:`SemanticMemory`    — conoscenza consolidata (fatti);
    - :class:`PreferenceMemory`  — preferenze dell'utente;
    - :class:`OperationalLog`    — traccia operativa di piani, step ed errori.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jarvis.memory.base import MemoryBackend, MemoryRecord


class BaseStore:
    """Vista su uno store logico di un backend condiviso."""

    store_name: str = "base"

    def __init__(self, backend: MemoryBackend, max_records: int = 10000) -> None:
        self._backend = backend
        self._max_records = max_records

    def remember(
        self,
        content: dict[str, Any],
        *,
        tags: list[str] | None = None,
        importance: float = 0.5,
    ) -> MemoryRecord:
        """Registra un contenuto e applica la politica di ritenzione."""
        record = MemoryRecord(
            store=self.store_name,
            content=content,
            tags=tags or [],
            importance=max(0.0, min(1.0, importance)),
        )
        self._backend.add(record)
        self._backend.prune(self.store_name, self._max_records)
        return record

    def recall(
        self,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Recupera i record più recenti che soddisfano i criteri."""
        return self._backend.query(self.store_name, tags=tags, text=text, limit=limit)

    def forget(self, record_id: str) -> bool:
        """Elimina un record."""
        return self._backend.delete(self.store_name, record_id)

    def count(self) -> int:
        return self._backend.count(self.store_name)


class WorkingMemory(BaseStore):
    """Contesto a breve termine: capacità limitata e scadenza temporale."""

    store_name = "working"

    def __init__(
        self,
        backend: MemoryBackend,
        capacity: int = 64,
        ttl_seconds: float = 900.0,
    ) -> None:
        super().__init__(backend, max_records=capacity)
        self._ttl = timedelta(seconds=ttl_seconds)

    def recall(
        self,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Come la base, ma scarta (ed elimina) i record scaduti."""
        cutoff = datetime.now(tz=timezone.utc) - self._ttl
        fresh: list[MemoryRecord] = []
        for record in super().recall(tags=tags, text=text, limit=limit * 2):
            created = datetime.fromisoformat(record.created_at)
            if created >= cutoff:
                fresh.append(record)
            else:
                self.forget(record.record_id)
        return fresh[:limit]


class EpisodicMemory(BaseStore):
    """Memoria degli episodi: richieste, risposte, eventi salienti."""

    store_name = "episodic"


class SemanticMemory(BaseStore):
    """Conoscenza consolidata: fatti stabili sull'utente e sull'ambiente."""

    store_name = "semantic"


class PreferenceMemory(BaseStore):
    """Preferenze dell'utente (tono, orari, strumenti, abitudini)."""

    store_name = "preference"

    def set_preference(self, key: str, value: Any) -> MemoryRecord:
        """Imposta una preferenza con chiave stabile (sovrascrive la precedente)."""
        for old in self.recall(tags=[f"pref:{key}"], limit=10):
            self.forget(old.record_id)
        return self.remember(
            {"key": key, "value": value}, tags=[f"pref:{key}"], importance=0.8
        )

    def get_preference(self, key: str, default: Any = None) -> Any:
        hits = self.recall(tags=[f"pref:{key}"], limit=1)
        return hits[0].content.get("value", default) if hits else default


class OperationalLog(BaseStore):
    """Traccia operativa strutturata: piani, step, errori, decisioni."""

    store_name = "operational"

    def log(self, kind: str, detail: dict[str, Any], importance: float = 0.3) -> None:
        self.remember({"kind": kind, **detail}, tags=[f"op:{kind}"], importance=importance)
