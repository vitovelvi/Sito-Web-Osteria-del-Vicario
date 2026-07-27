"""FrameClock: un solo battito per tutte le animazioni.

Il brief chiedeva di animare con ``QPropertyAnimation``. E' lo strumento giusto
per far evolvere uno scalare, ma ogni istanza porta con se' il **proprio timer
interno**: con sei o otto animazioni attive si ottengono aggiornamenti sfasati,
ridisegni ridondanti e micro-stuttering — un'interfaccia che "quasi" scorre
fluida, che e' il difetto piu' fastidioso da diagnosticare perche' nessun
singolo pezzo appare colpevole.

Qui il tempo ha una sola sorgente. Il clock emette :attr:`FrameClock.tick` a
cadenza costante; le animazioni **leggono** il tempo invece di generarlo, e il
ridisegno avviene una volta per frame. ``QPropertyAnimation`` continua a essere
usato dove serve davvero — le dissolvenze fra stati — ma non guida piu' il
rendering continuo.

Il clock misura anche il proprio ritardo: se il tempo per frame supera il budget,
:attr:`FrameClock.load` supera 1.0 e il gestore di qualita' puo' ridurre gli
effetti. Meglio un'interfaccia che si adatta di una che scatta.
"""

from __future__ import annotations

import time
from typing import Final

from core.logging_setup import LogCategory, get_logger
from core.qtcompat import Qt, QtCore, Signal

__all__ = ["FrameClock"]

_log = get_logger(LogCategory.UI, "frameclock")

#: Oltre questo valore il frame e' considerato "saltato" ai fini della
#: statistica: 2.5 volte il budget significa che qualcosa ha bloccato il thread.
_HITCH_FACTOR: Final[float] = 2.5

#: Coefficiente della media esponenziale sul tempo di frame. Basso = reattivo
#: al degrado, alto = stabile. 0.1 reagisce in circa dieci frame.
_EMA_ALPHA: Final[float] = 0.1


class FrameClock(QtCore.QObject):
    """Sorgente unica del tempo di animazione."""

    #: Emesso a ogni frame con il delta in **secondi** dal frame precedente.
    #: Le animazioni devono integrare su questo valore e mai assumere un passo
    #: fisso: su una macchina carica il passo reale non e' quello nominale, e
    #: un'animazione che conta i frame invece dei secondi rallenta con essa.
    tick = Signal(float)

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        *,
        target_fps: int = 60,
    ) -> None:
        super().__init__(parent)
        self._target_fps = max(1, target_fps)
        self._timer = QtCore.QTimer(self)
        # PreciseTimer chiede a Qt la massima accuratezza disponibile: senza,
        # su Windows la granularita' di default e' ~15 ms, cioe' un frame su due.
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(self._interval_ms())
        self._timer.timeout.connect(self._on_timeout)

        self._last = 0.0
        self._elapsed = 0.0
        self._frames = 0
        self._hitches = 0
        self._frame_ms_ema = 1000.0 / self._target_fps
        self._active = False

    # ------------------------------------------------------------------ #
    # Controllo
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Avvia il battito. Idempotente."""
        if self._active:
            return
        self._active = True
        self._last = time.perf_counter()
        self._timer.start()
        _log.debug("FrameClock avviato a %d FPS", self._target_fps)

    def stop(self) -> None:
        """Ferma il battito.

        Va chiamato quando la finestra e' nascosta o in standby: un'applicazione
        che parte al login e resta accesa tutto il giorno non deve consumare CPU
        per animare pixel che nessuno guarda.
        """
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        _log.debug("FrameClock fermato (%d frame, %d hitch)", self._frames, self._hitches)

    @property
    def is_running(self) -> bool:
        return self._active

    def set_target_fps(self, fps: int) -> None:
        """Cambia la cadenza a caldo.

        Usato dal gestore di qualita': scendere a 30 FPS su un portatile a
        batteria e' una scelta migliore che restare a 60 perdendo frame in modo
        irregolare — l'occhio percepisce l'irregolarita', non il valore assoluto.
        """
        fps = max(1, fps)
        if fps == self._target_fps:
            return
        self._target_fps = fps
        self._timer.setInterval(self._interval_ms())
        _log.info("Cadenza portata a %d FPS", fps)

    def _interval_ms(self) -> int:
        return max(1, round(1000.0 / self._target_fps))

    # ------------------------------------------------------------------ #
    # Battito
    # ------------------------------------------------------------------ #

    def _on_timeout(self) -> None:
        """Calcola il delta e notifica gli ascoltatori."""
        now = time.perf_counter()
        dt = now - self._last
        self._last = now

        # Un delta enorme significa che il thread e' stato bloccato (dialogo
        # modale, sospensione del sistema). Propagarlo farebbe "saltare" le
        # animazioni in avanti di mezzo secondo: meglio limitarlo e ripartire.
        budget = 1.0 / self._target_fps
        if dt > budget * _HITCH_FACTOR:
            self._hitches += 1
            dt = min(dt, budget * _HITCH_FACTOR)

        self._elapsed += dt
        self._frames += 1
        self._frame_ms_ema = (
            _EMA_ALPHA * (dt * 1000.0) + (1.0 - _EMA_ALPHA) * self._frame_ms_ema
        )

        # Gli ascoltatori sono isolati: un widget che solleva durante il
        # ridisegno non deve fermare il battito di tutti gli altri.
        try:
            self.tick.emit(dt)
        except Exception:
            _log.exception("Errore durante la propagazione del tick")

    # ------------------------------------------------------------------ #
    # Misure
    # ------------------------------------------------------------------ #

    @property
    def elapsed(self) -> float:
        """Secondi di animazione trascorsi da quando il clock e' attivo.

        E' il tempo che le animazioni cicliche devono usare come fase: essendo
        fermo durante lo standby, riattivare l'interfaccia non produce un salto.
        """
        return self._elapsed

    @property
    def frame_ms(self) -> float:
        """Tempo medio per frame in millisecondi (media esponenziale)."""
        return self._frame_ms_ema

    @property
    def fps(self) -> float:
        """Frequenza effettiva stimata."""
        return 1000.0 / self._frame_ms_ema if self._frame_ms_ema > 0 else 0.0

    @property
    def load(self) -> float:
        """Rapporto fra tempo di frame reale e budget nominale.

        Sopra 1.0 il clock non tiene il passo. E' il segnale su cui il gestore
        di qualita' decide di ridurre gli effetti.
        """
        return self._frame_ms_ema / (1000.0 / self._target_fps)

    @property
    def hitches(self) -> int:
        """Numero di frame in cui il thread e' rimasto bloccato oltre soglia."""
        return self._hitches

    def metrics(self) -> dict[str, float]:
        """Riepilogo per il pannello di diagnostica."""
        return {
            "target_fps": float(self._target_fps),
            "fps": round(self.fps, 1),
            "frame_ms": round(self._frame_ms_ema, 2),
            "load": round(self.load, 2),
            "frames": float(self._frames),
            "hitches": float(self._hitches),
        }
