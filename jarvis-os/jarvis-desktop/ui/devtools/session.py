"""Pannello Sessione: registrazione, replay, conformità.

Tre strumenti che rispondono a tre domande diverse:

* **registra** — "com'era la sessione quando è successo?" Produce un file da
  allegare a una segnalazione;
* **riproduci** — "fammelo rivedere." Ripete una registrazione. Non reagisce ai
  comandi, e il pannello lo dice a chiare lettere: chi non lo sapesse
  concluderebbe che l'interfaccia è rotta;
* **verifica** — "questo backend è conforme?" Esegue la suite dell'SDK e mostra
  quali punti della specifica non sono rispettati.

La verifica gira in un thread proprio: apre connessioni e attende risposte, e
farlo nel thread grafico bloccherebbe l'interfaccia proprio mentre si sta
diagnosticando un problema di connessione.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from jarvis_sdk.conformance import ConformanceReport, run_conformance
from jarvis_sdk.recording import Recording

from core.errors import safe_slot
from core.logging_setup import LogCategory, get_logger
from core.paths import app_paths
from core.qtcompat import QtCore, QtGui, QtWidgets, Signal
from ui.theme.theme import Theme

__all__ = ["SessionPanel"]

_log = get_logger(LogCategory.UI, "session")


class SessionPanel(QtWidgets.QWidget):
    """Registrazione, replay e verifica di conformità."""

    _report_ready = Signal(object)
    """Emesso dal thread di verifica; la consegna avviene nel thread grafico."""

    def __init__(
        self,
        network: Any,
        theme: Theme,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._network = network
        self._theme = theme
        self._loaded: Recording | None = None
        self._checking = False

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_recorder())
        layout.addWidget(self._build_replay())
        layout.addWidget(self._build_conformance(), 1)

        self._report_ready.connect(self._show_report)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh_status)

    # ------------------------------------------------------------------ #
    # Registrazione
    # ------------------------------------------------------------------ #

    def _build_recorder(self) -> QtWidgets.QWidget:
        riquadro = self._frame("REGISTRAZIONE")

        self._record_button = QtWidgets.QPushButton("Avvia registrazione")
        self._record_button.clicked.connect(self._toggle_recording)

        self._save_button = QtWidgets.QPushButton("Salva…")
        self._save_button.setEnabled(False)
        self._save_button.clicked.connect(self._save_recording)

        self._record_status = QtWidgets.QLabel("Ferma.")
        self._record_status.setProperty("role", "muted")

        riga = QtWidgets.QHBoxLayout()
        riga.setSpacing(8)
        riga.addWidget(self._record_button)
        riga.addWidget(self._save_button)
        riga.addWidget(self._record_status, 1)
        riquadro.layout().addLayout(riga)

        nota = QtWidgets.QLabel(
            "Token e blocchi audio non finiscono nel file: una registrazione "
            "nasce per essere allegata a una segnalazione."
        )
        nota.setProperty("role", "muted")
        nota.setWordWrap(True)
        riquadro.layout().addWidget(nota)
        return riquadro

    @safe_slot("devtools.session")
    def _toggle_recording(self) -> None:
        if self._network is None:
            return
        if self._network.recorder.is_recording:
            registrazione = self._network.stop_recording()
            self._save_button.setEnabled(len(registrazione) > 0)
        else:
            self._network.start_recording()
            self._save_button.setEnabled(False)
        self._refresh_status()

    @safe_slot("devtools.session")
    def _save_recording(self) -> None:
        if self._network is None:
            return
        registrazione = self._network.recorder.current
        if not len(registrazione):
            return

        predefinito = str(app_paths().data_dir / "sessioni" / "sessione.jcpl")
        percorso, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Salva la sessione", predefinito, "Sessioni JCP (*.jcpl)"
        )
        if not percorso:
            return

        try:
            registrazione.save(Path(percorso))
        except OSError as exc:
            self._record_status.setText(f"Salvataggio non riuscito: {exc}")
            return
        self._record_status.setText(f"Salvata in {Path(percorso).name}")
        _log.info("Sessione salvata in %s", percorso)

    def _refresh_status(self) -> None:
        """Riallinea i comandi allo stato reale del registratore.

        Il pulsante non ricorda cosa ha fatto: legge. Una registrazione puo'
        essere avviata da altrove — dalla riga di comando, da un altro
        pannello — e un pulsante che dicesse "Avvia" mentre la registrazione
        e' gia' in corso mentirebbe su cosa succede premendolo.
        """
        if self._network is None:
            return
        registratore = self._network.recorder
        registrazione = registratore.current
        self._record_button.setText(
            "Ferma registrazione" if registratore.is_recording else "Avvia registrazione"
        )
        if registratore.is_recording:
            testo = f"In corso · {len(registrazione)} messaggi"
            if registratore.truncated:
                testo += " · ⚠ tetto raggiunto, i nuovi vengono scartati"
        elif len(registrazione):
            testo = f"Ferma · {len(registrazione)} messaggi, {registrazione.duration:.1f}s"
        else:
            testo = "Ferma."
        self._record_status.setText(testo)

    # ------------------------------------------------------------------ #
    # Replay
    # ------------------------------------------------------------------ #

    def _build_replay(self) -> QtWidgets.QWidget:
        riquadro = self._frame("REPLAY")

        carica = QtWidgets.QPushButton("Apri sessione…")
        carica.clicked.connect(self._load_recording)

        self._replay_button = QtWidgets.QPushButton("Riproduci")
        self._replay_button.setEnabled(False)
        self._replay_button.clicked.connect(self._toggle_replay)

        self._replay_status = QtWidgets.QLabel("Nessuna sessione caricata.")
        self._replay_status.setProperty("role", "muted")

        riga = QtWidgets.QHBoxLayout()
        riga.setSpacing(8)
        riga.addWidget(carica)
        riga.addWidget(self._replay_button)
        riga.addWidget(self._replay_status, 1)
        riquadro.layout().addLayout(riga)

        avviso = QtWidgets.QLabel(
            "Durante il replay l'interfaccia non reagisce ai comandi: una "
            "registrazione riproduce, non simula. Per la reattività si usa "
            "l'ambiente di simulazione."
        )
        avviso.setProperty("role", "muted")
        avviso.setWordWrap(True)
        riquadro.layout().addWidget(avviso)
        return riquadro

    @safe_slot("devtools.session")
    def _load_recording(self) -> None:
        percorso, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Apri una sessione", str(app_paths().data_dir), "Sessioni JCP (*.jcpl)"
        )
        if not percorso:
            return

        try:
            self._loaded = Recording.load(Path(percorso))
        except Exception as exc:
            self._replay_status.setText(f"Non caricabile: {exc}")
            self._replay_button.setEnabled(False)
            return

        riepilogo = self._loaded.summary()
        self._replay_status.setText(
            f"{Path(percorso).name} · {riepilogo['messaggi']} messaggi · "
            f"{riepilogo['durata_s']}s · backend {riepilogo['backend']}"
        )
        self._replay_button.setEnabled(True)

    @safe_slot("devtools.session")
    def _toggle_replay(self) -> None:
        if self._network is None:
            return
        if self._network.is_replaying:
            self._network.set_replay(None)
            self._replay_button.setText("Riproduci")
        elif self._loaded is not None:
            self._network.set_replay(self._loaded)
            self._replay_button.setText("Interrompi replay")

    # ------------------------------------------------------------------ #
    # Conformità
    # ------------------------------------------------------------------ #

    def _build_conformance(self) -> QtWidgets.QWidget:
        riquadro = self._frame("CONFORMITÀ JCP")

        self._check_button = QtWidgets.QPushButton("Verifica il backend")
        self._check_button.clicked.connect(self._run_conformance)

        riga = QtWidgets.QHBoxLayout()
        riga.addWidget(self._check_button)
        riga.addStretch(1)
        riquadro.layout().addLayout(riga)

        self._report = QtWidgets.QPlainTextEdit()
        self._report.setReadOnly(True)
        self._report.setFont(QtGui.QFont(str(self._theme.raw("font.mono", "monospace")), 10))
        self._report.setPlaceholderText(
            "Esegue i punti di conformità della specifica contro il backend "
            "configurato, aprendo una connessione nuova per ciascun controllo."
        )
        riquadro.layout().addWidget(self._report, 1)
        return riquadro

    @safe_slot("devtools.session")
    def _run_conformance(self) -> None:
        if self._network is None or self._checking:
            return

        self._checking = True
        self._check_button.setEnabled(False)
        self._report.setPlainText("Verifica in corso…")

        factory = self._network.transport_factory()
        segnale = self._report_ready

        def lavora() -> None:
            try:
                report = asyncio.run(run_conformance(factory, timeout=4.0))
            except Exception as exc:
                _log.exception("Verifica di conformità interrotta")
                report = exc
            segnale.emit(report)

        threading.Thread(target=lavora, name="jarvis-conformance", daemon=True).start()

    @safe_slot("devtools.session")
    def _show_report(self, esito: object) -> None:
        self._checking = False
        self._check_button.setEnabled(True)

        if isinstance(esito, ConformanceReport):
            self._report.setPlainText(esito.as_text())
            _log.info("Conformità: %s", esito.summary())
        else:
            self._report.setPlainText(f"Verifica non completata: {esito}")

    # ------------------------------------------------------------------ #

    def _frame(self, titolo: str) -> QtWidgets.QFrame:
        riquadro = QtWidgets.QFrame()
        riquadro.setProperty("role", "panel")
        etichetta = QtWidgets.QLabel(titolo)
        etichetta.setProperty("role", "hud")
        layout = QtWidgets.QVBoxLayout(riquadro)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(etichetta)
        return riquadro

    def showEvent(self, event) -> None:
        self._timer.start()
        self._refresh_status()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)
