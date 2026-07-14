"""Contratti del sottosistema LLM.

Un :class:`LLMProvider` incapsula un modello (locale o remoto) e dichiara un
profilo (costo, velocità, qualità) che il router usa per la scelta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class Quality(str, Enum):
    """Qualità richiesta per una generazione."""

    FAST = "fast"          # risposta rapida, tolleranza a imprecisioni
    STANDARD = "standard"  # equilibrio qualità/costo
    BEST = "best"          # massima qualità disponibile


@dataclass(slots=True)
class LLMRequest:
    """Richiesta di generazione.

    Attributes:
        prompt: prompt utente/di sistema già composto dal chiamante.
        system: prompt di sistema (identità JARVIS).
        quality: qualità minima richiesta.
        max_tokens: limite di generazione.
        temperature: creatività della generazione.
        metadata: contesto libero per routing e telemetria.
    """

    prompt: str
    system: str = ""
    quality: Quality = Quality.STANDARD
    max_tokens: int = 1024
    temperature: float = 0.2
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    """Risposta di una generazione."""

    text: str
    provider: str
    model: str
    estimated_cost_usd: float = 0.0
    latency_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Profilo dichiarato da un provider, usato dal router per la scelta.

    Attributes:
        cost_per_1k_tokens_usd: costo stimato (0 per i modelli locali/gratuiti).
        speed: 0.0–1.0, più alto è più veloce.
        quality: 0.0–1.0, più alto è migliore.
        max_complexity: complessità massima (0.0–1.0) gestibile con
            qualità accettabile.
    """

    cost_per_1k_tokens_usd: float
    speed: float
    quality: float
    max_complexity: float


class ProviderUnavailable(Exception):
    """Il provider non è raggiungibile o non è configurato."""


class LLMProvider(ABC):
    """Interfaccia di un provider LLM."""

    name: str = "abstract"
    profile: ProviderProfile

    @abstractmethod
    async def is_available(self) -> bool:
        """Verifica rapida di raggiungibilità/configurazione."""

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Esegue la generazione.

        Raises:
            ProviderUnavailable: se il servizio non risponde.
        """
