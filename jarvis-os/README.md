# jarvis-os

Monorepo di J.A.R.V.I.S.: interfaccia desktop, protocollo, SDK, simulatore,
adapter, strumenti.

```
jarvis-os/
├── jarvis-desktop/     interfaccia PySide6 (l'applicazione)
├── jarvis-protocol/    jarvis-protocol — JCP 1.0, il contratto
├── jarvis-sdk/         jarvis-sdk — adapter, plugin, registrazione, conformità
├── jarvis-sim/         jarvis-sim — backend simulato con scenari riproducibili
├── openclaw-adapter/   jarvis-adapter-openclaw — primo dialetto
├── jarvis-docs/        specifica, guide, riferimento tecnico
├── tools/              utilità di sviluppo
└── examples/           backend JCP minimale, come riferimento
```

## Perché cinque pacchetti e non uno

**Nessuno dei quattro pacchetti di libreria importa Qt.** Chi implementa un
backend, un adapter o un plugin non deve installare un toolkit grafico. È la
differenza fra un protocollo e un dettaglio interno di un'applicazione.

* **`jarvis-protocol`** ha una sola dipendenza, `pydantic`. Contiene il
  contratto e nient'altro.
* **`jarvis-sdk`** dipende solo dal protocollo: base per adapter e plugin,
  registrazione e replay delle sessioni, suite di conformità, utilità di test.
* **`jarvis-sim`** dipende solo dal protocollo: implementa JCP 1.0 per intero,
  si usa in-process o come server autonomo, e riproduce a comando i guasti che
  con un backend reale non si sanno provocare.
* **`openclaw-adapter`** dipende solo dal protocollo. Qualunque client JCP può
  riusarlo, e il giorno in cui il dialetto di OpenClaw cambia si aggiorna lì
  senza toccare l'interfaccia.
* **`jarvis-desktop`** dipende da tutti e quattro e da nient'altro di proprio.
  Un secondo client — una CLI, un pannello web, un dispositivo — parte dagli
  stessi pacchetti.

## Avvio

```bash
cd jarvis-desktop
python -m venv .venv
.venv/bin/pip install -e ../jarvis-protocol -e ../jarvis-sdk -e ../jarvis-sim \
                      -e ../openclaw-adapter -e ".[dev]"
.venv/bin/python main.py --transport sim
```

```bash
.venv/bin/python main.py --transport sim --scenario rete-instabile
.venv/bin/python main.py --url ws://127.0.0.1:8765/jarvis
```

## Test

```bash
cd jarvis-desktop
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest ../jarvis-sdk/tests ../jarvis-sim/tests -q
.venv/bin/ruff check . ../jarvis-protocol ../jarvis-sdk ../jarvis-sim ../openclaw-adapter
```

## Backend e conformità

```bash
jarvis-sim --list                                  # scenari disponibili
jarvis-sim --scenario tempesta                     # server JCP simulato
python tools/jcp_validate.py --url ws://127.0.0.1:8765
```

`jcp_validate` esce con `0` se il backend è conforme, `1` altrimenti: si mette
in integrazione continua senza interpretare l'output.

## Documentazione

Indice completo in [`jarvis-docs/README.md`](jarvis-docs/README.md).

* [`00-architettura-proposta.md`](jarvis-docs/00-architettura-proposta.md) — perché è fatto così
* [`01-jcp-specifica.md`](jarvis-docs/01-jcp-specifica.md) — il contratto di rete
* [`02-sdk.md`](jarvis-docs/02-sdk.md) — scrivere adapter, plugin, backend
* [`03-simulazione-e-replay.md`](jarvis-docs/03-simulazione-e-replay.md) — scenari, registrazione, replay, conformità
* [`04-riferimento-tecnico.md`](jarvis-docs/04-riferimento-tecnico.md) — moduli, contratti, threading, invarianti
