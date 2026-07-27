"""Tema come **dato**, non come codice sparso.

I colori vivono in ``tokens.json``, non nei widget. La differenza si vede negli
anni: cambiare l'accento di un'interfaccia con i colori scritti nei fogli di
stile significa cercare la stessa stringa in trenta file e dimenticarne due.
Qui si modifica un valore e cambia tutto, incluso il nucleo — che non usa QSS ma
legge gli stessi token.

Il foglio di stile Qt viene **generato** dai token, non scritto a mano. Nota
pratica: ``setStyleSheet`` e' costoso e invalida la cache di stile del widget e
dei figli. Va applicato una volta all'avvio e al cambio tema, mai dentro un
gestore di eventi o durante un'animazione.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.logging_setup import LogCategory, get_logger
from core.qtcompat import QtGui

__all__ = ["Theme", "load_theme"]

_log = get_logger(LogCategory.UI, "theme")

_TOKENS_DIR = Path(__file__).resolve().parent


class Theme:
    """Accesso tipizzato ai design token e generazione del foglio di stile."""

    def __init__(self, tokens: dict[str, Any]) -> None:
        self._tokens = tokens

    # ------------------------------------------------------------------ #
    # Accesso ai token
    # ------------------------------------------------------------------ #

    def raw(self, path: str, default: Any = None, *, quiet: bool = False) -> Any:
        """Legge un token per percorso puntato (``color.accent.core``).

        :param quiet: sopprime l'avviso di token assente. Serve a chi tenta piu'
            percorsi di proposito, come :meth:`color`.
        """
        cursor: Any = self._tokens
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                if not quiet:
                    _log.warning("Token '%s' assente: si usa il valore di ripiego", path)
                return default
            cursor = cursor[part]
        return cursor

    def color(self, path: str, alpha: int | None = None) -> QtGui.QColor:
        """Colore da token, con alpha opzionale (0-255).

        Il percorso viene cercato prima sotto ``color.`` e poi come percorso
        assoluto: i colori non appartengono tutti alla tavolozza — quello
        dell'ombra vive sotto ``elevation`` — e obbligare il chiamante a sapere
        dove sta ciascuno sarebbe un invito a sbagliare.
        """
        value = self.raw(f"color.{path}", None, quiet=True)
        if value is None:
            value = self.raw(path, "#ff00ff")

        color = QtGui.QColor(str(value))
        if not color.isValid():
            _log.warning("Colore '%s' non valido: '%s'", path, value)
            color = QtGui.QColor("#ff00ff")  # magenta: si nota subito in revisione
        if alpha is not None:
            color.setAlpha(max(0, min(255, alpha)))
        return color

    def hex(self, path: str) -> str:
        """Colore in forma ``#rrggbb``, per il foglio di stile."""
        return self.color(path).name()

    def px(self, path: str, default: int = 0) -> int:
        """Valore numerico intero (raggi, spaziature, dimensioni)."""
        value = self.raw(path, default)
        return int(value) if isinstance(value, (int, float)) else default

    def ms(self, name: str) -> int:
        """Durata di animazione dal gruppo ``motion``."""
        return self.px(f"motion.{name}", 240)

    def state_color(self, mode: str) -> QtGui.QColor:
        """Colore associato a una modalita' visiva.

        E' il punto in cui il tema e lo state manager si incontrano: la
        modalita' e' un dato del dominio, il colore una scelta del tema, e
        nessuno dei due conosce l'altro.
        """
        return self.color(f"state.{mode}", alpha=None)

    @property
    def name(self) -> str:
        return str(self._tokens.get("name", "dark-mcu"))

    # ------------------------------------------------------------------ #
    # Foglio di stile
    # ------------------------------------------------------------------ #

    def qss(self) -> str:
        """Genera il foglio di stile completo dai token."""
        t = self
        return f"""
/* Generato da ui/theme/theme.py — non modificare a mano: cambiare tokens.json */

QWidget {{
    color: {t.hex("text.primary")};
    font-family: {t.raw("font.family")};
    font-size: {t.px("font.size.md", 13)}px;
    background: transparent;
}}

QWidget#rootSurface {{
    background-color: {t.hex("bg.base")};
    border: 1px solid {t.hex("border.default")};
    border-radius: {t.px("radius.xl", 18)}px;
}}

QLabel[role="hud"] {{
    color: {t.hex("text.secondary")};
    font-size: {t.px("font.size.xs", 10)}px;
    letter-spacing: {t.raw("font.tracking.hud", 1.6)}px;
    text-transform: uppercase;
}}

QLabel[role="title"] {{
    color: {t.hex("text.primary")};
    font-size: {t.px("font.size.md", 13)}px;
    font-weight: {t.px("font.weight.medium", 500)};
    letter-spacing: {t.raw("font.tracking.hud", 1.6)}px;
}}

QLabel[role="muted"] {{
    color: {t.hex("text.muted")};
    font-size: {t.px("font.size.sm", 11)}px;
}}

QFrame[role="panel"] {{
    background-color: {t.hex("bg.panel")};
    border: 1px solid {t.hex("border.subtle")};
    border-radius: {t.px("radius.lg", 14)}px;
}}

QFrame[role="separator"] {{
    background-color: {t.hex("border.subtle")};
    max-height: 1px;
    border: none;
}}

QPushButton {{
    background-color: {t.hex("bg.elevated")};
    border: 1px solid {t.hex("border.default")};
    border-radius: {t.px("radius.md", 8)}px;
    padding: {t.px("space.sm", 8)}px {t.px("space.md", 14)}px;
    color: {t.hex("text.primary")};
}}
QPushButton:hover {{ background-color: {t.hex("bg.hover")};
                     border-color: {t.hex("border.strong")}; }}
QPushButton:pressed {{ background-color: {t.hex("bg.active")}; }}
QPushButton:disabled {{ color: {t.hex("text.muted")};
                        border-color: {t.hex("border.subtle")};
                        background-color: {t.hex("bg.panel")}; }}

QPushButton[role="chrome"] {{
    background: transparent;
    border: none;
    border-radius: {t.px("radius.sm", 4)}px;
    padding: {t.px("space.xs", 4)}px;
    color: {t.hex("text.secondary")};
}}
QPushButton[role="chrome"]:hover {{ background-color: {t.hex("bg.hover")};
                                    color: {t.hex("text.primary")}; }}
QPushButton[role="chrome"][danger="true"]:hover {{
    background-color: {t.hex("state.error")};
    color: {t.hex("text.inverse")};
}}

QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {t.hex("bg.overlay")};
    border: 1px solid {t.hex("border.default")};
    border-radius: {t.px("radius.md", 8)}px;
    padding: {t.px("space.sm", 8)}px;
    selection-background-color: {t.hex("accent.coreDim")};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {t.hex("accent.core")};
}}

QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t.hex("border.strong")};
    border-radius: 4px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.hex("accent.coreDim")}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background-color: {t.hex("bg.elevated")};
    color: {t.hex("text.primary")};
    border: 1px solid {t.hex("border.default")};
    border-radius: {t.px("radius.sm", 4)}px;
    padding: {t.px("space.xs", 4)}px {t.px("space.sm", 8)}px;
}}

QMenu {{
    background-color: {t.hex("bg.elevated")};
    border: 1px solid {t.hex("border.default")};
    border-radius: {t.px("radius.md", 8)}px;
    padding: {t.px("space.xs", 4)}px;
}}
QMenu::item {{
    padding: {t.px("space.sm", 8)}px {t.px("space.md", 14)}px;
    border-radius: {t.px("radius.sm", 4)}px;
}}
QMenu::item:selected {{ background-color: {t.hex("bg.hover")}; }}
QMenu::separator {{ height: 1px; background: {t.hex("border.subtle")};
                    margin: {t.px("space.xs", 4)}px 0; }}
"""


