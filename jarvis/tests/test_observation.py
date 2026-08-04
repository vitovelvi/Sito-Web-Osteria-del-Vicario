"""Test dell'Observation System, con attenzione alla portabilità.

Le sonde di sistema girano su piattaforme diverse: qui si verifica che il
percorso di fallback non sollevi MAI un'eccezione, in particolare su Windows
dove ``os.getloadavg`` non esiste e le API native possono fallire.
"""

import unittest
from unittest import mock

from jarvis.observation import system as sysmod


class LoadAverageTest(unittest.TestCase):
    def test_missing_getloadavg_returns_zero(self) -> None:
        """Su Windows ``os.getloadavg`` è assente: niente AttributeError."""
        with mock.patch.object(sysmod, "os") as fake_os:
            fake_os.cpu_count.return_value = 4
            del fake_os.getloadavg  # simula l'assenza dell'attributo
            self.assertEqual(sysmod._load_average(), 0.0)

    def test_oserror_returns_zero(self) -> None:
        with mock.patch("os.getloadavg", side_effect=OSError):
            self.assertEqual(sysmod._load_average(), 0.0)


class WindowsFallbackTest(unittest.TestCase):
    """Il ramo Windows non è eseguibile qui: se ne verifica l'isolamento."""

    def test_cpu_fallback_survives_probe_failure(self) -> None:
        with mock.patch.object(sysmod, "_IS_WINDOWS", True), \
             mock.patch.object(sysmod, "_cpu_percent_windows",
                               side_effect=OSError("API non disponibile")):
            cpu = sysmod._cpu_fallback()
        self.assertEqual(cpu["percent"], 0.0)
        self.assertGreaterEqual(cpu["cores"], 1.0)

    def test_memory_fallback_survives_probe_failure(self) -> None:
        with mock.patch.object(sysmod, "_IS_WINDOWS", True), \
             mock.patch.object(sysmod, "_memory_windows",
                               side_effect=OSError("API non disponibile")):
            memory = sysmod._memory_fallback()
        self.assertEqual(memory, {"total_mb": 0.0, "available_mb": 0.0,
                                  "percent": 0.0})

    def test_windows_probes_are_used_when_available(self) -> None:
        with mock.patch.object(sysmod, "_IS_WINDOWS", True), \
             mock.patch.object(sysmod, "_cpu_percent_windows", return_value=42.0), \
             mock.patch.object(sysmod, "_memory_windows",
                               return_value={"total_mb": 16000.0,
                                             "available_mb": 8000.0,
                                             "percent": 50.0}):
            self.assertEqual(sysmod._cpu_fallback()["percent"], 42.0)
            self.assertEqual(sysmod._memory_fallback()["percent"], 50.0)
            self.assertIsNone(sysmod._process_count_fallback())


class CollectMetricsTest(unittest.TestCase):
    def test_shape_is_stable_without_psutil(self) -> None:
        with mock.patch.object(sysmod, "psutil", None):
            metrics = sysmod.collect_system_metrics()
        self.assertTrue(metrics["degraded"])
        for key in ("cpu", "memory", "processes", "process_count"):
            self.assertIn(key, metrics)
        self.assertIn("percent", metrics["cpu"])
        self.assertIn("percent", metrics["memory"])

    def test_never_raises_on_hostile_platform(self) -> None:
        """Nessuna sonda disponibile: metriche neutre, nessuna eccezione."""
        with mock.patch.object(sysmod, "psutil", None), \
             mock.patch.object(sysmod, "_IS_WINDOWS", True), \
             mock.patch.object(sysmod, "_cpu_percent_windows",
                               side_effect=RuntimeError("boom")), \
             mock.patch.object(sysmod, "_memory_windows",
                               side_effect=RuntimeError("boom")):
            metrics = sysmod.collect_system_metrics()
        self.assertEqual(metrics["cpu"]["percent"], 0.0)
        self.assertEqual(metrics["memory"]["percent"], 0.0)


class ObserverTest(unittest.IsolatedAsyncioTestCase):
    async def test_emits_metrics_and_alerts(self) -> None:
        from jarvis.events import EventBus

        observer = sysmod.SystemObserver(EventBus(), cpu_alert_percent=0.0,
                                         memory_alert_percent=101.0)
        events = await observer.observe()
        topics = [e.topic for e in events]
        self.assertIn("system.metrics", topics)
        self.assertIn("system.alert.cpu", topics)       # soglia 0% → sempre
        self.assertNotIn("system.alert.memory", topics)  # soglia 101% → mai
        self.assertTrue(observer.last_metrics)


if __name__ == "__main__":
    unittest.main()
