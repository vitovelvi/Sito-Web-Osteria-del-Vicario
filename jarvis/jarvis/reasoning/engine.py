"""Reasoning Engine: analizza la richiesta PRIMA di qualsiasi esecuzione.

Il ragionamento è separato dall'esecuzione per progetto: l'output del motore
è un oggetto :class:`Reasoning` (intento, vincoli, rischio, approccio) che il
Planner traduce in un piano; solo l'Execution System tocca il mondo reale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.identity import CoreIdentity
from jarvis.llm import LLMRequest, LLMRouter, Quality
from jarvis.llm.base import ProviderUnavailable
from jarvis.logging import get_logger

_log = get_logger("reasoning")

# Mappa intento → segnali lessicali (italiano + inglese).
# L'ordine conta: i pattern più specifici (memoria, codice) precedono quelli
# generici (report di sistema), che contengono parole ad alta frequenza.
_INTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "memory": re.compile(
        r"\b(ricorda|memorizza|salva|preferenz|remember)\w*", re.IGNORECASE),
    "coding": re.compile(
        r"\b(codice|script|implementa|programma|refactor|debug|funzione)\b", re.IGNORECASE),
    "research": re.compile(
        r"\b(cerca|ricerca|search|trova|approfondisci|documentati)\b", re.IGNORECASE),
    "system_report": re.compile(
        r"\b(stato del sistema|system status|report|diagnostic|cpu|ram|memoria|process)\w*",
        re.IGNORECASE),
    "file_ops": re.compile(
        r"\b(file|cartella|directory|leggi|elenca|lista)\b", re.IGNORECASE),
}


@dataclass(slots=True)
class Reasoning:
    """Esito del ragionamento su una richiesta.

    Attributes:
        request_text: richiesta originale.
        intent: intento principale riconosciuto.
        analysis: analisi discorsiva (da LLM quando disponibile).
        constraints: vincoli operativi da rispettare.
        risk_note: valutazione sintetica del rischio.
        suggested_actions: azioni suggerite al Planner (nomi registrati).
        context: contesto di memoria rilevante.
    """

    request_text: str
    intent: str
    analysis: str
    constraints: list[str] = field(default_factory=list)
    risk_note: str = "basso"
    suggested_actions: list[str] = field(default_factory=list)
    context: list[dict[str, Any]] = field(default_factory=list)


class ReasoningEngine:
    """Motore di ragionamento: intento, analisi, vincoli.

    Usa il LLM Router per l'analisi discorsiva quando un provider è
    disponibile; la classificazione dell'intento resta deterministica, così
    la pipeline è affidabile anche offline.
    """

    def __init__(self, identity: CoreIdentity, router: LLMRouter) -> None:
        self._identity = identity
        self._router = router

    @staticmethod
    def detect_intent(text: str) -> str:
        """Classifica l'intento in modo deterministico."""
        for intent, pattern in _INTENT_PATTERNS.items():
            if pattern.search(text):
                return intent
        return "general"

    async def reason(
        self, request_text: str, context: list[dict[str, Any]] | None = None
    ) -> Reasoning:
        """Produce il ragionamento per una richiesta utente."""
        intent = self.detect_intent(request_text)
        constraints = list(self._identity.operating_rules)
        suggested = {
            "system_report": ["system.stats", "memory.recall", "respond"],
            "research": ["web.search", "respond"],
            "coding": ["llm.generate", "respond"],
            "memory": ["memory.store", "respond"],
            "file_ops": ["fs.list", "respond"],
            "general": ["llm.generate", "respond"],
        }[intent]

        analysis = f"Intento riconosciuto: {intent}."
        try:
            response = await self._router.generate(LLMRequest(
                prompt=(
                    "Analizza questa richiesta e descrivi in 2-3 frasi l'approccio "
                    f"migliore, senza eseguirla.\nRichiesta: {request_text}"
                ),
                system=self._identity.system_prompt(),
                quality=Quality.FAST,
                max_tokens=256,
            ))
            analysis = response.text
        except ProviderUnavailable:
            _log.debug("Nessun LLM per l'analisi discorsiva: uso solo l'euristica")

        risk = "basso" if intent in {"system_report", "research", "general"} else "medio"
        return Reasoning(
            request_text=request_text,
            intent=intent,
            analysis=analysis,
            constraints=constraints,
            risk_note=risk,
            suggested_actions=suggested,
            context=context or [],
        )
