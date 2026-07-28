"""Configurazione tipizzata e stratificata.

Precedenza, dal piu' debole al piu' forte::

    config/defaults.toml  →  settings.json (utente)  →  variabili d'ambiente
                                                     →  argomenti da riga di comando

Ogni livello sovrascrive solo le chiavi che nomina: modificare una preferenza
non congela le altre ai valori di quel momento, quindi i default aggiornati in
una nuova versione arrivano davvero all'utente.

Tutto e' validato con Pydantic. Una configurazione errata produce un messaggio
comprensibile all'avvio e **il ritorno ai default**, non un ``KeyError`` a meta'
sessione: un file di preferenze corrotto non deve impedire a Jarvis di partire.

Nessun segreto qui dentro. Le chiavi API vivono nel keyring dell'OS
(:mod:`security.secrets`).
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.logging_setup import LogCategory, get_logger
from core.paths import AppPaths, app_paths

__all__ = [
    "AppSettings",
    "AudioSettings",
    "BackendSettings",
    "SettingsStore",
    "UiSettings",
    "VisionSettings",
    "WindowSettings",
    "load_settings",
]

_log = get_logger(LogCategory.APP, "settings")

_ENV_PREFIX = "JARVIS_"
_ENV_SEPARATOR = "__"


class _Base(BaseModel):
    """Base comune: rifiuta le chiavi sconosciute e vieta la mutazione."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AppGeneralSettings(_Base):
    standby_after_hidden_s: int = Field(default=300, ge=0)
    single_instance: bool = True
    developer_tools: bool = True
    """Developer Console richiamabile con F12. Da disattivare nelle build
    distribuite a utenti finali."""


class WindowSettings(_Base):
    frameless: bool = True
    translucent: bool = True
    always_on_top: bool = False
    start_minimized: bool = False
    width: int = Field(default=1280, ge=480)
    height: int = Field(default=820, ge=360)
    min_width: int = Field(default=900, ge=320)
    min_height: int = Field(default=620, ge=240)
    corner_radius: int = Field(default=18, ge=0, le=64)
    opacity: float = Field(default=1.0, gt=0.1, le=1.0)


class BackendSettings(_Base):
    transport: Literal["websocket", "sim", "mock"] = "sim"
    """'mock' e' un sinonimo storico di 'sim', accettato per compatibilita'."""

    scenario: str = "nominale"
    """Scenario di simulazione, quando il trasporto e' 'sim'."""
    adapter: Literal["jcp-native", "openclaw"] = "jcp-native"
    """Dialetto del backend. 'jcp-native' per un backend conforme a JCP,
    'openclaw' per la traduzione verso il dialetto di OpenClaw."""

    auth_scheme: Literal["none", "token", "challenge"] = "none"
    """Il segreto non sta qui: vive nel keyring dell'OS (vedi jarvis_protocol.auth)."""

    url: str = "ws://127.0.0.1:8765/jarvis"
    connect_timeout_s: float = Field(default=5.0, gt=0)
    heartbeat_interval_s: float = Field(default=10.0, gt=0)
    heartbeat_timeout_s: float = Field(default=6.0, gt=0)
    degraded_latency_ms: float = Field(default=750.0, gt=0)
    reconnect_initial_s: float = Field(default=1.0, gt=0)
    reconnect_max_s: float = Field(default=30.0, gt=0)
    reconnect_factor: float = Field(default=2.0, ge=1.0)
    reconnect_jitter: float = Field(default=0.3, ge=0.0, le=1.0)
    circuit_breaker_threshold: int = Field(default=12, ge=1)


class AudioSettings(_Base):
    enabled: bool = True
    tts_mode: Literal["backend", "local"] = "backend"
    sample_rate: int = Field(default=24000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    output_device: str = ""
    input_device: str = ""
    vad_enabled: bool = True
    wake_word_enabled: bool = False


class VisionSettings(_Base):
    enabled: bool = False
    device_index: int = Field(default=0, ge=0)
    target_fps: int = Field(default=24, ge=1, le=120)
    send_frames_to_backend: bool = False
    mirror: bool = True


class UiSettings(_Base):
    theme: str = "dark-mcu"
    language: str = "it"
    target_fps: int = Field(default=60, ge=15, le=240)
    quality: Literal["auto", "high", "low"] = "auto"
    reduced_motion: bool = False
    show_panels: tuple[str, ...] = ("system", "backend", "log", "chat")


class LoggingSettings(_Base):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    console: bool = True
    max_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024)
    backup_count: int = Field(default=5, ge=0)
    ring_capacity: int = Field(default=500, ge=50)


class TelemetrySettings(_Base):
    enabled: bool = True
    sample_interval_s: float = Field(default=1.0, gt=0)


class PluginSettings(_Base):
    enabled: bool = True
    blocklist: tuple[str, ...] = ()


class AppSettings(_Base):
    """Configurazione completa dell'applicazione."""

    app: AppGeneralSettings = AppGeneralSettings()
    window: WindowSettings = WindowSettings()
    backend: BackendSettings = BackendSettings()
    audio: AudioSettings = AudioSettings()
    vision: VisionSettings = VisionSettings()
    ui: UiSettings = UiSettings()
    logging: LoggingSettings = LoggingSettings()
    telemetry: TelemetrySettings = TelemetrySettings()
    plugins: PluginSettings = PluginSettings()


