"""Politica di riconnessione: backoff esponenziale, jitter, interruttore.

Tre comportamenti che sembrano dettagli e non lo sono:

**Il jitter.** Senza, tutti i client che perdono la connessione insieme —
perché il backend è stato riavviato — riprovano nello stesso istante, e lo
riaffondano appena risale. È il "thundering herd", e con un solo utente si
manifesta comunque quando la GUI e altri processi condividono la stessa rete.

**Il tetto massimo.** Un backoff illimitato porta ad attese di ore: l'utente
riavvia OpenClaw e Jarvis non se ne accorge fino a sera.

**L'interruttore.** Dopo molti fallimenti consecutivi la causa non è
transitoria — indirizzo sbagliato, servizio non installato. Si continua a
riprovare, ma con calma, e l'HUD lo dice invece di fingere un tentativo
imminente all'infinito.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = ["BackoffPolicy"]


@dataclass(slots=True)
class BackoffPolicy:
    """Calcola l'attesa fra un tentativo di connessione e il successivo."""

    initial: float = 1.0
    maximum: float = 30.0
    factor: float = 2.0
    jitter: float = 0.3
    """Frazione di variazione casuale applicata all'attesa (0 = nessuna)."""

    circuit_threshold: int = 12
    """Fallimenti consecutivi dopo i quali si passa alla cadenza lenta."""

    circuit_delay: float = 120.0
    """Attesa fissa una volta scattato l'interruttore."""

    _attempts: int = 0
    _rng: random.Random | None = None

    def __post_init__(self) -> None:
        if self._rng is None:
            self._rng = random.Random()

    @property
    def attempts(self) -> int:
        """Tentativi falliti consecutivi."""
        return self._attempts

    @property
    def circuit_open(self) -> bool:
        """Vero quando la causa non sembra più transitoria."""
        return self._attempts >= self.circuit_threshold

    def next_delay(self) -> float:
        """Registra un fallimento e restituisce l'attesa prima del prossimo tentativo."""
        self._attempts += 1

        if self.circuit_open:
            base = self.circuit_delay
        else:
            base = min(self.maximum, self.initial * (self.factor ** (self._attempts - 1)))

        if self.jitter <= 0.0:
            return base

        assert self._rng is not None
        spread = base * self.jitter
        # Il jitter è simmetrico ma non può produrre attese negative o nulle:
        # un ritardo zero equivarrebbe a un ciclo di riconnessione a vuoto.
        return max(0.1, base + self._rng.uniform(-spread, spread))

    def reset(self) -> None:
        """Azzera il conteggio dopo una connessione riuscita."""
        self._attempts = 0

    def describe(self) -> str:
        """Testo per l'HUD e per i log."""
        if self._attempts == 0:
            return "nessun tentativo fallito"
        if self.circuit_open:
            return f"{self._attempts} tentativi falliti: nuovi tentativi diradati"
        return f"tentativo {self._attempts + 1}"
