"""Scenari inclusi.

Ogni scenario riproduce una situazione che con un backend reale non si sa
provocare a comando. Sono composti per parametri, non scritti uno per uno: la
maggior parte nasce da :data:`NOMINAL` cambiando il profilo di canale.

Uso tipico::

    from jarvis_sim.library import by_name
    transport = SimTransport(by_name("rete-instabile"))
"""

from __future__ import annotations

from jarvis_protocol.version import PROTOCOL_VERSION

from jarvis_sim.scenario import Scenario

__all__ = ["ALL", "by_name", "names"]

NOMINAL = Scenario(
    name="nominale",
    description="Backend sano: latenza bassa, nessun guasto. Il riferimento.",
)

SLOW = NOMINAL.with_channel(latency=0.45, handshake_delay=2.5).renamed(
    "lento",
    "Backend lento. Rende osservabile 'Connessione a Jarvis…' e mette alla "
    "prova la soglia di canale degradato.",
)

FLAKY = NOMINAL.with_channel(latency=0.12, jitter=0.8, drop_after=6.0).renamed(
    "rete-instabile",
    "Latenza variabile e caduta a metà sessione: verifica riconnessione, "
    "backoff e la dichiarazione di esito ignoto delle operazioni in corso.",
)

UNREACHABLE = NOMINAL.with_channel(fail_connect=True).renamed(
    "irraggiungibile",
    "La connessione non si apre mai: verifica che l'interfaccia resti viva e "
    "continui a riprovare senza bloccarsi.",
)

SILENT = NOMINAL.with_channel(refuse_handshake=True).renamed(
    "muto",
    "Il canale si apre ma il backend non si presenta: verifica il timeout di "
    "handshake, distinto da quello di connessione.",
)

AUTH_REQUIRED = NOMINAL.with_channel(require_auth=True).renamed(
    "autenticazione-richiesta",
    "Rifiuta l'handshake senza token valido: verifica che i tentativi si "
    "fermino invece di ripetersi all'infinito.",
)

PROTOCOL_MISMATCH = NOMINAL.with_channel(
    protocol_major=PROTOCOL_VERSION.major + 1
).renamed(
    "protocollo-incompatibile",
    "Dichiara un major diverso: la sessione va rifiutata senza tentare di "
    "interpretare.",
)

PROTOCOL_NEWER_MINOR = NOMINAL.with_channel(
    protocol_minor=PROTOCOL_VERSION.minor + 5
).renamed(
    "protocollo-piu-recente",
    "Minor superiore: la sessione deve essere accettata. È il caso che rende "
    "possibile aggiornare GUI e backend in momenti diversi.",
)

NOISY = NOMINAL.with_channel(malformed_every=7, emit_unknown=True).renamed(
    "rumoroso",
    "Un messaggio su sette è malformato, più tipi sconosciuti ed estensioni "
    "non negoziate: nulla di ciò deve interrompere la sessione.",
)

DESTRUCTIVE = NOMINAL.with_behaviour(
    confirm_probability=1.0, actions_min=3, actions_max=4, confirm_timeout_s=45.0
).renamed(
    "conferme-distruttive",
    "Ogni azione rischiosa chiede conferma: verifica il trattamento visivo del "
    "rischio e il conto alla rovescia.",
)

STORM = NOMINAL.with_behaviour(
    actions_min=6, actions_max=9, step_delay=0.04, failure_rate=0.35, emit_audio=False
).with_channel(latency=0.01).renamed(
    "tempesta",
    "Molte azioni rapide con alto tasso di fallimento: mette alla prova coda, "
    "metriche e tenuta della timeline.",
)

LEGACY_TASKS = NOMINAL.with_behaviour(
    emit_missions=False, task_probability=1.0
).renamed(
    "task-legacy",
    "Usa solo 'task.update' senza missioni: verifica che la forma semplice "
    "resti supportata e venga proiettata nella coda.",
)

QUIET = NOMINAL.with_behaviour(emit_audio=False, emit_missions=False).renamed(
    "minimale",
    "Solo conversazione: nessun audio, nessuna missione. Il minimo che un "
    "backend conforme può offrire.",
)

#: Tutti gli scenari inclusi, per nome.
ALL: dict[str, Scenario] = {
    s.name: s
    for s in (
        NOMINAL, SLOW, FLAKY, UNREACHABLE, SILENT, AUTH_REQUIRED,
        PROTOCOL_MISMATCH, PROTOCOL_NEWER_MINOR, NOISY, DESTRUCTIVE,
        STORM, LEGACY_TASKS, QUIET,
    )
}


def names() -> list[str]:
    """Nomi degli scenari disponibili, in ordine."""
    return sorted(ALL)


def by_name(name: str) -> Scenario:
    """Recupera uno scenario per nome.

    :raises KeyError: con l'elenco dei nomi validi. Un messaggio d'errore che
        dice solo "non trovato" costringe a cercare il nome altrove.
    """
    try:
        return ALL[name]
    except KeyError:
        raise KeyError(
            f"Scenario '{name}' sconosciuto. Disponibili: {', '.join(names())}"
        ) from None
