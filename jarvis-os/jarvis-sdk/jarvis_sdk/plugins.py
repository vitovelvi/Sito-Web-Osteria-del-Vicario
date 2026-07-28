"""API dei plugin.

Definisce il **contratto**, non il caricatore dell'applicazione. Un autore di
plugin dipende da questo pacchetto — che non tira dentro Qt — e può scrivere,
validare e collaudare il proprio plugin senza avviare l'interfaccia.

Tre scelte che vale la pena motivare.

**Versione di API separata dalla versione del pacchetto.**
:data:`PLUGIN_API_VERSION` cambia solo quando cambia il contratto. Un plugin
dichiara con quale versione è stato scritto; il caricatore rifiuta ciò che non
sa ospitare invece di caricarlo e scoprirlo a metà.

**Il contesto è deliberatamente povero.** :class:`PluginContext` espone bus
namespaced, registro dei pannelli, logger e configurazione — non la finestra
principale, non i servizi, non lo state manager. Se un plugin potesse
raggiungere gli interni, in due anni il core non sarebbe più modificabile senza
rompere i plugin, che è il modo classico in cui un sistema estensibile si
irrigidisce.

**I plugin girano in-process, con piena fiducia.** Python non offre sandboxing
reale, e fingere il contrario sarebbe peggio che dirlo: la versione di API li
protegge dalle rotture del core, non protegge il core da un plugin malevolo.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

__all__ = [
    "PLUGIN_API_VERSION",
    "IPlugin",
    "PluginContext",
    "PluginManifest",
    "ValidationIssue",
    "discover",
    "validate_manifest",
]

_log = logging.getLogger("jarvis_sdk.plugins")

#: Versione del contratto dei plugin. Indipendente dalla versione dell'SDK.
PLUGIN_API_VERSION: Final[int] = 1

#: Un identificatore di plugin: minuscole, punti come separatore.
_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)*$")

_MANIFEST_NAME: Final[str] = "plugin.json"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Un problema riscontrato in un manifesto."""

    field: str
    message: str
    fatal: bool = True

    def __str__(self) -> str:  # pragma: no cover - diagnostica
        gravita = "errore" if self.fatal else "avviso"
        return f"[{gravita}] {self.field}: {self.message}"


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Dichiarazione di un plugin (``plugin.json``).

    Il manifesto è separato dal codice di proposito: si può ispezionare un
    plugin — nome, versione, permessi richiesti — **senza importarlo**, cioè
    senza eseguirlo.
    """

    id: str
    name: str
    version: str
    api_version: int = PLUGIN_API_VERSION
    entry_point: str = "plugin:Plugin"
    """Modulo e classe, nella forma ``modulo:Classe``."""

    description: str = ""
    author: str = ""
    requires_capabilities: tuple[str, ...] = ()
    """Capability JCP senza le quali il plugin non ha senso di essere attivato."""

    path: Path | None = field(default=None, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path | None = None) -> PluginManifest:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            api_version=int(data.get("api_version", PLUGIN_API_VERSION)),
            entry_point=str(data.get("entry_point", "plugin:Plugin")),
            description=str(data.get("description", "")),
            author=str(data.get("author", "")),
            requires_capabilities=tuple(data.get("requires_capabilities", ())),
            path=path,
        )

    @classmethod
    def load(cls, directory: Path) -> PluginManifest:
        """Legge il manifesto da una directory.

        :raises FileNotFoundError: se il manifesto non esiste.
        :raises ValueError: se non è JSON valido.
        """
        percorso = directory / _MANIFEST_NAME
        try:
            data = json.loads(percorso.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{percorso}: manifesto non valido ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{percorso}: il manifesto deve essere un oggetto JSON")
        return cls.from_dict(data, path=directory)

    @property
    def is_compatible(self) -> bool:
        """Vero se questa build sa ospitare il plugin."""
        return self.api_version == PLUGIN_API_VERSION


def validate_manifest(manifest: PluginManifest) -> list[ValidationIssue]:
    """Verifica un manifesto e restituisce i problemi trovati.

    Restituisce una lista invece di sollevare alla prima anomalia: chi scrive
    un plugin vuole vedere tutti gli errori insieme, non correggerne uno per
    volta scoprendo il successivo a ogni tentativo.
    """
    problemi: list[ValidationIssue] = []

    if not manifest.id:
        problemi.append(ValidationIssue("id", "identificatore mancante"))
    elif not _ID_PATTERN.match(manifest.id):
        problemi.append(
            ValidationIssue(
                "id",
                "deve essere in minuscolo, con punti come separatore "
                "(esempio: 'acme.meteo')",
            )
        )

    if not manifest.name:
        problemi.append(ValidationIssue("name", "nome leggibile mancante"))
    if not manifest.version:
        problemi.append(ValidationIssue("version", "versione mancante"))

    if manifest.api_version != PLUGIN_API_VERSION:
        problemi.append(
            ValidationIssue(
                "api_version",
                f"il plugin dichiara la versione {manifest.api_version}, "
                f"questa build ospita la {PLUGIN_API_VERSION}",
            )
        )

    if ":" not in manifest.entry_point:
        problemi.append(
            ValidationIssue("entry_point", "atteso il formato 'modulo:Classe'")
        )

    if manifest.path is not None:
        modulo = manifest.entry_point.split(":", 1)[0]
        if not (manifest.path / f"{modulo}.py").exists():
            problemi.append(
                ValidationIssue(
                    "entry_point",
                    f"il modulo '{modulo}.py' non esiste in {manifest.path}",
                    fatal=False,
                )
            )

    return problemi


@runtime_checkable
class PluginContext(Protocol):
    """Ciò che l'applicazione mette a disposizione di un plugin.

    Volutamente ristretto: tutto ciò che non compare qui è fuori portata, e
    resterà tale anche quando il core cambierà.
    """

    @property
    def plugin_id(self) -> str:
        """Identificatore del plugin in esecuzione."""
        ...

    @property
    def logger(self) -> logging.Logger:
        """Logger dedicato, già instradato nella diagnostica dell'applicazione."""
        ...

    def publish(self, name: str, payload: Any) -> None:
        """Pubblica un evento nello spazio del plugin.

        Il nome viene automaticamente prefissato con ``plugin.<id>.``: un
        plugin non può pubblicare eventi del core, né collidere con un altro
        plugin.
        """
        ...

    def subscribe(self, event: str, handler: Any) -> Any:
        """Si sottoscrive a un evento. Restituisce un token di disiscrizione."""
        ...

    def has_capability(self, capability: str) -> bool:
        """Indica se il backend dichiara una capability JCP."""
        ...

    def send(self, message_type: str, payload: dict[str, Any] | None = None) -> bool:
        """Invia un messaggio JCP, se il tipo appartiene allo spazio ``ext.``.

        Un plugin **non** può inviare messaggi del protocollo core: potrebbe
        dichiarare stati o esiti che il backend non ha prodotto, e la GUI
        smetterebbe di essere una proiezione fedele.
        """
        ...

    def settings(self) -> dict[str, Any]:
        """Configurazione del plugin, isolata da quella dell'applicazione."""
        ...


@runtime_checkable
class IPlugin(Protocol):
    """Contratto che un plugin deve soddisfare."""

    def activate(self, context: PluginContext) -> None:
        """Chiamata una volta, all'attivazione.

        Deve ritornare in fretta: viene invocata durante l'avvio, e un plugin
        lento ritarda la comparsa dell'interfaccia. Il lavoro lungo va in un
        thread proprio.
        """
        ...

    def deactivate(self) -> None:
        """Chiamata alla disattivazione. Deve rilasciare tutto e non sollevare."""
        ...


def discover(directory: Path) -> list[PluginManifest]:
    """Elenca i manifesti presenti in una directory di plugin.

    Non importa nulla: si limita a leggere i manifesti. È ciò che permette a
    uno strumento da riga di comando di dire cosa c'è **senza eseguirlo**.
    """
    if not directory.is_dir():
        return []

    trovati: list[PluginManifest] = []
    for figlio in sorted(directory.iterdir()):
        if not (figlio / _MANIFEST_NAME).exists():
            continue
        try:
            trovati.append(PluginManifest.load(figlio))
        except (OSError, ValueError) as exc:
            _log.warning("Plugin in '%s' ignorato: %s", figlio.name, exc)
    return trovati
