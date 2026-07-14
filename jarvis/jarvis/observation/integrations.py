"""Integrazioni con servizi esterni: WordPress, WooCommerce, GA, Meta Ads.

Ogni integrazione è un osservatore che interroga il servizio e traduce le
novità in eventi (``integration.<servizio>.<evento>``). Le classi qui sotto
definiscono il contratto e il ciclo di polling; la chiamata HTTP specifica è
il SOLO punto da implementare quando si collega il servizio reale:

    class WordPressObserver(IntegrationObserver):
        async def poll(self) -> list[dict]:
            # GET {base_url}/wp-json/wp/v2/comments?after=...  → lista di novità
            ...

Le credenziali arrivano SEMPRE dall'ambiente, mai dalla configurazione.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from jarvis.config import Config
from jarvis.events import Event, EventBus
from jarvis.observation.base import Observer


class IntegrationObserver(Observer):
    """Base per osservatori di servizi esterni.

    Args:
        bus: event bus.
        service: nome del servizio (usato nei topic).
        config: sezione ``observation.integrations.<service>``.
    """

    def __init__(self, bus: EventBus, service: str, config: Config) -> None:
        self.name = f"integration.{service}"
        super().__init__(bus, float(config.get("poll_seconds", 300)))
        self.service = service
        self.enabled = bool(config.get("enabled", False))
        self.settings = config.as_dict()

    @abstractmethod
    async def poll(self) -> list[dict[str, Any]]:
        """Interroga il servizio e ritorna le novità (dizionari serializzabili).

        Implementazioni reali: chiamata HTTP autenticata + deduplica.
        """

    async def observe(self) -> list[Event]:
        if not self.enabled:
            return []
        return [
            Event(
                topic=f"integration.{self.service}.update",
                payload=item,
                source=self.name,
            )
            for item in await self.poll()
        ]


class WordPressObserver(IntegrationObserver):
    """Nuovi post, commenti e aggiornamenti da un sito WordPress.

    Da implementare con la REST API (``/wp-json/wp/v2/...``).
    """

    def __init__(self, bus: EventBus, config: Config) -> None:
        super().__init__(bus, "wordpress", config)

    async def poll(self) -> list[dict[str, Any]]:
        return []  # placeholder documentato: vedi docstring del modulo


class WooCommerceObserver(IntegrationObserver):
    """Nuovi ordini e variazioni di stock da WooCommerce (``/wp-json/wc/v3``)."""

    def __init__(self, bus: EventBus, config: Config) -> None:
        super().__init__(bus, "woocommerce", config)

    async def poll(self) -> list[dict[str, Any]]:
        return []  # placeholder documentato


class GoogleAnalyticsObserver(IntegrationObserver):
    """Metriche di traffico dalla GA4 Data API."""

    def __init__(self, bus: EventBus, config: Config) -> None:
        super().__init__(bus, "google_analytics", config)

    async def poll(self) -> list[dict[str, Any]]:
        return []  # placeholder documentato


class MetaAdsObserver(IntegrationObserver):
    """Spesa e performance campagne dalla Meta Marketing API."""

    def __init__(self, bus: EventBus, config: Config) -> None:
        super().__init__(bus, "meta_ads", config)

    async def poll(self) -> list[dict[str, Any]]:
        return []  # placeholder documentato


def build_integration_observers(bus: EventBus, config: Config) -> list[IntegrationObserver]:
    """Istanzia le integrazioni dichiarate in configurazione."""
    section = config.section("observation.integrations")
    return [
        WordPressObserver(bus, section.section("wordpress")),
        WooCommerceObserver(bus, section.section("woocommerce")),
        GoogleAnalyticsObserver(bus, section.section("google_analytics")),
        MetaAdsObserver(bus, section.section("meta_ads")),
    ]