# --------------------------------------------------------------------------- #
# Caricamento stratificato
# --------------------------------------------------------------------------- #


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Fonde ``overlay`` dentro ``base`` ricorsivamente, senza mutare gli input."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    """Legge un TOML, restituendo un dizionario vuoto se assente o illeggibile."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        _log.warning("Default non trovati in %s: si usano i valori del codice", path)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        _log.error("Default illeggibili (%s): %s", path, exc)
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    """Legge le preferenze utente, tollerando assenza e corruzione."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        # Un settings.json corrotto non deve impedire l'avvio: si ignora e si
        # avverte. La copia viene conservata per non perdere le preferenze.
        _log.error("Preferenze utente illeggibili (%s): %s — ignorate", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _coerce(raw: str) -> Any:
    """Converte una stringa d'ambiente nel tipo piu' plausibile."""
    lowered = raw.strip().lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _read_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Estrae gli override dall'ambiente.

    Convenzione: ``JARVIS_<SEZIONE>__<CHIAVE>``. Esempio::

        JARVIS_BACKEND__URL=ws://192.168.1.10:8765/jarvis
        JARVIS_UI__TARGET_FPS=30
    """
    source = os.environ if environ is None else environ
    overrides: dict[str, Any] = {}
    for name, value in source.items():
        if not name.startswith(_ENV_PREFIX):
            continue
        path = name[len(_ENV_PREFIX) :].lower().split(_ENV_SEPARATOR)
        if len(path) < 2:
            continue  # JARVIS_QT_BINDING e simili non sono configurazione
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _coerce(value)
    return overrides


def load_settings(
    paths: AppPaths | None = None,
    *,
    cli_overrides: Mapping[str, Any] | None = None,
) -> AppSettings:
    """Compone e valida la configurazione dai quattro livelli.

    Non solleva mai: se la fusione produce una configurazione non valida, si
    ricade sui default e si registra il motivo. Un'interfaccia che non parte per
    una preferenza sbagliata e' inaccettabile in un'applicazione che deve avviarsi
    al login, quando l'utente potrebbe non avere modo di correggerla.
    """
    resolved = paths or app_paths()

    merged = _read_toml(resolved.defaults_file)
    merged = _deep_merge(merged, _read_json(resolved.user_settings))
    merged = _deep_merge(merged, _read_env())
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    try:
        return AppSettings.model_validate(merged)
    except ValidationError as exc:
        _log.error(
            "Configurazione non valida, si usano i default.\n%s",
            "\n".join(
                f"  {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            ),
        )
        return AppSettings()


class SettingsStore:
    """Accesso alla configurazione con salvataggio delle preferenze utente.

    Scrive **solo** le differenze rispetto ai default, in ``settings.json``: il
    file resta piccolo e leggibile, e le chiavi non toccate continuano a seguire
    i default anche quando questi cambiano in una versione futura.
    """

    def __init__(self, paths: AppPaths | None = None) -> None:
        self._paths = paths or app_paths()
        self._settings = load_settings(self._paths)

    @property
    def current(self) -> AppSettings:
        """Configurazione attualmente in vigore."""
        return self._settings

    @property
    def paths(self) -> AppPaths:
        return self._paths

    def update(self, patch: Mapping[str, Any]) -> tuple[str, ...]:
        """Applica e persiste un insieme di modifiche.

        :param patch: dizionario annidato con le sole chiavi da cambiare.
        :returns: percorsi puntati delle chiavi effettivamente modificate; da
            passare nell'evento ``CONFIG_CHANGED`` cosi' che ogni modulo
            reagisca solo a cio' che lo riguarda.
        """
        stored = _read_json(self._paths.user_settings)
        updated = _deep_merge(stored, patch)

        try:
            candidate = load_settings(
                self._paths, cli_overrides=_deep_merge(updated, {})
            )
        except Exception as exc:
            _log.error("Modifica di configurazione rifiutata: %s", exc)
            return ()

        changed = _diff_keys(self._settings.model_dump(), candidate.model_dump())
        self._settings = candidate

        try:
            self._paths.user_settings.parent.mkdir(parents=True, exist_ok=True)
            self._paths.user_settings.write_text(
                json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            # La modifica resta valida in memoria per questa sessione.
            _log.error("Preferenze non salvate su disco: %s", exc)

        return changed

    def reload(self) -> tuple[str, ...]:
        """Rilegge la configurazione dal disco. Restituisce le chiavi cambiate."""
        previous = self._settings
        self._settings = load_settings(self._paths)
        return _diff_keys(previous.model_dump(), self._settings.model_dump())


def _diff_keys(
    before: Mapping[str, Any], after: Mapping[str, Any], prefix: str = ""
) -> tuple[str, ...]:
    """Elenca i percorsi puntati delle chiavi il cui valore e' cambiato."""
    changed: list[str] = []
    for key in set(before) | set(after):
        path = f"{prefix}{key}"
        old, new = before.get(key), after.get(key)
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            changed.extend(_diff_keys(old, new, prefix=f"{path}."))
        elif old != new:
            changed.append(path)
    return tuple(sorted(changed))
