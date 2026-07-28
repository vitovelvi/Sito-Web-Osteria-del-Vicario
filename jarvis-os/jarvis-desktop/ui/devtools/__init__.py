"""Strumenti di sviluppo e manutenzione.

Timeline degli eventi, Event Inspector, monitor dei servizi, diagnostica in
tempo reale e vista del traffico JCP. Sono strumenti pensati per il lungo
periodo: la maggior parte del costo di manutenzione di un'interfaccia a eventi
sta nel capire *cosa è successo*, e senza questi pannelli la risposta si cerca
nei log a posteriori.
"""

from ui.devtools.console import DeveloperConsole
from ui.devtools.session import SessionPanel

__all__ = ["DeveloperConsole", "SessionPanel"]
