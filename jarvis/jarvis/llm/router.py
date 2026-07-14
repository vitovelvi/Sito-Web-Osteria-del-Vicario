"""LLM Router: sceglie automaticamente il modello migliore.

Criteri di scelta, in quest'ordine concettuale:
    1. il provider deve essere disponibile;
    2. deve reggere la complessità stimata della richiesta;
    3. deve soddisfare la qualità minima richiesta;
    4. tra i candidati vince il punteggio migliore su costo, velocità e
       preferenza per il locale.

Priorità di fatto: Ollama (locale) → modelli gratuiti → Claude API solo quando
la complessità o la qualità richiesta lo esigono.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from jarvis.config import Config
from jarvis.events import Event, EventBus
from jarvis.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderUnavailable,
    Quality,
)
from jarvis.llm.providers import (
    ClaudeProvider,
    FreeTierProvider,
    HeuristicProvider,
    OllamaProvider,
)
from jarvis.logging import get_logger

_log = get_logger("llm.router")

# Segnali lessicali di complessità: codice, analisi, pianificazione lunga.
_COMPLEX_HINTS = re.compile(
    r"\b(refactor|architett|analizza|progetta|implementa|debug|ottimizza|"
    r"confronta|dimostra|spiega in dettaglio|multi[- ]step)\b",
    re.IGNORECASE,
)

_QUALITY_FLOOR = {Quality.FAST: 0.0, Quality.STANDARD: 0.5, Quality.BEST: 0.85}


def estimate_complexity(request: LLMRequest) -> float:
    """Stima 0.0–1.0 della complessità di una richiesta.

    Combina lunghezza del prompt, segnali lessicali e presenza di codice.
    Volutamente semplice e deterministica: è un'euristica di routing, non
    una valutazione semantica.
    """
    text = request.prompt
    length_score = min(len(text) / 4000.0, 1.0) * 0.4
    hint_score = min(len(_COMPLEX_HINTS.findall(text)) * 0.15, 0.4)
    code_score = 0.2 if ("```" in text or "def " in text or "class " in text) else 0.0
    return round(min(length_score + hint_score + code_score, 1.0), 3)


@dataclass(slots=True)
class RoutingDecision:
    """Esito del routing, pubblicato sul bus per trasparenza."""

    provider: str
    complexity: float
    quality: str
    considered: list[str]


class LLMRouter:
    """Router intelligente tra provider LLM.

    Args:
        config: configurazione globale (sezione ``llm``).
        bus: event bus su cui pubblicare le decisioni di routing.
        providers: lista ordinata di provider; se ``None`` usa quelli standard.
    """

    def __init__(
        self,
        config: Config,
        bus: EventBus | None = None,
        providers: list[LLMProvider] | None = None,
    ) -> None:
        self._bus = bus
        self._prefer_local = bool(config.get("llm.routing.prefer_local", True))
        self._providers: list[LLMProvider] = providers if providers is not None else [
            OllamaProvider(config),
            FreeTierProvider(config),
            ClaudeProvider(config),
            HeuristicProvider(),
        ]
        self.last_decision: RoutingDecision | None = None

    # ------------------------------------------------------------- routing

    def _score(self, provider: LLMProvider, complexity: float) -> float:
        """Punteggio di preferenza: costo basso, velocità, margine di qualità."""
        p = provider.profile
        cost_score = 1.0 / (1.0 + p.cost_per_1k_tokens_usd * 100)
        local_bonus = 0.3 if (self._prefer_local and p.cost_per_1k_tokens_usd == 0) else 0.0
        headroom = max(p.max_complexity - complexity, 0.0)
        return cost_score * 0.4 + p.speed * 0.2 + headroom * 0.1 + local_bonus + p.quality * 0.1

    async def select(self, request: LLMRequest,
                     exclude: frozenset[str] = frozenset()) -> LLMProvider:
        """Sceglie il provider migliore per la richiesta.

        Args:
            request: richiesta da instradare.
            exclude: provider da scartare (già falliti in questo giro).
        """
        complexity = estimate_complexity(request)
        floor = _QUALITY_FLOOR[request.quality]
        candidates: list[tuple[float, LLMProvider]] = []
        considered: list[str] = []

        for provider in self._providers:
            if provider.name in exclude:
                continue
            if not await provider.is_available():
                continue
            considered.append(provider.name)
            profile = provider.profile
            if profile.max_complexity < complexity:
                continue
            if profile.quality < floor and provider.name != "heuristic":
                continue
            candidates.append((self._score(provider, complexity), provider))

        if not candidates:
            # Nessun candidato pieno: degrada al migliore disponibile per qualità.
            for provider in self._providers:
                if provider.name not in exclude and await provider.is_available():
                    candidates.append((provider.profile.quality, provider))
        if not candidates:
            raise ProviderUnavailable("Nessun provider LLM disponibile")

        # Il fallback euristico vince solo se è rimasto da solo.
        real = [c for c in candidates if c[1].name != "heuristic"]
        pool = real or candidates
        pool.sort(key=lambda item: item[0], reverse=True)
        chosen = pool[0][1]

        self.last_decision = RoutingDecision(
            provider=chosen.name,
            complexity=complexity,
            quality=request.quality.value,
            considered=considered,
        )
        if self._bus is not None:
            await self._bus.publish(Event(
                topic="llm.routing.decision",
                payload=asdict(self.last_decision),
                source="llm.router",
            ))
        return chosen

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Instrada e genera, con failover automatico sul provider successivo."""
        last_error: Exception | None = None
        tried: set[str] = set()
        while len(tried) < len(self._providers):
            try:
                provider = await self.select(request, exclude=frozenset(tried))
            except ProviderUnavailable as exc:
                last_error = exc
                break
            tried.add(provider.name)
            try:
                response = await provider.generate(request)
                _log.info("Generazione via %s (%.2fs)",
                          provider.name, response.latency_seconds)
                return response
            except ProviderUnavailable as exc:
                _log.warning("Provider %s non disponibile, failover: %s",
                             provider.name, exc)
                last_error = exc
        raise ProviderUnavailable(str(last_error or "routing esaurito"))

    async def snapshot(self) -> dict[str, object]:
        """Stato dei provider per la dashboard."""
        availability = {}
        for provider in self._providers:
            availability[provider.name] = await provider.is_available()
        return {
            "providers": availability,
            "last_decision": asdict(self.last_decision) if self.last_decision else None,
        }
