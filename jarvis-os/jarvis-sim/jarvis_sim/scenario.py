"""Scenari di simulazione: dichiarativi, parametrici, riproducibili.

Uno scenario è **solo dati**. Non contiene codice, quindi si serializza in JSON,
si allega a una segnalazione, si versiona accanto ai test e — soprattutto — si
riproduce identico: stesso seme, stessa sequenza di eventi, stesse durate.

La riproducibilità non è un dettaglio. Un difetto che compare "ogni tanto"
diventa affrontabile solo quando si riesce a farlo comparire a comando, e con
un backend reale non si può.

Uno scenario descrive due cose distinte:

* il **profilo di canale** — latenza, cadute, handshake, autenticazione,
  messaggi malformati. Sono i modi in cui una connessione si comporta male;
* il **comportamento** — quante azioni per missione, con che probabilità
  falliscono, quando chiedono conferma. È cosa fa il backend quando il canale
  funziona.

Tenerli separati permette di combinarli: "il backend nominale, ma su una rete
che cade a metà risposta" è la composizione di due profili, non un terzo
scenario da scrivere.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from jarvis_protocol.capabilities import Capability
from jarvis_protocol.version import PROTOCOL_VERSION

__all__ = ["Behaviour", "Channel", "Scenario", "ToolSpec"]


@dataclass(slots=True)
class ToolSpec:
    """Strumento dichiarato dal backend simulato."""

    name: str
    title: str = ""
    description: str = ""
    category: str = ""
    risk: str = "low"

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "category": self.category or None,
            "risk": self.risk,
        }


@dataclass(slots=True)
class Channel:
    """Profilo del canale: come si comporta la connessione.

    Ogni campo riproduce un guasto osservato con backend reali. Sono i casi in
    cui un'interfaccia si rivela fatta male, ed è per questo che esistono.
    """

    latency: float = 0.05
    """Ritardo applicato a ogni messaggio in uscita dal backend."""

    jitter: float = 0.0
    """Variazione casuale della latenza, come frazione di essa. Una rete reale
    non ha latenza costante, e un'interfaccia tarata su una latenza fissa
    scopre tardi di non reggere la variabilità."""

    handshake_delay: float = 0.3
    """Ritardo prima di ``session.welcome``. Alzarlo rende osservabile lo stato
    "Connessione a Jarvis…", che altrimenti passa troppo in fretta per essere
    valutato."""

    fail_connect: bool = False
    refuse_handshake: bool = False
    """Il canale si apre ma il backend non si presenta mai: caso reale — un
    servizio in avvio, una porta occupata da un altro processo — e distinto da
    un host irraggiungibile, che fallisce prima."""

    drop_after: float | None = None
    """Secondi dopo i quali il canale cade, anche a metà risposta."""

    malformed_every: int = 0
    """Ogni quanti messaggi inviarne uno con payload della forma sbagliata."""

    protocol_major: int = PROTOCOL_VERSION.major
    protocol_minor: int = PROTOCOL_VERSION.minor

    require_auth: bool = False
    accepted_token: str = "segreto-di-prova"

    emit_unknown: bool = False
    """Invia anche un tipo del futuro e un'estensione non negoziata: entrambi
    devono essere ignorati senza conseguenze."""


@dataclass(slots=True)
class Behaviour:
    """Comportamento del backend quando il canale funziona."""

    reply_streaming: bool = True
    emit_audio: bool = True
    emit_missions: bool = True

    actions_min: int = 2
    actions_max: int = 4
    action_steps_min: int = 2
    action_steps_max: int = 4
    step_delay: float = 0.18

    failure_rate: float = 0.15
    """Probabilità che un'azione fallisca. Un backend che riesce sempre non
    mette mai alla prova il modo in cui l'interfaccia mostra un errore."""

    confirm_probability: float = 0.35
    """Probabilità che un'azione rischiosa chieda conferma."""

    confirm_timeout_s: float = 20.0
    task_probability: float = 0.0
    """Probabilità di emettere anche un ``task.update`` legacy, per verificare
    che la forma semplice resti supportata."""


#: Strumenti predefiniti, con rischi differenziati: senza variazione non si
#: potrebbe verificare che l'interfaccia tratti diversamente una lettura da
#: un'operazione distruttiva.
DEFAULT_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("calendar.read", "Lettura calendario", "Consulta gli impegni del giorno.",
             "produttività", "low"),
    ToolSpec("web.search", "Ricerca web", "Cerca informazioni in rete.", "conoscenza", "low"),
    ToolSpec("fs.read_file", "Lettura file", "Legge un file locale.", "sistema", "medium"),
    ToolSpec("fs.write_file", "Scrittura file", "Scrive o sovrascrive un file locale.",
             "sistema", "high"),
    ToolSpec("shell.run", "Comando di sistema", "Esegue un comando sulla macchina.",
             "sistema", "destructive"),
)

#: Azioni che il backend simulato può compiere.
DEFAULT_PLAN: tuple[tuple[str, str, str], ...] = (
    ("calendar.read", "Consulta gli impegni di oggi", "date=2026-07-28"),
    ("web.search", "Cerca i riferimenti richiesti", "query=stato dei sistemi"),
    ("fs.read_file", "Legge la configurazione", "path=~/.config/jarvis/settings.json"),
    ("fs.write_file", "Aggiorna il rapporto", "path=~/rapporto.md, bytes=2481"),
    ("shell.run", "Riavvia il servizio di indicizzazione", "cmd=systemctl restart indexer"),
)

