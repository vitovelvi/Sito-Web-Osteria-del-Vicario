"""Server della dashboard: stdlib, zero dipendenze.

Espone:
    - ``GET /``           — interfaccia web (``index.html``);
    - ``GET /api/state``  — stato aggregato in JSON (polling dal frontend).

Lo stato è prodotto da una callable iniettata (il Kernel la fornisce), così
il server non conosce i sottosistemi: riceve solo dati già serializzabili.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from jarvis.logging import get_logger

_log = get_logger("dashboard")

StateProvider = Callable[[], dict[str, Any]]
_INDEX = Path(__file__).parent / "index.html"


class DashboardServer:
    """Server HTTP della dashboard, eseguito su thread dedicato."""

    def __init__(self, host: str, port: int, state_provider: StateProvider) -> None:
        self._host = host
        self._port = port
        self._provider = state_provider
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def running(self) -> bool:
        """Vero solo se il server ha davvero acquisito la porta."""
        return self._httpd is not None

    def start(self) -> bool:
        """Avvia il server.

        La dashboard è un accessorio: se la porta è occupata il sistema deve
        restare operativo. Ritorna ``False`` senza sollevare, così il Kernel
        prosegue il boot.
        """
        provider = self._provider

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - API stdlib
                if self.path == "/api/state":
                    try:
                        body = json.dumps(provider(), ensure_ascii=False,
                                          default=str).encode("utf-8")
                        self._send(200, "application/json", body)
                    except Exception as exc:  # noqa: BLE001
                        self._send(500, "application/json",
                                   json.dumps({"error": str(exc)}).encode())
                elif self.path in ("/", "/index.html"):
                    self._send(200, "text/html; charset=utf-8",
                               _INDEX.read_bytes())
                else:
                    self._send(404, "text/plain", b"not found")

            def _send(self, code: int, ctype: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # niente rumore sull'access log: c'è il logging strutturato

        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port), Handler)
        except OSError as exc:
            _log.error(
                "Dashboard non avviata su %s (%s). Il sistema resta operativo: "
                "liberare la porta o cambiare 'dashboard.port' in configurazione.",
                self.url, exc,
            )
            self._httpd = None
            return False

        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="dashboard", daemon=True
        )
        self._thread.start()
        _log.info("Dashboard attiva su %s", self.url)
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