@lru_cache(maxsize=4)
def load_theme(name: str = "dark-mcu") -> Theme:
    """Carica un tema per nome.

    Se il file non e' leggibile si ricade sui token minimi incorporati:
    un'interfaccia senza tema resta usabile, un'interfaccia che non parte no.
    """
    path = _TOKENS_DIR / ("tokens.json" if name == "dark-mcu" else f"tokens-{name}.json")
    try:
        return Theme(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        _log.error("Tema '%s' non caricabile (%s): si usano i valori minimi", name, exc)
        return Theme(_FALLBACK_TOKENS)


#: Token minimi di sopravvivenza, usati solo se ``tokens.json`` e' illeggibile.
_FALLBACK_TOKENS: dict[str, Any] = {
    "name": "fallback",
    "color": {
        "bg": {"base": "#070b12", "panel": "#0c121c", "elevated": "#111a27",
               "overlay": "#0a0f18", "hover": "#16202f", "active": "#1c2a3d"},
        "border": {"subtle": "#182334", "default": "#22314a", "strong": "#2f4763"},
        "text": {"primary": "#dce8f7", "secondary": "#8ba0bd", "muted": "#546881",
                 "inverse": "#050810"},
        "accent": {"core": "#3fa9f5", "coreDim": "#1d6ba8", "coreBright": "#8fd4ff",
                   "glow": "#2a8fe0"},
        "state": {"idle": "#3fa9f5", "listening": "#37d0d6", "thinking": "#6b8cff",
                  "executing": "#c88bff", "speaking": "#4fc3f7", "success": "#5ef2c4",
                  "error": "#ff4d5e", "warning": "#ffb454", "offline": "#41546e",
                  "standby": "#243347", "boot": "#2a6ea8", "connecting": "#4a8fd0"},
    },
    "radius": {"sm": 4, "md": 8, "lg": 14, "xl": 18, "pill": 999},
    "space": {"xs": 4, "sm": 8, "md": 14, "lg": 22, "xl": 34},
    "font": {"family": "sans-serif", "mono": "monospace",
             "size": {"xs": 10, "sm": 11, "md": 13, "lg": 16, "xl": 22},
             "weight": {"regular": 400, "medium": 500, "bold": 600},
             "tracking": {"hud": 1.6}},
    "elevation": {"shadowColor": "#000000", "shadowAlpha": 160, "shadowBlur": 34,
                  "shadowOffsetY": 8},
    "motion": {"fast": 140, "normal": 240, "slow": 420, "scene": 700},
    "window": {"chromeHeight": 44, "resizeMargin": 6, "shadowMargin": 22},
}
