"""Contratto dell'adapter di backend.

Un adapter traduce fra il dialetto reale di un backend e JCP, in entrambe le
direzioni. Ha **tre responsabilità e nessun'altra**:

1. ``to_backend`` — da JCP al dialetto del backend;
2. ``from_backend`` — dal dialetto del backend a JCP;
3. dichiarare quali capability sa mappare.

Ciò che un adapter non deve fare, ed è la parte che conta: non decide, non
conserva stato di dominio, non tocca il bus, non conosce lo state manager. Se
un adapter iniziasse ad avere logica di stato sarebbe il segnale che il confine
è stato attraversato, e la sostituibilità del backend — l'unico motivo per cui
questo livello esiste — sarebbe già persa.

Un adapter **può** essere senza stato o averne uno puramente tecnico (una mappa
di identificativi, un contatore di sequenza). La distinzione è fra stato di
traduzione e stato di dominio.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.jcp.envelope import Envelope

__all__ = ["IBackendAdapter"]


@runtime_checkable
class IBackendAdapter(Protocol):
    """Traduttore fra JCP e il dialetto di uno specifico backend."""

    @property
    def name(self) -> str:
        """Nome del backend supportato, per log e diagnostica."""
        ...

    def to_backend(self, envelope: Envelope) -> list[dict[str, Any]]:
        """Traduce un messaggio JCP nel dialetto del backend.

        :returns: i messaggi da serializzare. Lista **vuota** se il backend non
            supporta questo tipo: non tutti i backend hanno un equivalente per
            ogni messaggio JCP, e non inviare nulla è una risposta legittima.
        """
        ...

    def from_backend(self, raw: dict[str, Any]) -> list[Envelope]:
        """Traduce un messaggio del backend in JCP.

        :returns: le buste JCP corrispondenti. La cardinalità **non è uno a
            uno**: un backend che invia blocchi audio senza aprire lo stream
            richiede due messaggi JCP per il primo blocco. Lista vuota se il
            messaggio va ignorato — che non è un errore, ma la regola che
            permette a un backend più recente di parlare senza rompere una GUI
            più vecchia.
        """
        ...

    def describe(self) -> dict[str, Any]:
        """Informazioni per la Developer Console: nome, versione, note."""
        ...
