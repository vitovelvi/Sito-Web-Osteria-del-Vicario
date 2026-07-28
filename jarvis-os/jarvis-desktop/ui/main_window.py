"""Finestra principale: compone il guscio, il nucleo e l'HUD.

Questa classe **assembla**, non decide. Non contiene logica di stato, di rete o
di dominio: riceve i componenti gia' costruiti e li dispone. Se in futuro
comparira' logica qui dentro, sara' il primo segnale che l'architettura sta
scivolando.
"""

from __future__ import annotations

from typing import Final

from core.capabilities import CapabilityManager
from core.errors import safe_slot
from core.eventbus import Event, EventBus, Subscription
from core.events import EventType, LinkStatus, NotificationRequest
from core.frameclock import FrameClock
from core.logging_setup import LogCategory, get_logger
from core.missions.engine import MissionEngine
from core.qtcompat import Qt, QtCore, QtGui, QtWidgets
from core.settings import AppSettings
from core.state.machines import AppState
from core.state.manager import StateManager
from ui.chrome import TitleBar
from ui.frameless import FramelessWindow
from ui.hud import StatusStrip
from ui.notifications import ToastManager
from ui.ops import ConfirmationLayer, OperationsSidebar
from ui.reactor.widget import CoreReactorWidget
from ui.theme.theme import Theme

__all__ = ["MainWindow"]

_log = get_logger(LogCategory.UI, "main_window")

#: Chiavi con cui si persiste la geometria.
_GEOMETRY_KEY: Final[str] = "window/geometry"