#: Capability dichiarate per default dal backend simulato.
DEFAULT_CAPABILITIES: tuple[str, ...] = (
    Capability.CHAT_STREAM.value,
    Capability.CHAT_CANCEL.value,
    Capability.TTS_STREAM.value,
    Capability.TASKS.value,
    Capability.IDENTITY.value,
    Capability.MISSIONS.value,
    Capability.ACTIONS.value,
    Capability.ACTIONS_CANCEL.value,
    Capability.ACTIONS_CONFIRM.value,
    Capability.TOOLS_REGISTRY.value,
)


@dataclass(slots=True)
class Scenario:
    """Uno scenario completo: identità, canale, comportamento, catalogo."""

    name: str = "nominale"
    description: str = ""
    seed: int = 7
    """Seme del generatore. **Lo stesso seme produce la stessa sessione**: è
    ciò che rende uno scenario una prova ripetibile invece di un aneddoto."""

    channel: Channel = field(default_factory=Channel)
    behaviour: Behaviour = field(default_factory=Behaviour)
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES
    tools: tuple[ToolSpec, ...] = DEFAULT_TOOLS
    plan: tuple[tuple[str, str, str], ...] = DEFAULT_PLAN

    assistant_name: str = "J.A.R.V.I.S."
    backend_name: str = "jarvis-sim"
    backend_version: str = "1.0.0"
    model: str = "simulato"

    # ------------------------------------------------------------------ #
    # Composizione
    # ------------------------------------------------------------------ #

    def with_channel(self, **overrides: Any) -> Scenario:
        """Copia con un profilo di canale diverso.

        È il meccanismo che evita di scrivere uno scenario per ogni
        combinazione: ``NOMINALE.with_channel(drop_after=2.0)`` è il
        comportamento nominale su una rete che cade.
        """
        return replace(self, channel=replace(self.channel, **overrides))

    def with_behaviour(self, **overrides: Any) -> Scenario:
        """Copia con un comportamento diverso."""
        return replace(self, behaviour=replace(self.behaviour, **overrides))

    def renamed(self, name: str, description: str = "") -> Scenario:
        return replace(self, name=name, description=description or self.description)

    # ------------------------------------------------------------------ #
    # Persistenza
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        """Scrive lo scenario in JSON, allegabile a una segnalazione."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        """Costruisce uno scenario da un dizionario.

        I campi sconosciuti vengono **ignorati**: uno scenario scritto per una
        versione più recente resta caricabile, con i valori di default per ciò
        che questa build non conosce. È la stessa regola del protocollo,
        applicata agli scenari.
        """
        noti = set(cls.__slots__)  # type: ignore[attr-defined]
        grezzi = {k: v for k, v in data.items() if k in noti}

        if isinstance(grezzi.get("channel"), dict):
            campi = set(Channel.__slots__)  # type: ignore[attr-defined]
            grezzi["channel"] = Channel(
                **{k: v for k, v in grezzi["channel"].items() if k in campi}
            )
        if isinstance(grezzi.get("behaviour"), dict):
            campi = set(Behaviour.__slots__)  # type: ignore[attr-defined]
            grezzi["behaviour"] = Behaviour(
                **{k: v for k, v in grezzi["behaviour"].items() if k in campi}
            )
        if isinstance(grezzi.get("tools"), list):
            campi = set(ToolSpec.__slots__)  # type: ignore[attr-defined]
            grezzi["tools"] = tuple(
                ToolSpec(**{k: v for k, v in t.items() if k in campi})
                for t in grezzi["tools"]
                if isinstance(t, dict)
            )
        for chiave in ("capabilities", "plan"):
            if isinstance(grezzi.get(chiave), list):
                valore = grezzi[chiave]
                grezzi[chiave] = tuple(
                    tuple(v) if isinstance(v, list) else v for v in valore
                )
        return cls(**grezzi)

    @classmethod
    def load(cls, path: Path) -> Scenario:
        """:raises ValueError: se il file non è JSON valido."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: scenario non valido ({exc})") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{path}: lo scenario deve essere un oggetto JSON")
        return cls.from_dict(data)

    def describe(self) -> str:
        """Riga di riepilogo per log e strumenti."""
        parti = [f"latenza {self.channel.latency * 1000:.0f} ms"]
        if self.channel.jitter:
            parti.append(f"jitter {self.channel.jitter:.0%}")
        if self.channel.drop_after:
            parti.append(f"caduta a {self.channel.drop_after:.1f}s")
        if self.channel.refuse_handshake:
            parti.append("handshake omesso")
        if self.channel.require_auth:
            parti.append("autenticazione richiesta")
        if self.channel.malformed_every:
            parti.append(f"1 su {self.channel.malformed_every} malformato")
        if (self.channel.protocol_major, self.channel.protocol_minor) != (
            PROTOCOL_VERSION.major,
            PROTOCOL_VERSION.minor,
        ):
            parti.append(
                f"protocollo {self.channel.protocol_major}.{self.channel.protocol_minor}"
            )
        return f"{self.name}: " + ", ".join(parti)
