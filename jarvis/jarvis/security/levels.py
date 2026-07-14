"""Livelli di sicurezza delle operazioni.

Ogni operazione che attraversa l'Execution System è classificata prima di
essere eseguita. La classificazione è indipendente da chi la richiede.
"""

from __future__ import annotations

from enum import IntEnum


class SecurityLevel(IntEnum):
    """Classificazione del rischio di un'operazione.

    - ``READ_ONLY``: sola lettura, nessun effetto collaterale.
    - ``REVERSIBLE``: modifica reversibile (scritture in sandbox, cache).
    - ``SIGNIFICANT``: modifica importante ma recuperabile; richiede conferma.
    - ``IRREVERSIBLE``: distruttiva o non recuperabile; richiede sempre conferma.
    """

    READ_ONLY = 0
    REVERSIBLE = 1
    SIGNIFICANT = 2
    IRREVERSIBLE = 3

    def describe(self) -> str:
        return {
            SecurityLevel.READ_ONLY: "Livello 0 — Solo lettura",
            SecurityLevel.REVERSIBLE: "Livello 1 — Modifica reversibile",
            SecurityLevel.SIGNIFICANT: "Livello 2 — Modifica importante (conferma)",
            SecurityLevel.IRREVERSIBLE: "Livello 3 — Irreversibile (conferma obbligatoria)",
        }[self]
