"""Punto d'ingresso di J.A.R.V.I.S.

Questo file **non contiene logica**. Costruisce i componenti, li registra nel
service registry, avvia i servizi e mostra la finestra. Se dovesse crescere
oltre un centinaio di righe utili, significherebbe che qualcosa che dovrebbe
stare in un modulo e' finito nel bootstrap.

Sequenza di avvio, come da specifica:

1. la GUI parte e si mostra subito, senza attendere nessuno;
2. tenta la connessione al backend in modo asincrono;
3. a connessione riuscita mostra "Jarvis online";
4. se il backend non risponde continua a riprovare, **senza mai bloccarsi**.
"""

from __future__ import annotations

import argparse
import signal
import sys
from typing import Any

from core.capabilities import CapabilityManager
from core.errors import ErrorCondition, install_excepthooks
from core.eventbus import EventBus
from core.events import Empty, ErrorRaised, EventType
from core.frameclock import FrameClock
from core.identity import IdentityService
from core.logging_setup import LogCategory, get_logger, setup_logging
from core.paths import app_paths
from core.qtcompat import QT_BINDING, Qt, QtCore, QtGui, QtWidgets, qt_version
from core.registry import ServiceRegistry
from core.settings import AppSettings, SettingsStore
from core.state.machines import AppState
from core.state.manager import StateManager
from network.service import NetworkService
from ui.main_window import MainWindow
from ui.theme.theme import Theme, load_theme

_log = get_logger(LogCategory.APP, "bootstrap")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Interpreta gli argomenti da riga di comando.

    Gli argomenti sono il livello di configurazione piu' forte: servono a
    scavalcare le preferenze per una singola esecuzione, tipicamente in
    diagnostica.
    """
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Interfaccia desktop di J.A.R.V.I.S."
    )
    parser.add_argument(
        "--transport",
        choices=("websocket", "mock"),
        help="Trasporto verso il backend. 'mock' usa il backend simulato.",
    )
    parser.add_argument("--url", help="URL del backend OpenClaw.")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), help="Verbosita'."
    )
    parser.add_argument(
        "--no-translucent",
        action="store_true",
        help="Disattiva le trasparenze (utile su hardware senza compositing).",
    )
    parser.add_argument(
        "--minimized", action="store_true", help="Parte ridotto nella barra di sistema."
    )
    return parser.parse_args(argv)


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Traduce gli argomenti nel formato della configurazione."""
    overrides: dict[str, dict[str, Any]] = {}
    if args.transport:
        overrides.setdefault("backend", {})["transport"] = args.transport
    if args.url:
        overrides.setdefault("backend", {})["url"] = args.url
    if args.log_level:
        overrides.setdefault("logging", {})["level"] = args.log_level
    if args.no_translucent:
        overrides.setdefault("window", {})["translucent"] = False
    if args.minimized:
        overrides.setdefault("window", {})["start_minimized"] = True
    return overrides


def build_registry(settings: AppSettings, bus: EventBus) -> ServiceRegistry:
    """Registra i componenti dell'applicazione.

    E' l'unico punto in cui si dichiara *come* si costruisce Jarvis. Le fasi
    successive aggiungono righe qui — servizi di rete, audio, visione — senza
    modificare nulla di quanto gia' registrato.
    """
    registry = ServiceRegistry(bus)
    registry.register_instance(EventBus, bus)
    registry.register_instance(AppSettings, settings)

    registry.register(
        Theme, lambda _: load_theme(settings.ui.theme), name="theme", lazy=False
    )
    registry.register(
        StateManager, lambda r: StateManager(r.resolve(EventBus)), name="state", critical=True
    )
    registry.register(
        IdentityService,
        lambda r: IdentityService(r.resolve(EventBus)),
        name="identity",
        critical=True,
    )
    registry.register(
        CapabilityManager,
        lambda r: CapabilityManager(r.resolve(EventBus)),
        name="capabilities",
        critical=True,
    )
    registry.register(
        FrameClock,
        lambda _: FrameClock(target_fps=settings.ui.target_fps),
        name="frameclock",
    )
    # La rete non e' critica: se il backend non esiste, la GUI deve comunque
    # partire e continuare a riprovare. E' il requisito centrale della sequenza
    # di avvio descritta nel brief.
    registry.register(
        NetworkService,
        lambda r: NetworkService(
            r.resolve(EventBus),
            r.resolve(StateManager),
            r.resolve(IdentityService),
            r.resolve(CapabilityManager),
            settings.backend,
        ),
        name="network",
        depends_on=[StateManager, IdentityService, CapabilityManager],
        lazy=False,
    )
    return registry


