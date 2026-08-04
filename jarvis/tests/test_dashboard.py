"""Test della dashboard.

La dashboard è un accessorio: la sua indisponibilità non deve mai impedire
al sistema cognitivo di funzionare.
"""

import json
import socket
import unittest
import urllib.error
import urllib.request

from jarvis.dashboard import DashboardServer


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class DashboardServerTest(unittest.TestCase):
    def test_serves_state_and_page(self) -> None:
        port = _free_port()
        server = DashboardServer("127.0.0.1", port, lambda: {"stato": "ok"})
        self.assertTrue(server.start())
        self.addCleanup(server.stop)
        try:
            with urllib.request.urlopen(f"{server.url}/api/state", timeout=5) as res:
                self.assertEqual(json.loads(res.read())["stato"], "ok")
            with urllib.request.urlopen(f"{server.url}/", timeout=5) as res:
                self.assertIn(b"J.A.R.V.I.S.", res.read())
        finally:
            server.stop()

    def test_busy_port_degrades_without_raising(self) -> None:
        """Porta occupata: nessuna eccezione, solo 'running' a False."""
        port = _free_port()
        first = DashboardServer("127.0.0.1", port, dict)
        self.assertTrue(first.start())
        self.addCleanup(first.stop)

        second = DashboardServer("127.0.0.1", port, dict)
        self.assertFalse(second.start())
        self.assertFalse(second.running)
        second.stop()  # deve essere sicuro anche senza server attivo

    def test_state_provider_failure_returns_500(self) -> None:
        def broken() -> dict:
            raise RuntimeError("provider guasto")

        port = _free_port()
        server = DashboardServer("127.0.0.1", port, broken)
        self.assertTrue(server.start())
        self.addCleanup(server.stop)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{server.url}/api/state", timeout=5)
        self.assertEqual(ctx.exception.code, 500)


if __name__ == "__main__":
    unittest.main()
