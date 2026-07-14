"""Backend di persistenza inclusi: in-memory, JSON su file, SQLite.

Tutti i backend sono thread-safe: gli osservatori e la dashboard girano su
thread separati dal loop asyncio.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from jarvis.memory.base import MemoryBackend, MemoryRecord


def _matches(record: MemoryRecord, tags: list[str] | None, text: str | None) -> bool:
    if tags and not set(tags).issubset(set(record.tags)):
        return False
    if text:
        haystack = json.dumps(record.content, ensure_ascii=False).lower()
        if text.lower() not in haystack:
            return False
    return True


def _prune_keys(records: dict[str, MemoryRecord], max_records: int) -> list[str]:
    """Chiavi da rimuovere: prima i meno importanti, a parità i più vecchi."""
    if len(records) <= max_records:
        return []
    ranked = sorted(records.values(), key=lambda r: (r.importance, r.created_at))
    return [r.record_id for r in ranked[: len(records) - max_records]]


class InMemoryBackend(MemoryBackend):
    """Backend volatile: rapido, adatto a test e working memory."""

    def __init__(self) -> None:
        self._stores: dict[str, dict[str, MemoryRecord]] = {}
        self._lock = threading.RLock()

    def _store(self, store: str) -> dict[str, MemoryRecord]:
        return self._stores.setdefault(store, {})

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            self._store(record.store)[record.record_id] = record

    def get(self, store: str, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._store(store).get(record_id)

    def query(
        self,
        store: str,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        with self._lock:
            hits = [r for r in self._store(store).values() if _matches(r, tags, text)]
        hits.sort(key=lambda r: r.created_at, reverse=True)
        return hits[:limit]

    def delete(self, store: str, record_id: str) -> bool:
        with self._lock:
            return self._store(store).pop(record_id, None) is not None

    def count(self, store: str) -> int:
        with self._lock:
            return len(self._store(store))

    def prune(self, store: str, max_records: int) -> int:
        with self._lock:
            records = self._store(store)
            doomed = _prune_keys(records, max_records)
            for key in doomed:
                del records[key]
            return len(doomed)


class JsonFileBackend(InMemoryBackend):
    """Backend JSON: un file per store, leggibile e ispezionabile.

    Adatto al prototipo e a volumi moderati; per volumi maggiori usare SQLite.
    """

    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    def _path(self, store: str) -> Path:
        return self._data_dir / f"{store}.json"

    def _load_all(self) -> None:
        for path in self._data_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue  # file corrotto: si riparte da vuoto, il flush lo riscrive
            for item in raw:
                record = MemoryRecord.from_dict(item)
                self._store(record.store)[record.record_id] = record

    def _persist(self, store: str) -> None:
        records = [r.to_dict() for r in self._store(store).values()]
        tmp = self._path(store).with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path(store))

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            super().add(record)
            self._persist(record.store)

    def delete(self, store: str, record_id: str) -> bool:
        with self._lock:
            existed = super().delete(store, record_id)
            if existed:
                self._persist(store)
            return existed

    def prune(self, store: str, max_records: int) -> int:
        with self._lock:
            removed = super().prune(store, max_records)
            if removed:
                self._persist(store)
            return removed

    def flush(self) -> None:
        with self._lock:
            for store in self._stores:
                self._persist(store)


class SQLiteBackend(MemoryBackend):
    """Backend SQLite: robusto, adatto a volumi elevati e query frequenti."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                record_id  TEXT PRIMARY KEY,
                store      TEXT NOT NULL,
                content    TEXT NOT NULL,
                tags       TEXT NOT NULL,
                importance REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_store ON memory(store, created_at)"
        )
        self._conn.commit()

    def _row_to_record(self, row: tuple) -> MemoryRecord:
        return MemoryRecord(
            record_id=row[0],
            store=row[1],
            content=json.loads(row[2]),
            tags=json.loads(row[3]),
            importance=row[4],
            created_at=row[5],
        )

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.record_id,
                    record.store,
                    json.dumps(record.content, ensure_ascii=False),
                    json.dumps(record.tags, ensure_ascii=False),
                    record.importance,
                    record.created_at,
                ),
            )
            self._conn.commit()

    def get(self, store: str, record_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory WHERE store = ? AND record_id = ?",
                (store, record_id),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def query(
        self,
        store: str,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE store = ? ORDER BY created_at DESC",
                (store,),
            ).fetchall()
        records = (self._row_to_record(r) for r in rows)
        hits = [r for r in records if _matches(r, tags, text)]
        return hits[:limit]

    def delete(self, store: str, record_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memory WHERE store = ? AND record_id = ?",
                (store, record_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def count(self, store: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM memory WHERE store = ?", (store,)
            ).fetchone()
        return int(row[0])

    def prune(self, store: str, max_records: int) -> int:
        with self._lock:
            excess = self.count(store) - max_records
            if excess <= 0:
                return 0
            cur = self._conn.execute(
                """
                DELETE FROM memory WHERE record_id IN (
                    SELECT record_id FROM memory WHERE store = ?
                    ORDER BY importance ASC, created_at ASC LIMIT ?
                )
                """,
                (store, excess),
            )
            self._conn.commit()
            return cur.rowcount

    def flush(self) -> None:
        with self._lock:
            self._conn.commit()
