"""Fixture comuni ai test.

I test del nucleo girano **senza interfaccia**: serve un ``QCoreApplication``
perche' bus e state manager usano segnali e timer Qt, ma nessuna finestra. E'
anche una verifica implicita della regola di dipendenza — se un test del nucleo
richiedesse una ``QApplication``, vorrebbe dire che qualcosa in ``core`` ha
iniziato a dipendere dalla GUI.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# I test si eseguono senza display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.eventbus import EventBus  # noqa: E402
from core.paths import AppPaths  # noqa: E402
from core.qtcompat import QtCore  # noqa: E402
from core.state import StateManager  # noqa: E402


@pytest.fixture(scope="session")
def qt_app() -> Iterator[QtCore.QCoreApplication]:
    """Applicazione Qt minima, condivisa da tutta la sessione di test."""
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    yield app  # type: ignore[misc]


@pytest.fixture
def bus(qt_app: QtCore.QCoreApplication) -> Iterator[EventBus]:
    """Bus in modalita' rigorosa: un payload non conforme fa fallire il test.

    In produzione la modalita' e' permissiva — un evento malformato si scarta —
    ma nei test si vuole l'opposto: che l'errore emerga subito.
    """
    instance = EventBus(strict=True)
    yield instance
    instance.clear()


@pytest.fixture
def state(bus: EventBus) -> Iterator[StateManager]:
    """State manager collegato al bus di test."""
    manager = StateManager(bus)
    yield manager
    manager.shutdown()


@pytest.fixture
def temp_paths(tmp_path: Path) -> AppPaths:
    """Percorsi applicativi isolati, per non toccare la configurazione reale."""
    from core.paths import bundled_root

    return AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        bundled=bundled_root(),
    ).ensure()


@pytest.fixture
def collected(bus: EventBus) -> list:
    """Raccoglie ogni evento pubblicato sul bus durante il test."""
    events: list = []
    bus.subscribe_all(events.append)
    return events