class MainWindow(FramelessWindow):
    """Finestra principale di J.A.R.V.I.S."""

    def __init__(
        self,
        bus: EventBus,
        state: StateManager,
        clock: FrameClock,
        theme: Theme,
        settings: AppSettings,
        missions: MissionEngine | None = None,
        capabilities: CapabilityManager | None = None,
        sender=None,
    ) -> None:
        super().__init__(theme, translucent=settings.window.translucent)
        self._missions = missions
        self._capabilities = capabilities
        self._sender = sender
        self._bus = bus
        self._state = state
        self._clock = clock
        self._theme = theme
        self._settings = settings

        self.setWindowTitle("J.A.R.V.I.S.")
        self.setMinimumSize(settings.window.min_width, settings.window.min_height)
        self.resize(settings.window.width, settings.window.height)

        self._build_layout()
        self._toasts = ToastManager(
            bus,
            self.surface,
            theme,
            # I toast si impilano sopra la striscia di stato, non su di essa.
            bottom_offset=self._status.sizeHint().height() + 20,
        )
        self._confirmations = (
            ConfirmationLayer(
                bus, missions, self.surface, theme,
                top_offset=theme.px("window.chromeHeight", 44) + 12,
            )
            if missions is not None
            else None
        )
        self._tray = self._build_tray()

        # F9 appartiene alla finestra, non agli strumenti di sviluppo: la barra
        # operativa e' una funzione dell'utente. Registrarla insieme alla
        # console la farebbe sparire in una build distribuita, dove la console
        # non viene collegata — e chi avesse nascosto la barra non avrebbe piu'
        # alcun modo di riaprirla.
        self._sidebar_shortcut = QtGui.QShortcut(QtGui.QKeySequence("F9"), self)
        self._sidebar_shortcut.activated.connect(self.toggle_sidebar)

        self._subscriptions: list[Subscription] = [
            bus.subscribe(EventType.LINK_STATE_CHANGED, self._on_link),
        ]

        # Sospensione automatica quando la finestra resta nascosta a lungo:
        # un'applicazione che parte al login e vive tutto il giorno non deve
        # animare pixel invisibili.
        self._standby_timer = QtCore.QTimer(self)
        self._standby_timer.setSingleShot(True)
        self._standby_timer.timeout.connect(self._enter_standby)
        self._standby_delay_ms = settings.app.standby_after_hidden_s * 1000

        self._console: QtWidgets.QWidget | None = None
        self._restore_geometry()
        if settings.window.always_on_top:
            self.set_always_on_top(True)

    # ------------------------------------------------------------------ #
    # Composizione
    # ------------------------------------------------------------------ #

    def _build_layout(self) -> None:
        """Dispone barra del titolo, area centrale e striscia di stato."""
        self._title_bar = TitleBar(
            self._bus, self, height=self._theme.px("window.chromeHeight", 44)
        )
        self._reactor = CoreReactorWidget(
            self._bus,
            self._clock,
            self._theme,
            reduced_motion=self._settings.ui.reduced_motion,
        )
        self._status = StatusStrip(self._bus, self._theme)

        # Area centrale: il nucleo occupa lo spazio, i pannelli della fase 4 si
        # inseriranno ai suoi lati senza modificare questa struttura.
        self._stage = QtWidgets.QWidget()
        stage_layout = QtWidgets.QHBoxLayout(self._stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.addWidget(self._reactor, 1)

        # Barra operativa: presente solo se il livello operativo esiste. La
        # finestra non decide se il backend gestisce missioni — lo chiede alle
        # capability, come per ogni altra funzione.
        self._sidebar: OperationsSidebar | None = None
        if self._missions is not None and self._capabilities is not None:
            self._sidebar = OperationsSidebar(
                self._bus, self._missions, self._capabilities, self._theme, self._sender
            )
            stage_layout.addWidget(self._sidebar)

        layout = QtWidgets.QVBoxLayout(self.surface)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._title_bar)
        layout.addWidget(self._stage, 1)

        footer = QtWidgets.QHBoxLayout()
        footer.setContentsMargins(14, 0, 14, 14)
        footer.addWidget(self._status)
        layout.addLayout(footer)

    def toggle_sidebar(self) -> None:
        """Mostra o nasconde la barra operativa (F9)."""
        if self._sidebar is None:
            return
        # Si commuta la *preferenza*, non la visibilita': con un backend che non
        # dichiara missioni la barra e' nascosta comunque, e derivare la scelta
        # da cio' che si vede la bloccherebbe su "voluta" per sempre.
        self._sidebar.set_wanted(not self._sidebar.is_wanted)

    def attach_developer_console(self, console: QtWidgets.QWidget) -> None:
        """Collega la Developer Console alla scorciatoia F12 e al menu di sistema.

        La finestra non sa come si costruisce la console: la riceve gia' pronta.
        E' cio' che permette di avviare Jarvis senza strumenti di sviluppo — in
        una build distribuita basta non chiamare questo metodo.
        """
        self._console = console
        shortcut = QtGui.QShortcut(QtGui.QKeySequence("F12"), self)
        # ApplicationShortcut: la scorciatoia funziona anche quando il fuoco e'
        # sulla console stessa, cosi' F12 la chiude come l'ha aperta.
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(console.toggle)

        if self._tray is not None and (menu := self._tray.contextMenu()) is not None:
            # Va inserita prima di "Esci": il comando di uscita resta l'ultimo,
            # dove l'utente si aspetta di trovarlo.
            quit_action = menu.actions()[-1]
            action = QtGui.QAction("Developer Console", menu)
            action.triggered.connect(console.toggle)
            menu.insertAction(quit_action, action)

    @property
    def stage(self) -> QtWidgets.QWidget:
        """Area centrale, punto d'innesto dei pannelli."""
        return self._stage

    @property
    def reactor(self) -> CoreReactorWidget:
        """Widget del nucleo, esposto per test e pannelli di prova."""
        return self._reactor

    # ------------------------------------------------------------------ #
    # Icona nella barra di sistema
    # ------------------------------------------------------------------ #

    def _build_tray(self) -> QtWidgets.QSystemTrayIcon | None:
        """Crea l'icona di sistema, se la piattaforma la supporta.

        Indispensabile per un'applicazione che parte al login: senza, chiudere
        la finestra significherebbe perdere ogni modo di richiamarla.
        """
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            _log.info("Barra di sistema non disponibile su questa piattaforma")
            return None

        tray = QtWidgets.QSystemTrayIcon(self)
        tray.setIcon(self._tray_icon())
        tray.setToolTip("J.A.R.V.I.S.")

        menu = QtWidgets.QMenu()
        menu.addAction("Mostra", self._show_from_tray)
        menu.addAction("Nascondi", self.hide)
        menu.addSeparator()
        menu.addAction("Esci", self._quit)
        tray.setContextMenu(menu)

        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _tray_icon(self) -> QtGui.QIcon:
        """Disegna l'icona: un anello con nucleo, negli stessi colori del tema."""
        size = 64
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        accent = self._theme.color("accent.core")

        pen = QtGui.QPen(accent, 4)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QtCore.QPointF(size / 2, size / 2), 24, 24)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._theme.color("accent.coreBright"))
        painter.drawEllipse(QtCore.QPointF(size / 2, size / 2), 10, 10)
        painter.end()

        return QtGui.QIcon(pixmap)

    @safe_slot("ui.window")
    def _on_tray_activated(self, reason: object) -> None:
        if reason == QtWidgets.QSystemTrayIcon.ActivationReason.Trigger:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        """Riporta in primo piano la finestra, ovunque fosse."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        """Chiude davvero l'applicazione, saltando la riduzione a icona."""
        self._closing_for_real = True
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()

    # ------------------------------------------------------------------ #
    # Eventi
    # ------------------------------------------------------------------ #

    @safe_slot("ui.window")
    def _on_link(self, event: Event[LinkStatus]) -> None:
        """Notifica i cambi di stato del canale, senza invadere.

        Solo le transizioni che l'utente percepisce come eventi: la connessione
        riuscita e la caduta. I tentativi intermedi restano nell'HUD, altrimenti
        una rete instabile produrrebbe una raffica di toast.
        """
        state = event.payload.state
        if state == "online":
            self._bus.publish(
                EventType.NOTIFICATION_REQUESTED,
                NotificationRequest(title="Jarvis online", kind="success"),
                source="ui.window",
            )
        elif state == "offline" and event.payload.reason:
            self._bus.publish(
                EventType.NOTIFICATION_REQUESTED,
                NotificationRequest(
                    title="Connessione persa",
                    body=event.payload.reason,
                    kind="warning",
                ),
                source="ui.window",
            )

    # ------------------------------------------------------------------ #
    # Ciclo di vita della finestra
    # ------------------------------------------------------------------ #

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        """Riavvia il clock e annulla la sospensione programmata."""
        self._standby_timer.stop()
        if not self._clock.is_running:
            self._clock.start()
        if self._state.app_state is AppState.STANDBY:
            self._state.set_app_state(AppState.RUNNING, reason="finestra mostrata")
        super().showEvent(event)

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        """Ferma il clock e programma la sospensione."""
        self._clock.stop()
        if self._standby_delay_ms > 0:
            self._standby_timer.start(self._standby_delay_ms)
        super().hideEvent(event)

    def _enter_standby(self) -> None:
        """Porta l'applicazione in standby dopo un'assenza prolungata."""
        if self.isVisible():
            return
        self._state.set_app_state(AppState.STANDBY, reason="finestra nascosta a lungo")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Chiudere la finestra la nasconde: l'applicazione resta disponibile.

        E' il comportamento atteso da un assistente sempre presente. Con la
        barra di sistema assente si chiude davvero, altrimenti l'utente non
        avrebbe piu' modo di riaprirla.
        """
        self._save_geometry()

        if getattr(self, "_closing_for_real", False) or self._tray is None:
            if self._console is not None:
                self._console.close()
            for subscription in self._subscriptions:
                subscription.unsubscribe()
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()
        self._bus.publish(
            EventType.NOTIFICATION_REQUESTED,
            NotificationRequest(
                title="Jarvis è ancora attivo",
                body="Richiamalo dall'icona nella barra di sistema.",
                kind="info",
            ),
            source="ui.window",
        )

    # ------------------------------------------------------------------ #
    # Geometria
    # ------------------------------------------------------------------ #

    def _settings_store(self) -> QtCore.QSettings:
        return QtCore.QSettings("Jarvis", "JarvisDesktop")

    def _save_geometry(self) -> None:
        try:
            self._settings_store().setValue(_GEOMETRY_KEY, self.saveGeometry())
        except Exception:
            _log.exception("Geometria non salvata")

    def _restore_geometry(self) -> None:
        """Ripristina posizione e dimensione della sessione precedente.

        Se lo schermo su cui era la finestra non esiste piu' — configurazione
        molto comune con i portatili agganciati a un monitor esterno — Qt la
        riporterebbe fuori dall'area visibile. Si verifica quindi che la
        geometria ripristinata intersechi almeno uno schermo.
        """
        try:
            saved = self._settings_store().value(_GEOMETRY_KEY)
            if not saved or not self.restoreGeometry(saved):
                return
        except Exception:
            _log.exception("Geometria non ripristinata")
            return

        for screen in QtWidgets.QApplication.screens():
            if screen.availableGeometry().intersects(self.geometry()):
                return

        _log.info("Geometria salvata fuori dagli schermi disponibili: si ricentra")
        self.resize(self._settings.window.width, self._settings.window.height)
        primary = QtWidgets.QApplication.primaryScreen()
        if primary is not None:
            self.move(primary.availableGeometry().center() - self.rect().center())
