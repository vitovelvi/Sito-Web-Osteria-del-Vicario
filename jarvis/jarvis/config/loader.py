"""Caricamento e accesso alla configurazione.

La configurazione è l'unica fonte di verità per percorsi, modelli, porte e
parametri: nessun valore operativo è hardcoded nel resto del codice.

Formati supportati:
    - JSON (sempre, via stdlib)
    - YAML (se PyYAML è installato)

Le chiavi si leggono con percorsi puntati: ``config.get("llm.providers.ollama.model")``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:  # PyYAML è opzionale.
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dipende dall'ambiente
    yaml = None


class ConfigError(Exception):
    """Errore di caricamento o di accesso alla configurazione."""


class Config:
    """Vista immutabile, ad accesso puntato, su un albero di configurazione.

    Args:
        data: albero di configurazione (dict annidati).
        source: percorso del file di provenienza, se esiste.
    """

    def __init__(self, data: dict[str, Any], source: Path | None = None) -> None:
        self._data = data
        self.source = source

    def get(self, path: str, default: Any = None) -> Any:
        """Ritorna il valore alla chiave puntata ``path`` o ``default``."""
        node: Any = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def require(self, path: str) -> Any:
        """Come :meth:`get`, ma solleva :class:`ConfigError` se assente."""
        sentinel = object()
        value = self.get(path, sentinel)
        if value is sentinel:
            raise ConfigError(f"Chiave di configurazione mancante: {path!r}")
        return value

    def section(self, path: str) -> "Config":
        """Ritorna una sotto-configurazione (dict vuoto se assente)."""
        value = self.get(path, {})
        if not isinstance(value, dict):
            raise ConfigError(f"La chiave {path!r} non è una sezione")
        return Config(value, self.source)

    def resolve_path(self, path: str, default: str) -> Path:
        """Risolve una chiave che rappresenta un percorso su filesystem.

        I percorsi relativi sono ancorati alla directory del file di
        configurazione (o alla cwd se la config non proviene da file).
        """
        raw = Path(str(self.get(path, default)))
        if raw.is_absolute():
            return raw
        base = self.source.parent.parent if self.source else Path.cwd()
        return base / raw

    def as_dict(self) -> dict[str, Any]:
        """Copia profonda serializzabile dell'albero di configurazione."""
        return json.loads(json.dumps(self._data))


def _read_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise ConfigError(
                f"{path} è YAML ma PyYAML non è installato (pip install PyYAML)"
            )
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: la radice della configurazione deve essere un oggetto")
    return data


def _candidate_paths(explicit: str | os.PathLike[str] | None) -> list[Path]:
    if explicit is not None:
        return [Path(explicit)]
    project_root = Path(__file__).resolve().parent.parent.parent
    names = ("jarvis.yaml", "jarvis.yml", "jarvis.json")
    return [project_root / "config" / name for name in names]


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Carica la configurazione di JARVIS.

    Args:
        path: file esplicito; se ``None`` cerca ``config/jarvis.{yaml,yml,json}``
            nella radice del progetto.

    Raises:
        ConfigError: se nessun file valido è disponibile.
    """
    for candidate in _candidate_paths(path):
        if candidate.is_file():
            return Config(_read_file(candidate), source=candidate.resolve())
    raise ConfigError(
        "Nessun file di configurazione trovato: atteso config/jarvis.json "
        "oppure un percorso esplicito valido"
    )
