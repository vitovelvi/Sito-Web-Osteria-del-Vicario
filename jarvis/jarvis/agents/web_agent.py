"""WebAgent: accesso al web per gli altri componenti.

Serve richieste ``web.fetch`` (GET di pagine, Livello 0) pubblicando
``web.fetch.result``. Le fetch passano dalla stdlib con timeout e limite di
dimensione; nessun contenuto scaricato viene mai eseguito.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request

from jarvis.agents.base import BaseAgent
from jarvis.events import Event, EventBus

_MAX_BYTES = 512 * 1024
_TIMEOUT = 20.0
_ALLOWED_SCHEMES = ("http://", "https://")


def _fetch(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "JARVIS/0.1"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        body = response.read(_MAX_BYTES)
    return {
        "url": url,
        "status": getattr(response, "status", 200),
        "content": body.decode("utf-8", errors="replace"),
        "truncated": len(body) >= _MAX_BYTES,
    }


class WebAgent(BaseAgent):
    """Recupera contenuti web su richiesta di altri componenti."""

    name = "web"
    description = "Fetch HTTP controllati per ricerca e integrazioni"
    subscriptions = ("web.fetch",)

    def __init__(self, bus: EventBus) -> None:
        super().__init__(bus)

    async def handle(self, event: Event) -> None:
        url = str(event.payload.get("url", "")).strip()
        correlation = event.correlation_id or event.event_id
        if not url.startswith(_ALLOWED_SCHEMES):
            await self.emit("web.fetch.result",
                            {"url": url, "error": "schema URL non consentito"},
                            correlation)
            return
        try:
            result = await asyncio.to_thread(_fetch, url)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            result = {"url": url, "error": str(exc)}
        await self.emit("web.fetch.result", result, correlation)
