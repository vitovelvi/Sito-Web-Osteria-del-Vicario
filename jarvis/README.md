# JARVIS — Cognitive Operating System

JARVIS è un **sistema operativo cognitivo modulare** ispirato al J.A.R.V.I.S. dell'MCU.
Non è un chatbot: è un'architettura a eventi in cui osservazione, memoria, ragionamento,
pianificazione ed esecuzione sono sistemi indipendenti che comunicano esclusivamente
tramite un Event Bus.

## Avvio rapido

```bash
cd jarvis

# Prototipo eseguibile immediatamente (zero dipendenze obbligatorie)
python3 -m jarvis demo            # boot completo + richiesta dimostrativa end-to-end
python3 -m jarvis run             # avvia il sistema + dashboard su http://127.0.0.1:8765
python3 -m jarvis status          # snapshot di stato del sistema

# Dipendenze opzionali (metriche più ricche, config YAML, provider LLM)
pip install -r requirements.txt

# Test
python3 -m unittest discover -s tests -v
```

## Architettura

```
                         ┌────────────────────┐
                         │    Core Identity   │  personalità · regole · autonomia
                         └─────────┬──────────┘
                                   │
 Observation ──► ┌──────────────────────────────────┐ ◄── Voice Pipeline
 (PC, processi,  │            EVENT BUS             │     (WakeWord→VAD→STT→
  CPU, RAM, FS)  │  ogni componente parla a eventi  │      Intent→Planner→LLM→TTS)
                 └───┬────────┬────────┬───────┬────┘
                     │        │        │       │
              ┌──────▼──┐ ┌───▼────┐ ┌─▼─────┐ ┌▼──────────┐
              │ Agents  │ │ Memory │ │ Tasks │ │ Self-Heal │
              │Orchestr.│ │ System │ │Manager│ │  System   │
              └────┬────┘ └────────┘ └───────┘ └───────────┘
                   │
        Reasoning Engine ─► Planner ─► Execution Broker ─► Validation
                                                            ─► Sandbox ─► Executor
                   │
              LLM Router (Ollama → modelli gratuiti → Claude API)
```

### Principi

- **Event-driven**: nessun componente chiama direttamente un altro; tutto passa dal bus.
- **Security Layer**: ogni operazione è classificata (Livello 0–3); i livelli 2–3
  richiedono sempre conferma. L'LLM **non tocca mai il terminale**: può solo proporre
  azioni registrate, che passano da Broker → Validation → Sandbox → Executor.
- **Backend sostituibili**: memoria (in-memory / JSON / SQLite), provider LLM,
  stadi voce e osservatori sono interfacce con implementazioni intercambiabili.
- **Dependency injection**: il `Kernel` compone i sottosistemi; niente singleton globali.

## Struttura

| Pacchetto              | Responsabilità                                            |
|------------------------|-----------------------------------------------------------|
| `jarvis.core`          | Core Identity: personalità, tono, regole, autonomia       |
| `jarvis.events`        | Event Bus asincrono con topic gerarchici e wildcard       |
| `jarvis.memory`        | Working / Episodic / Semantic / Preference / Op-Logs      |
| `jarvis.observation`   | Osservatori PC, filesystem + integrazioni (WP, GA, Meta)  |
| `jarvis.agents`        | Orchestratore + 8 agenti indipendenti                     |
| `jarvis.reasoning`     | Reasoning Engine (separato dall'esecuzione)               |
| `jarvis.planning`      | Planner: richiesta → piano multi-step                     |
| `jarvis.llm`           | LLM Router: Ollama → free-tier → Claude                   |
| `jarvis.execution`     | Broker → Validation → Sandbox → Executor                  |
| `jarvis.security`      | Classificazione operazioni, gate di conferma, audit       |
| `jarvis.voice`         | Pipeline vocale modulare (interfacce + impl. console)     |
| `jarvis.tasks`         | Task Manager: ID, stato, priorità, dipendenze, storia     |
| `jarvis.healing`       | Rilevamento errori, retry, rollback, recovery             |
| `jarvis.dashboard`     | Dashboard web (stdlib, zero dipendenze)                   |
| `jarvis.logging`       | Logging strutturato JSON                                  |
| `jarvis.config`        | Loader di configurazione (JSON, YAML opzionale)           |

## Configurazione

Tutto è configurabile da `config/jarvis.json` (o `.yaml` se PyYAML è installato):
percorsi, modelli, provider, intervalli, porte. Nessun valore hardcoded nel codice.
Le chiavi API si passano **solo** via variabili d'ambiente (es. `ANTHROPIC_API_KEY`),
mai nel file di configurazione.
