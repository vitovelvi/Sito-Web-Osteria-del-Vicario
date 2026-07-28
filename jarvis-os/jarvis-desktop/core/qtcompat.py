"""Livello di astrazione sul binding Qt.

Tutto il progetto importa Qt **esclusivamente da questo modulo**::

    from core.qtcompat import QtCore, QtGui, QtWidgets, Signal, Slot, Qt

Motivazione (docs §2.1): PySide6 e' LGPLv3 e permette la distribuzione di
un'applicazione proprietaria; PyQt6 e' GPLv3 o licenza commerciale. Il default
e' quindi PySide6, ma le due API differiscono in pochi nomi. Concentrandoli qui,
cambiare binding significa modificare un solo file invece di sessanta.

Il binding si sceglie con la variabile d'ambiente ``JARVIS_QT_BINDING``
(``pyside6`` | ``pyqt6``); se il binding richiesto non e' installato si ricade
sull'altro, perche' un'interfaccia che non parte e' peggio di un'interfaccia che
parte con il binding secondario.
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType
from typing import Any, Final

__all__ = [
    "QT_BINDING",
    "Property",
    "Qt",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "Signal",
    "Slot",
    "qt_version",
]

_ENV_VAR: Final[str] = "JARVIS_QT_BINDING"
_PREFERRED: Final[str] = "pyside6"
_SUPPORTED: Final[tuple[str, ...]] = ("pyside6", "pyqt6")


def _candidate_order() -> tuple[str, ...]:
    """Restituisce i binding da provare, nell'ordine, in base all'ambiente."""
    requested = os.environ.get(_ENV_VAR, _PREFERRED).strip().lower()
    if requested not in _SUPPORTED:
        requested = _PREFERRED
    return (requested, *(b for b in _SUPPORTED if b != requested))


def _import_binding() -> tuple[str, ModuleType, ModuleType, ModuleType]:
    """Importa il primo binding disponibile.

    :raises ImportError: se nessun binding Qt e' installato.
    """
    errors: list[str] = []
    for name in _candidate_order():
        package = "PySide6" if name == "pyside6" else "PyQt6"
        try:
            core = importlib.import_module(f"{package}.QtCore")
            gui = importlib.import_module(f"{package}.QtGui")
            widgets = importlib.import_module(f"{package}.QtWidgets")
        except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
            errors.append(f"{package}: {exc}")
            continue
        return name, core, gui, widgets

    raise ImportError(
        "Nessun binding Qt disponibile. Installa PySide6 (consigliato) "
        "oppure PyQt6.\nDettagli:\n  " + "\n  ".join(errors)
    )


QT_BINDING, QtCore, QtGui, QtWidgets = _import_binding()

# --- Normalizzazione dei nomi divergenti fra i due binding -------------------
#
# PySide6 usa Signal/Slot/Property; PyQt6 usa pyqtSignal/pyqtSlot/pyqtProperty.
# Il resto delle API Qt6 e' allineato (enum scoped inclusi), quindi non serve
# altro adattamento.

if QT_BINDING == "pyside6":
    Signal: Any = QtCore.Signal
    Slot: Any = QtCore.Slot
    Property: Any = QtCore.Property
else:  # pragma: no cover - percorso attivo solo con PyQt6 installato
    Signal = QtCore.pyqtSignal
    Slot = QtCore.pyqtSlot
    Property = QtCore.pyqtProperty

Qt: Any = QtCore.Qt


def qt_version() -> str:
    """Versione di Qt sottostante, per diagnostica e handshake."""
    return str(QtCore.qVersion())
