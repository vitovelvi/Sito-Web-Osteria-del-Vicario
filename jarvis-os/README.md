# jarvis-os

Monorepo di J.A.R.V.I.S.: interfaccia desktop, protocollo, adapter, strumenti.

```
jarvis-os/
├── jarvis-desktop/     interfaccia PySide6 (l'applicazione)
├── jarvis-protocol/    pacchetto jarvis-protocol — JCP 1.0, il contratto
├── openclaw-adapter/   pacchetto jarvis-adapter-openclaw — primo backend
├── jarvis-docs/        specifica e analisi architetturale
├── tools/              utilità di sviluppo
└── examples/           backend JCP minimale, come riferimento
```

## Perché tre pacchetti e non uno

**`jarvis-protocol` ha una sola dipendenza** (`pydantic`). Chi implementa un
backend deve poter adottare il contratto senza tirarsi dietro Qt, audio e
visione. È la differenza fra un protocollo e un dettaglio interno di
un'applicazione.

**`openclaw-adapter` dipende solo dal protocollo.** Qualunque client JCP può
riusarlo, e il giorno in cui il dialetto di OpenClaw cambia si aggiorna lì
senza toccare l'interfaccia.

**`jarvis-desktop` dipende da entrambi** e da nient'altro di proprio. Un
secondo client — una CLI, un pannello web, un dispositivo — parte dagli stessi
due pacchetti.

## Avvio

```bash
cd jarvis-desktop
python -m venv .venv
.venv/bin/pip install -e ../jarvis-protocol -e ../openclaw-adapter -e ".[dev]"
.venv/bin/python main.py --transport mock
```

## Test

```bash
cd jarvis-desktop
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
.venv/bin/ruff check . ../jarvis-protocol ../openclaw-adapter
```

## Documentazione

* [`jarvis-docs/00-architettura-proposta.md`](jarvis-docs/00-architettura-proposta.md)
  — analisi architetturale e motivazione di ogni scelta
* [`jarvis-docs/01-jcp-specifica.md`](jarvis-docs/01-jcp-specifica.md)
  — specifica JCP 1.0, incluso il livello operativo (§11)
