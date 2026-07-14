"""Provider LLM inclusi.

Ordine di preferenza del router (a parità di requisiti):
    1. :class:`OllamaProvider`   — modello locale, costo zero;
    2. :class:`FreeTierProvider` — endpoint gratuiti OpenAI-compatibili;
    3. :class:`ClaudeProvider`   — Claude API, solo quando serve qualità alta;
    4. :class:`HeuristicProvider`— fallback deterministico offline, così il
       prototipo funziona end-to-end anche senza alcun servizio esterno.

Le chiamate HTTP usano la stdlib (``urllib``) eseguita in thread per non
bloccare il loop asyncio: nessuna dipendenza obbligatoria.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from jarvis.config import Config
from jarvis.llm.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderProfile,
    ProviderUnavailable,
)
from jarvis.logging import get_logger

_log = get_logger("llm.providers")


def _http_json(
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    method: str | None = None,
) -> dict[str, Any]:
    """POST/GET JSON sincrono su stdlib (da eseguire via ``asyncio.to_thread``)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OllamaProvider(LLMProvider):
    """Modello locale servito da Ollama (https://ollama.com)."""

    name = "ollama"
    profile = ProviderProfile(
        cost_per_1k_tokens_usd=0.0, speed=0.6, quality=0.6, max_complexity=0.7
    )

    def __init__(self, config: Config) -> None:
        section = config.section("llm.providers.ollama")
        self.enabled = bool(section.get("enabled", True))
        self.base_url = str(section.get("base_url", "http://127.0.0.1:11434"))
        self.model = str(section.get("model", "llama3.2"))
        self.timeout = float(section.get("timeout_seconds", 60))

    async def is_available(self) -> bool:
        if not self.enabled:
            return False
        try:
            await asyncio.to_thread(
                _http_json, f"{self.base_url}/api/tags", None, None, 2.0
            )
            return True
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        try:
            raw = await asyncio.to_thread(
                _http_json,
                f"{self.base_url}/api/generate",
                {
                    "model": self.model,
                    "prompt": request.prompt,
                    "system": request.system,
                    "stream": False,
                    "options": {
                        "temperature": request.temperature,
                        "num_predict": request.max_tokens,
                    },
                },
                None,
                self.timeout,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderUnavailable(f"Ollama non raggiungibile: {exc}") from exc
        return LLMResponse(
            text=str(raw.get("response", "")).strip(),
            provider=self.name,
            model=self.model,
            latency_seconds=time.monotonic() - started,
        )


class FreeTierProvider(LLMProvider):
    """Endpoint gratuito OpenAI-compatibile (es. OpenRouter free tier).

    Va configurato in ``llm.providers.free`` con ``base_url`` e ``model``;
    la chiave, se richiesta, arriva dall'ambiente (``api_key_env``).
    """

    name = "free"
    profile = ProviderProfile(
        cost_per_1k_tokens_usd=0.0, speed=0.5, quality=0.65, max_complexity=0.75
    )

    def __init__(self, config: Config) -> None:
        section = config.section("llm.providers.free")
        self.enabled = bool(section.get("enabled", False))
        self.base_url = str(section.get("base_url", "")).rstrip("/")
        self.model = str(section.get("model", ""))
        self.timeout = float(section.get("timeout_seconds", 60))
        self._api_key = os.environ.get(str(section.get("api_key_env", "")), "")

    async def is_available(self) -> bool:
        return self.enabled and bool(self.base_url and self.model)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        try:
            raw = await asyncio.to_thread(
                _http_json,
                f"{self.base_url}/chat/completions",
                {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                },
                headers,
                self.timeout,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderUnavailable(f"Provider free non raggiungibile: {exc}") from exc
        text = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        return LLMResponse(
            text=str(text).strip(),
            provider=self.name,
            model=self.model,
            latency_seconds=time.monotonic() - started,
        )


class ClaudeProvider(LLMProvider):
    """Claude API (Anthropic Messages API): usato solo quando necessario."""

    name = "claude"
    profile = ProviderProfile(
        cost_per_1k_tokens_usd=0.009, speed=0.7, quality=0.95, max_complexity=1.0
    )

    def __init__(self, config: Config) -> None:
        section = config.section("llm.providers.claude")
        self.enabled = bool(section.get("enabled", True))
        self.base_url = str(section.get("base_url", "https://api.anthropic.com"))
        self.model = str(section.get("model", "claude-sonnet-5"))
        self.max_tokens = int(section.get("max_tokens", 2048))
        self.timeout = float(section.get("timeout_seconds", 120))
        self._api_key = os.environ.get(str(section.get("api_key_env",
                                                       "ANTHROPIC_API_KEY")), "")

    async def is_available(self) -> bool:
        return self.enabled and bool(self._api_key)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": min(request.max_tokens, self.max_tokens),
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            payload["system"] = request.system
        try:
            raw = await asyncio.to_thread(
                _http_json,
                f"{self.base_url}/v1/messages",
                payload,
                {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
                self.timeout,
            )
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderUnavailable(f"Claude API non raggiungibile: {exc}") from exc
        blocks = raw.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = raw.get("usage", {})
        tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        return LLMResponse(
            text=text.strip(),
            provider=self.name,
            model=self.model,
            estimated_cost_usd=tokens / 1000 * self.profile.cost_per_1k_tokens_usd,
            latency_seconds=time.monotonic() - started,
        )


class HeuristicProvider(LLMProvider):
    """Fallback deterministico e offline.

    Non è un modello: produce risposte strutturate e oneste ("elaborato in
    modalità euristica") così l'intera pipeline resta esercitabile senza
    servizi esterni. Il router lo sceglie solo quando nessun provider reale
    è disponibile.
    """

    name = "heuristic"
    profile = ProviderProfile(
        cost_per_1k_tokens_usd=0.0, speed=1.0, quality=0.1, max_complexity=1.0
    )

    async def is_available(self) -> bool:
        return True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        summary = request.prompt.strip().replace("\n", " ")
        if len(summary) > 240:
            summary = summary[:240] + "…"
        text = (
            "[modalità euristica — nessun provider LLM disponibile]\n"
            f"Richiesta ricevuta: \"{summary}\"\n"
            "Analisi: la richiesta è stata registrata ed elaborata dalla pipeline "
            "(reasoning → planner → execution). Per risposte generative, avviare "
            "Ollama o configurare una API key."
        )
        return LLMResponse(
            text=text,
            provider=self.name,
            model="rule-based",
            latency_seconds=time.monotonic() - started,
        )
