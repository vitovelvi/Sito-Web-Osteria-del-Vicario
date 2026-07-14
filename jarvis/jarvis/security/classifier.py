"""Classificazione delle operazioni e gate di conferma.

Regole:
    - ogni azione registrata dichiara il proprio livello di base;
    - il classificatore può alzare (mai abbassare) il livello in base ai
      parametri (percorsi fuori sandbox, pattern distruttivi);
    - il :class:`ConfirmationGate` blocca le operazioni oltre il livello di
      autonomia finché l'utente non conferma; senza presidio, nega.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from jarvis.core.identity import CoreIdentity
from jarvis.events import Event, EventBus
from jarvis.logging import get_logger
from jarvis.security.levels import SecurityLevel

_log = get_logger("security")

# Frammenti che indicano intenti distruttivi nei parametri di un'azione.
_DESTRUCTIVE_MARKERS = ("rm -rf", "format", "drop table", "truncate", "shred",
                        "mkfs", "dd if=", ":(){", "del /f")

Confirmer = Callable[[str, SecurityLevel], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class ClassifiedOperation:
    """Esito della classificazione di un'operazione."""

    action: str
    level: SecurityLevel
    reasons: tuple[str, ...]


class OperationClassifier:
    """Assegna un :class:`SecurityLevel` a ogni operazione.

    Args:
        base_levels: livello dichiarato per ciascuna azione registrata.
    """

    def __init__(self, base_levels: dict[str, SecurityLevel]) -> None:
        self._base_levels = dict(base_levels)

    def register(self, action: str, level: SecurityLevel) -> None:
        """Registra (o aggiorna) il livello base di un'azione."""
        self._base_levels[action] = level

    def classify(self, action: str, params: dict[str, Any]) -> ClassifiedOperation:
        """Classifica ``action`` con i suoi parametri concreti.

        Azioni sconosciute sono trattate come ``IRREVERSIBLE``: ciò che non è
        registrato non è eseguibile senza massima cautela.
        """
        reasons: list[str] = []
        level = self._base_levels.get(action)
        if level is None:
            return ClassifiedOperation(
                action, SecurityLevel.IRREVERSIBLE, ("azione non registrata",)
            )
        reasons.append(f"livello base dell'azione: {level.name}")

        blob = str(params).lower()
        if any(marker in blob for marker in _DESTRUCTIVE_MARKERS):
            level = SecurityLevel.IRREVERSIBLE
            reasons.append("pattern distruttivo nei parametri")

        if params.get("path") and level < SecurityLevel.SIGNIFICANT:
            # Le scritture su percorsi espliciti fuori dalla sandbox pesano di più:
            # la verifica puntuale dei percorsi appartiene alla Sandbox.
            if params.get("mode") in {"write", "delete"}:
                level = SecurityLevel.SIGNIFICANT
                reasons.append("scrittura su percorso esplicito")

        return ClassifiedOperation(action, level, tuple(reasons))


class ConfirmationGate:
    """Gate di conferma: decide se un'operazione può procedere.

    La decisione combina il livello dell'operazione, l'autonomia concessa
    dall'identità e la presenza dell'utente. Ogni esito è pubblicato sul bus
    come audit trail.
    """

    def __init__(
        self,
        identity: CoreIdentity,
        bus: EventBus,
        *,
        confirmation_from_level: int = 2,
        auto_deny_when_unattended: bool = True,
        confirmer: Confirmer | None = None,
    ) -> None:
        self._identity = identity
        self._bus = bus
        self._threshold = confirmation_from_level
        self._auto_deny = auto_deny_when_unattended
        self._confirmer = confirmer

    def set_confirmer(self, confirmer: Confirmer | None) -> None:
        """Inietta il canale di conferma (CLI, dashboard, voce)."""
        self._confirmer = confirmer

    async def authorize(self, operation: ClassifiedOperation,
                        correlation_id: str | None = None) -> bool:
        """Autorizza o nega un'operazione classificata."""
        autonomy_max = self._identity.autonomy.max_unconfirmed_security_level()
        needs_confirmation = (
            operation.level >= self._threshold or operation.level > autonomy_max
        )

        if not needs_confirmation:
            await self._audit("granted", operation, correlation_id, auto=True)
            return True

        await self._bus.publish(Event(
            topic="security.confirmation.required",
            payload={"action": operation.action, "level": int(operation.level),
                     "reasons": list(operation.reasons)},
            source="security.gate",
            correlation_id=correlation_id,
        ))

        if self._confirmer is None:
            if self._auto_deny:
                await self._audit("denied", operation, correlation_id,
                                  note="nessun canale di conferma disponibile")
                return False
            await self._audit("granted", operation, correlation_id,
                              note="auto-approvazione disabilitata dalla config")
            return True

        try:
            approved = await self._confirmer(
                f"{operation.action} [{operation.level.describe()}]", operation.level
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - il canale può fallire
            _log.error("Canale di conferma fallito: %s", exc)
            approved = False

        await self._audit("granted" if approved else "denied",
                          operation, correlation_id)
        return approved

    async def _audit(self, outcome: str, operation: ClassifiedOperation,
                     correlation_id: str | None, *, auto: bool = False,
                     note: str = "") -> None:
        _log.info("Security %s: %s (%s)%s", outcome, operation.action,
                  operation.level.name, f" — {note}" if note else "")
        await self._bus.publish(Event(
            topic=f"security.confirmation.{outcome}",
            payload={"action": operation.action, "level": int(operation.level),
                     "auto": auto, "note": note},
            source="security.gate",
            correlation_id=correlation_id,
        ))
