"""Executor: registro delle azioni eseguibili.

Le azioni sono l'UNICA superficie con cui JARVIS tocca il mondo: funzioni
tipizzate, registrate con un livello di sicurezza dichiarato e uno schema dei
parametri. Un LLM può solo *proporre* il nome di un'azione registrata; non
esiste alcun percorso da testo libero a terminale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from jarvis.security import SecurityLevel

ActionHandler = Callable[["ActionContext", dict[str, Any]], Awaitable[Any]]


@dataclass(slots=True)
class ActionContext:
    """Dipendenze iniettate negli handler delle azioni.

    Gli handler ricevono solo questa facciata, mai i sottosistemi interi:
    ciò mantiene esplicito e verificabile cosa un'azione può toccare.
    """

    services: dict[str, Any] = field(default_factory=dict)

    def service(self, name: str) -> Any:
        if name not in self.services:
            raise KeyError(f"Servizio non disponibile per le azioni: {name!r}")
        return self.services[name]


@dataclass(frozen=True, slots=True)
class ActionSpec:
    """Definizione di un'azione registrata.

    Attributes:
        name: nome univoco (es. ``fs.list``).
        handler: coroutine che implementa l'azione.
        level: livello di sicurezza di base.
        description: descrizione leggibile.
        required_params: parametri obbligatori (validati prima dell'esecuzione).
    """

    name: str
    handler: ActionHandler
    level: SecurityLevel
    description: str
    required_params: tuple[str, ...] = ()


class Executor:
    """Registro ed esecutore delle azioni."""

    def __init__(self, context: ActionContext) -> None:
        self._actions: dict[str, ActionSpec] = {}
        self._context = context

    def register(self, spec: ActionSpec) -> None:
        """Registra un'azione (il nome deve essere univoco)."""
        if spec.name in self._actions:
            raise ValueError(f"Azione già registrata: {spec.name!r}")
        self._actions[spec.name] = spec

    def spec(self, name: str) -> ActionSpec | None:
        return self._actions.get(name)

    def known_actions(self) -> dict[str, ActionSpec]:
        return dict(self._actions)

    def base_levels(self) -> dict[str, SecurityLevel]:
        """Mappa azione → livello base, per l'OperationClassifier."""
        return {name: spec.level for name, spec in self._actions.items()}

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Esegue un'azione registrata.

        Nota: questo metodo è invocato SOLO dalla Sandbox; i componenti
        devono passare dall'ExecutionBroker.
        """
        spec = self._actions.get(name)
        if spec is None:
            raise KeyError(f"Azione non registrata: {name!r}")
        return await spec.handler(self._context, params)