def _install_error_bridge(bus: EventBus, state: StateManager) -> None:
    """Collega le reti di sicurezza allo stato e al bus.

    Da qui in poi qualunque eccezione non catturata, in qualunque thread,
    diventa una condizione visibile nell'interfaccia invece di una traccia su
    stderr che nessuno legge.
    """

    def sink(condition: ErrorCondition) -> None:
        state.raise_error(condition)
        bus.publish(EventType.ERROR, ErrorRaised(condition), source="excepthook")

    install_excepthooks(sink)


def _configure_application(app: QtWidgets.QApplication, theme: Theme) -> None:
    """Applica tema, carattere e impostazioni globali."""
    app.setApplicationName("Jarvis")
    app.setOrganizationName("Jarvis")
    app.setApplicationDisplayName("J.A.R.V.I.S.")
    # Chiudere l'ultima finestra non deve terminare il processo: l'assistente
    # resta nella barra di sistema.
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())

    font = QtGui.QFont()
    font.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def main(argv: list[str] | None = None) -> int:
    """Avvia l'applicazione. Restituisce il codice di uscita del processo."""
    args = parse_args(argv)
    paths = app_paths()

    store = SettingsStore(paths)
    store.update({})  # forza la validazione iniziale
    settings = store.current
    overrides = _cli_overrides(args)
    if overrides:
        from core.settings import load_settings

        settings = load_settings(paths, cli_overrides=overrides)

    setup_logging(
        paths.log_dir,
        level=settings.logging.level,
        console=settings.logging.console,
        max_bytes=settings.logging.max_bytes,
        backup_count=settings.logging.backup_count,
        ring_capacity=settings.logging.ring_capacity,
    )
    _log.info("Avvio di J.A.R.V.I.S. — %s %s", QT_BINDING, qt_version())
    _log.info("Configurazione: %s", paths.config_dir)

    # Il ridimensionamento per DPI e' automatico in Qt 6; resta da scegliere la
    # politica di arrotondamento. PassThrough evita il testo sfocato sui monitor
    # con scala frazionaria (125%, 150%), oggi la norma su Windows.
    QtGui.QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QtWidgets.QApplication(sys.argv[:1])

    bus = EventBus(history=settings.logging.ring_capacity)
    registry = build_registry(settings, bus)

    try:
        registry.start_all()
    except Exception as exc:
        _log.critical("Avvio interrotto: %s", exc)
        QtWidgets.QMessageBox.critical(
            None, "J.A.R.V.I.S.", f"Avvio non riuscito:\n{exc}"
        )
        return 1

    theme = registry.resolve(Theme)
    state = registry.resolve(StateManager)
    clock = registry.resolve(FrameClock)
    _configure_application(app, theme)
    _install_error_bridge(bus, state)

    window = MainWindow(bus, state, clock, theme, settings)

    # Ctrl+C da terminale: senza questo, il ciclo di eventi Qt ignora SIGINT e
    # l'unico modo di fermare l'applicazione in sviluppo e' ucciderla.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    interrupt_timer = QtCore.QTimer()
    interrupt_timer.start(400)
    interrupt_timer.timeout.connect(lambda: None)

    if settings.window.start_minimized:
        _log.info("Avvio ridotto nella barra di sistema")
    else:
        window.show()

    clock.start()
    state.set_app_state(AppState.RUNNING, reason="interfaccia pronta")
    bus.publish(EventType.APP_READY, Empty(), source="bootstrap")

    app.aboutToQuit.connect(lambda: _shutdown(registry, state, clock))
    return app.exec()


def _shutdown(registry: ServiceRegistry, state: StateManager, clock: FrameClock) -> None:
    """Arresto ordinato: prima si dichiara la chiusura, poi si spegne."""
    _log.info("Chiusura in corso")
    state.set_app_state(AppState.SHUTTING_DOWN, reason="uscita richiesta")
    clock.stop()
    registry.stop_all()
    state.shutdown()
    _log.info("Chiusura completata")


if __name__ == "__main__":
    raise SystemExit(main())
