"""Timeline degli eventi ed Event Inspector.

La timeline si sottoscrive a **tutto** il bus. È uno dei pochi consumatori per
cui questo è legittimo — insieme al pannello Log e alla telemetria — perché il
suo compito è appunto osservare.

Due vincoli imposti dall'uso reale, non dall'estetica:

* **volume**. Uno stream audio produce sedici eventi al secondo; una sessione di
  dieci minuti ne genera decine di migliaia. La lista è limitata e il filtro
  agisce sull'inserimento, non solo sulla visualizzazione.
* **pausa**. Selezionare una riga mentre ne arrivano venti al secondo è
  impossibile. Il pulsante di pausa **congela l'inserimento**, non la raccolta:
  alla ripresa non si è perso nulla.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from typing import Any, Final

from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.qtcompat import Qt, QtGui, QtWidgets, Signal
from ui.devtools.formatting import format_payload, summarize
from ui.theme.theme import Theme

__all__ = ["EventInspector", "EventTimeline"]

#: Righe mantenute nella lista. Oltre, le più vecchie escono.
_MAX_ROWS: Final[int] = 2000

#: Eventi trattenuti mentre la timeline è in pausa.
_PAUSE_BUFFER: Final[int] = 500

#: Colore per prefisso di dominio dell'evento.
_DOMAIN_COLOR: Final[dict[str, str]] = {
    "error": "state.error",
    "link": "state.connecting",
    "agent": "state.thinking",
    "chat": "state.speaking",
    "audio": "state.listening",
    "vision": "state.executing",
    "service": "state.warning",
    "app": "text.muted",
    "ui": "text.muted",
    "system": "text.muted",
    "capabilities": "state.success",
    "identity": "state.success",
    "task": "state.executing",
    "plugin": "accent.coreBright",
}


class EventTimeline(QtWidgets.QWidget):
    """Elenco cronologico degli eventi del bus."""

    selected = Signal(object)
    """Emesso con l':class:`Event` scelto, per l'ispettore."""

    def __init__(
        self, bus: EventBus, theme: Theme, parent: QtWidgets.QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._bus = bus
        self._theme = theme
        self._paused = False
        self._filter = ""
        self._counts: Counter[str] = Counter()
        self._buffer: deque[Event[Any]] = deque(maxlen=_PAUSE_BUFFER)
        self._start = time.time()
        self._seeded = 0
        """Numero d'ordine più alto già mostrato dallo storico.

        Un evento pubblicato da un altro thread è *già* nello storico quando la
        console si apre, ma la sua consegna al thread grafico avviene dopo:
        senza questa soglia comparirebbe due volte, e una timeline che mostra
        eventi che non sono avvenuti è peggio che non averla.
        """

        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Filtra per tipo o contenuto…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_filter)

        self._pause = QtWidgets.QPushButton("Pausa")
        self._pause.setCheckable(True)
        self._pause.setFixedWidth(78)
        self._pause.toggled.connect(self._on_pause)

        clear = QtWidgets.QPushButton("Svuota")
        clear.setFixedWidth(78)
        clear.clicked.connect(self.clear)

        self._list = QtWidgets.QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.setUniformItemSizes(True)
        self._list.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))
        self._list.currentItemChanged.connect(self._on_current_changed)

        self._status = QtWidgets.QLabel("in ascolto")
        self._status.setProperty("role", "muted")

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(self._search, 1)
        controls.addWidget(self._pause)
        controls.addWidget(clear)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(controls)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._status)

        # Lo storico del bus viene ricostruito all'apertura: la console mostra
        # anche ciò che è successo prima che venisse aperta, che è quasi sempre
        # il momento in cui si è deciso di aprirla.
        for event in bus.history():
            # Lo storico va contato oltre che mostrato: altrimenti il totale
            # risulterebbe inferiore alle righe visibili, e un contatore
            # incoerente toglie fiducia a tutto il pannello.
            self._counts[event.key] += 1
            self._seeded = max(self._seeded, event.seq)
            self._append(event)
        self._update_status()

        self._subscription: Subscription = bus.subscribe_all(self._on_event)

    # ------------------------------------------------------------------ #
    # Ingresso
    # ------------------------------------------------------------------ #

    @safe_slot("devtools.timeline")
    def _on_event(self, event: Event[Any]) -> None:
        if event.seq <= self._seeded:
            return  # già mostrato dallo storico: la consegna è solo in ritardo
        self._counts[event.key] += 1
        if self._paused:
            self._buffer.append(event)
            self._update_status()
            return
        self._append(event)
        self._update_status()

    def _append(self, event: Event[Any]) -> None:
        """Aggiunge una riga, se supera il filtro."""
        if not self._matches(event):
            return

        elapsed = event.ts - self._start
        text = f"{elapsed:8.3f}  {event.key:<28} {event.source:<10} {summarize(event.payload)}"

        item = QtWidgets.QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, event)
        item.setForeground(self._color_for(event.key))
        self._list.addItem(item)

        while self._list.count() > _MAX_ROWS:
            self._list.takeItem(0)

        # Scorrimento automatico solo se si è già in fondo: se l'utente sta
        # leggendo una riga più su, trascinarlo via a ogni evento renderebbe la
        # timeline inutilizzabile proprio quando serve.
        scrollbar = self._list.verticalScrollBar()
        if scrollbar.value() >= scrollbar.maximum() - 4:
            self._list.scrollToBottom()

    def _matches(self, event: Event[Any]) -> bool:
        if not self._filter:
            return True
        needle = self._filter
        return needle in event.key.lower() or needle in summarize(event.payload).lower()

    def _color_for(self, key: str) -> QtGui.QBrush:
        domain = key.split(".")[0]
        token = _DOMAIN_COLOR.get(domain, "text.secondary")
        return QtGui.QBrush(self._theme.color(token))

    # ------------------------------------------------------------------ #
    # Controlli
    # ------------------------------------------------------------------ #

    @safe_slot("devtools.timeline")
    def _on_filter(self, text: str) -> None:
        """Riapplica il filtro allo storico del bus."""
        self._filter = text.strip().lower()
        self._list.clear()
        for event in self._bus.history():
            self._append(event)

    @safe_slot("devtools.timeline")
    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self._pause.setText("Riprendi" if paused else "Pausa")
        if paused:
            return
        # Alla ripresa si riversano gli eventi trattenuti, in ordine.
        buffered, self._buffer = list(self._buffer), deque(maxlen=_PAUSE_BUFFER)
        for event in buffered:
            self._append(event)
        self._update_status()

    @safe_slot("devtools.timeline")
    def _on_current_changed(self, current: QtWidgets.QListWidgetItem | None) -> None:
        if current is None:
            return
        self.selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def clear(self) -> None:
        """Svuota la vista, non lo storico del bus."""
        self._list.clear()
        self._counts.clear()
        self._buffer.clear()
        self._start = time.time()
        self._update_status()

    def _update_status(self) -> None:
        total = sum(self._counts.values())
        shown = self._list.count()
        if self._paused:
            self._status.setText(
                f"in pausa · {len(self._buffer)} in attesa · {total} eventi totali"
            )
        else:
            self._status.setText(f"{shown} righe mostrate · {total} eventi totali")

    def top_events(self, limit: int = 8) -> list[tuple[str, int]]:
        """Eventi più frequenti, per la diagnostica."""
        return self._counts.most_common(limit)


class EventInspector(QtWidgets.QWidget):
    """Dettaglio di un singolo evento."""

    def __init__(self, theme: Theme, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._header = QtWidgets.QLabel("Nessun evento selezionato")
        self._header.setProperty("role", "title")
        self._header.setWordWrap(True)

        self._meta = QtWidgets.QLabel("")
        self._meta.setProperty("role", "muted")
        self._meta.setWordWrap(True)

        self._body = QtWidgets.QPlainTextEdit()
        self._body.setReadOnly(True)
        self._body.setFont(QtGui.QFont(str(theme.raw("font.mono", "monospace")), 10))
        self._body.setPlaceholderText(
            "Seleziona un evento nella timeline per vederne il contenuto."
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._header)
        layout.addWidget(self._meta)
        layout.addWidget(self._body, 1)

    @safe_slot("devtools.inspector")
    def show_event(self, event: Event[Any]) -> None:
        """Mostra il contenuto di un evento."""
        if event is None:
            return
        self._header.setText(event.key)
        moment = time.strftime("%H:%M:%S", time.localtime(event.ts))
        self._meta.setText(
            f"sorgente: {event.source}    sequenza: #{event.seq}    ora: {moment}"
            f".{int((event.ts % 1) * 1000):03d}"
        )
        self._body.setPlainText(format_payload(event.payload))
