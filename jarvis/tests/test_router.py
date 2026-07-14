"""Test del LLM Router."""

import unittest

from jarvis.llm import LLMRequest, LLMRouter, Quality
from jarvis.llm.base import (
    LLMProvider,
    LLMResponse,
    ProviderProfile,
    ProviderUnavailable,
)
from jarvis.llm.providers import HeuristicProvider
from jarvis.llm.router import estimate_complexity
from tests.helpers import test_config


class FakeProvider(LLMProvider):
    def __init__(self, name: str, profile: ProviderProfile,
                 available: bool = True, fail: bool = False) -> None:
        self.name = name
        self.profile = profile
        self._available = available
        self._fail = fail
        self.calls = 0

    async def is_available(self) -> bool:
        return self._available

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self._fail:
            raise ProviderUnavailable(f"{self.name} giù")
        return LLMResponse(text=f"da {self.name}", provider=self.name, model="fake")


def local_profile() -> ProviderProfile:
    return ProviderProfile(cost_per_1k_tokens_usd=0.0, speed=0.6,
                           quality=0.6, max_complexity=0.7)


def cloud_profile() -> ProviderProfile:
    return ProviderProfile(cost_per_1k_tokens_usd=0.01, speed=0.7,
                           quality=0.95, max_complexity=1.0)


class ComplexityTest(unittest.TestCase):
    def test_simple_vs_complex(self) -> None:
        simple = estimate_complexity(LLMRequest(prompt="Che ore sono?"))
        complex_ = estimate_complexity(LLMRequest(
            prompt="Analizza e refactor questa architettura: " + "x" * 3000
                   + "\n```def f(): pass```"))
        self.assertLess(simple, 0.2)
        self.assertGreater(complex_, 0.6)


class RouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_local_for_simple_requests(self) -> None:
        local = FakeProvider("ollama", local_profile())
        cloud = FakeProvider("claude", cloud_profile())
        router = LLMRouter(test_config(), providers=[local, cloud])
        chosen = await router.select(LLMRequest(prompt="Ciao, come va?"))
        self.assertEqual(chosen.name, "ollama")

    async def test_high_quality_routes_to_cloud(self) -> None:
        local = FakeProvider("ollama", local_profile())
        cloud = FakeProvider("claude", cloud_profile())
        router = LLMRouter(test_config(), providers=[local, cloud])
        chosen = await router.select(
            LLMRequest(prompt="Progetta l'architettura", quality=Quality.BEST))
        self.assertEqual(chosen.name, "claude")

    async def test_complexity_beyond_local_routes_to_cloud(self) -> None:
        local = FakeProvider("ollama", local_profile())
        cloud = FakeProvider("claude", cloud_profile())
        router = LLMRouter(test_config(), providers=[local, cloud])
        request = LLMRequest(
            prompt="Analizza, refactor e ottimizza in dettaglio " + "y" * 4000
                   + "```class A: ...```")
        chosen = await router.select(request)
        self.assertEqual(chosen.name, "claude")

    async def test_failover_to_next_provider(self) -> None:
        broken = FakeProvider("ollama", local_profile(), fail=True)
        cloud = FakeProvider("claude", cloud_profile())
        router = LLMRouter(test_config(), providers=[broken, cloud])
        response = await router.generate(LLMRequest(prompt="ciao"))
        self.assertEqual(response.provider, "claude")

    async def test_heuristic_fallback_when_alone(self) -> None:
        offline = FakeProvider("ollama", local_profile(), available=False)
        router = LLMRouter(test_config(),
                           providers=[offline, HeuristicProvider()])
        response = await router.generate(LLMRequest(prompt="ciao"))
        self.assertEqual(response.provider, "heuristic")
        self.assertIn("euristica", response.text)


if __name__ == "__main__":
    unittest.main()
