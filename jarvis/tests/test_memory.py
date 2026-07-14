"""Test del Memory System."""

import tempfile
import unittest
from pathlib import Path

from jarvis.memory.backends import InMemoryBackend, JsonFileBackend, SQLiteBackend
from jarvis.memory.base import MemoryBackend
from jarvis.memory.stores import PreferenceMemory, SemanticMemory, WorkingMemory


class BackendContractTest(unittest.TestCase):
    """Ogni backend deve rispettare lo stesso contratto."""

    def backends(self) -> list[MemoryBackend]:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        return [
            InMemoryBackend(),
            JsonFileBackend(base / "json"),
            SQLiteBackend(base / "db" / "memory.db"),
        ]

    def test_add_query_delete(self) -> None:
        for backend in self.backends():
            with self.subTest(backend=type(backend).__name__):
                store = SemanticMemory(backend)
                record = store.remember({"fact": "il cielo è blu"},
                                        tags=["colore"], importance=0.9)
                self.assertEqual(store.count(), 1)
                hits = store.recall(tags=["colore"])
                self.assertEqual(hits[0].record_id, record.record_id)
                hits = store.recall(text="cielo")
                self.assertEqual(len(hits), 1)
                self.assertEqual(store.recall(text="inesistente"), [])
                self.assertTrue(store.forget(record.record_id))
                self.assertEqual(store.count(), 0)

    def test_prune_keeps_important(self) -> None:
        for backend in self.backends():
            with self.subTest(backend=type(backend).__name__):
                store = SemanticMemory(backend, max_records=100)
                low = store.remember({"v": "scartabile"}, importance=0.1)
                high = store.remember({"v": "prezioso"}, importance=0.9)
                removed = backend.prune(store.store_name, 1)
                self.assertEqual(removed, 1)
                self.assertIsNone(backend.get(store.store_name, low.record_id))
                self.assertIsNotNone(backend.get(store.store_name, high.record_id))


class JsonPersistenceTest(unittest.TestCase):
    def test_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = JsonFileBackend(Path(tmp))
            SemanticMemory(first).remember({"fact": "persistente"})
            second = JsonFileBackend(Path(tmp))
            self.assertEqual(second.count("semantic"), 1)


class StoreSemanticsTest(unittest.TestCase):
    def test_working_memory_capacity(self) -> None:
        store = WorkingMemory(InMemoryBackend(), capacity=3, ttl_seconds=60)
        for i in range(5):
            store.remember({"n": i})
        self.assertLessEqual(store.count(), 3)

    def test_preferences_overwrite(self) -> None:
        prefs = PreferenceMemory(InMemoryBackend())
        prefs.set_preference("report", "sintetico")
        prefs.set_preference("report", "dettagliato")
        self.assertEqual(prefs.get_preference("report"), "dettagliato")
        self.assertEqual(prefs.get_preference("assente", "default"), "default")
        self.assertEqual(prefs.count(), 1)


if __name__ == "__main__":
    unittest.main()
