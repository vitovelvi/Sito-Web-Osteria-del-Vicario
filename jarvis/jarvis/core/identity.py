"""Core Identity: personalità, tono, regole operative, priorità e autonomia.

L'identità è caricata dalla configurazione ed è consultata da Reasoning Engine,
Planner e agenti per mantenere coerenza di comportamento. È l'unico punto del
sistema che definisce "chi è" JARVIS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.config import Config


class AutonomyLevel(str, Enum):
    """Livelli di autonomia operativa concessi dall'utente."""

    MANUAL = "manual"          # ogni step richiede conferma
    SUPERVISED = "supervised"  # autonomo su Livello 0-1, conferma su 2-3
    TRUSTED = "trusted"        # autonomo su Livello 0-2, conferma solo su 3

    def max_unconfirmed_security_level(self) -> int:
        """Livello di sicurezza massimo eseguibile senza conferma."""
        return {"manual": -1, "supervised": 1, "trusted": 2}[self.value]


@dataclass(slots=True)
class CoreIdentity:
    """Identità operativa di JARVIS.

    Attributes:
        name: nome del sistema.
        traits: tratti di personalità (calmo, preciso, sintetico, ...).
        philosophy: filosofia operativa.
        tone: registro, verbosità e forma di indirizzo.
        operating_rules: regole non negoziabili.
        priorities: priorità in ordine decrescente.
        autonomy: livello di autonomia corrente.
    """

    name: str = "JARVIS"
    traits: list[str] = field(default_factory=list)
    philosophy: str = ""
    tone: dict[str, str] = field(default_factory=dict)
    operating_rules: list[str] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)
    autonomy: AutonomyLevel = AutonomyLevel.SUPERVISED

    @classmethod
    def from_config(cls, config: Config) -> "CoreIdentity":
        """Costruisce l'identità dalla sezione ``identity`` della config."""
        section = config.section("identity")
        personality = section.section("personality")
        raw_level = str(section.get("autonomy.default_level", "supervised"))
        try:
            autonomy = AutonomyLevel(raw_level)
        except ValueError:
            autonomy = AutonomyLevel.SUPERVISED
        return cls(
            name=str(section.get("name", "JARVIS")),
            traits=list(personality.get("traits", [])),
            philosophy=str(personality.get("philosophy", "")),
            tone=dict(personality.get("tone", {})),
            operating_rules=list(section.get("operating_rules", [])),
            priorities=list(section.get("priorities", [])),
            autonomy=autonomy,
        )

    def system_prompt(self) -> str:
        """Prompt d'identità per gli LLM: garantisce coerenza di tono."""
        rules = "\n".join(f"- {rule}" for rule in self.operating_rules)
        traits = ", ".join(self.traits)
        return (
            f"Sei {self.name}, un sistema operativo cognitivo.\n"
            f"Tratti: {traits}.\n"
            f"Filosofia: {self.philosophy}\n"
            f"Tono: {self.tone.get('register', 'professionale')}, "
            f"{self.tone.get('verbosity', 'sintetico')}.\n"
            f"Regole operative:\n{rules}\n"
            f"Priorità (in ordine): {', '.join(self.priorities)}.\n"
            "Sei subordinato all'utente: mai impulsivo, mai distruttivo senza conferma."
        )

    def describe(self) -> dict[str, Any]:
        """Snapshot serializzabile per dashboard e memoria."""
        return {
            "name": self.name,
            "traits": self.traits,
            "philosophy": self.philosophy,
            "tone": self.tone,
            "operating_rules": self.operating_rules,
            "priorities": self.priorities,
            "autonomy": self.autonomy.value,
        }
