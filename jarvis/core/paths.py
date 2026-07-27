"""Percorsi di configurazione, log, cache e dati, conformi all'OS.

Il brief collocava ``logs/`` e ``config/`` dentro l'albero del progetto. Per
un'applicazione che parte al login e' la scelta sbagliata (docs §2.6): la
cartella d'installazione puo' essere in sola lettura — ``Program Files`` lo e'
per default — e un aggiornamento cancellerebbe log e preferenze.

Qui il repository conserva solo i **default versionati**; tutto cio' che
l'utente modifica o che l'applicazione produce vive nelle directory standard
della piattaforma.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from platformdirs import PlatformDirs

__all__ = ["AppPaths", "app_paths", "bundled_root"]

_APP_NAME = "Jarvis"
_APP_AUTHOR = "Jarvis"


def bundled_root() -> Path:
    """Radice dei file versionati con l'applicazione (default, asset, temi)."""
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Insieme dei percorsi usati dall'applicazione."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path
    bundled: Path

    @property
    def user_settings(self) -> Path:
        """File delle preferenze utente, scrivibile (``settings.json``)."""
        return self.config_dir / "settings.json"

    @property
    def defaults_file(self) -> Path:
        """Default versionati, in sola lettura (``config/defaults.toml``)."""
        return self.bundled / "config" / "defaults.toml"

    @property
    def env_file(self) -> Path:
        """``.env`` locale, usato solo in sviluppo (vedi docs §8)."""
        return self.bundled / ".env"

    @property
    def layout_file(self) -> Path:
        """Disposizione dei pannelli, salvata in formato leggibile."""
        return self.config_dir / "layout.json"

    @property
    def identity_file(self) -> Path:
        """Identita' persistente di questa installazione (vedi core.identity)."""
        return self.data_dir / "identity.json"

    @property
    def plugins_dir(self) -> Path:
        """Plugin installati dall'utente, fuori dal repository."""
        return self.data_dir / "plugins"

    def ensure(self) -> AppPaths:
        """Crea le directory mancanti.

        Un fallimento non e' fatale: l'applicazione deve partire comunque, in
        modalita' senza persistenza, e dirlo nel log.
        """
        for directory in (self.config_dir, self.data_dir, self.cache_dir, self.log_dir):
            # Permessi negati o disco pieno non sono fatali: si perde la
            # persistenza, non l'avvio.
            with contextlib.suppress(OSError):
                directory.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache(maxsize=1)
def app_paths() -> AppPaths:
    """Percorsi dell'applicazione, calcolati una sola volta."""
    dirs = PlatformDirs(appname=_APP_NAME, appauthor=_APP_AUTHOR, roaming=True)
    return AppPaths(
        config_dir=Path(dirs.user_config_dir),
        data_dir=Path(dirs.user_data_dir),
        cache_dir=Path(dirs.user_cache_dir),
        log_dir=Path(dirs.user_log_dir),
        bundled=bundled_root(),
    ).ensure()
