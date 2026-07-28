# J.A.R.V.I.S. — Interfaccia desktop

Interfaccia grafica, audio e visiva del backend **OpenClaw**.

Questa applicazione **non è il cervello di Jarvis**. Non prende decisioni, non
contiene logica AI e non conserva conoscenza. Mostra lo stato del sistema,
raccoglie l'input dell'utente, inoltra eventi al backend e riflette quelli che
ne tornano. Ogni decisione è di OpenClaw.

La conseguenza pratica di questo principio si vede ovunque nel codice: se il
backend non ha dichiarato un modello, l'HUD scrive "modello non dichiarato"
invece di indovinarlo; alla caduta del canale l'identità remota viene azzerata
invece di restare in vista; le capability non dichiarate non producono pulsanti
disabilitati, ma pannelli che non vengono proprio costruiti.

---

## Stato di avanzamento

| Fase | Contenuto | Stato |
|---|---|---|
| 0 | Fondamenta: bus, stati, identità, capability, protocollo, config, log | ✅ |
| 1 | Guscio GUI: tema, finestra frameless, HUD, notifiche, tray | ✅ |
| 2 | Nucleo animato: FrameClock, preset, dissolvenze, renderer | ✅ |
| 3 | Rete: trasporto, MockBackend, handshake, heartbeat, riconnessione | ✅ |
| 3.5 | JCP, adapter layer, Developer Console | ✅ |
| 3.6 | Mission Engine, Action Framework, Tool Inspector, Metrics | ✅ |
| 3.7 | Consolidamento: documentazione, SDK, simulatore, registrazione e replay | ✅ |
| 4 | Pannelli: PanelHost, registry, layout persistente | ⏳ |
| 5 | Audio: riproduzione streaming, inviluppo, cattura, VAD | ⏳ |
| 6 | Visione: cattura OpenCV, pipeline, pannello webcam | ⏳ |
| 7 | Plugin: API, loader, esempio | ⏳ |
| 8 | Rifiniture: supervisor, telemetria, packaging, autostart | ⏳ |

L'analisi architetturale che motiva ogni scelta è in
[`../jarvis-docs/00-architettura-proposta.md`](../jarvis-docs/00-architettura-proposta.md);
la mappa dei moduli in
[`../jarvis-docs/04-riferimento-tecnico.md`](../jarvis-docs/04-riferimento-tecnico.md).

---

## Avvio

```bash
python -m venv .venv
.venv/bin/pip install -e ../jarvis-protocol -e ../jarvis-sdk -e ../jarvis-sim \
                      -e ../openclaw-adapter -e ".[dev]"
.venv/bin/python main.py
```

Argomenti utili:

```bash
python main.py --transport sim                    # backend simulato (default)
python main.py --transport sim --scenario tempesta # uno scenario preciso
python main.py --url ws://host:8765/j             # backend reale (vedi backend.adapter)
python main.py --no-translucent                   # su hardware senza compositing
python main.py --log-level DEBUG
```

`jarvis-sim --list` elenca gli scenari disponibili. `mock` resta accettato come
sinonimo storico di `sim`.

### Su Linux minimale (container, CI)

Il plugin `xcb` di Qt ha dipendenze che una distribuzione ridotta non installa,
e l'errore che produce — "Could not load the Qt platform plugin xcb" — non dice
quale manchi:

```bash
apt-get install -y libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1 \
                   libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xkb1
xvfb-run -s "-screen 0 1600x1000x24" python main.py --transport sim
```

Per i soli test non serve nulla di tutto questo: `QT_QPA_PLATFORM=offscreen`.

## Test

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest ../jarvis-sdk/tests ../jarvis-sim/tests -q
.venv/bin/ruff check . ../jarvis-protocol ../jarvis-sdk ../jarvis-sim ../openclaw-adapter
```

I test del nucleo girano **senza display**. È anche una verifica implicita
della regola di dipendenza: se un test di `core/` richiedesse una finestra,
vorrebbe dire che il nucleo ha iniziato a dipendere dalla GUI.

---

## Architettura in breve

```
main.py            bootstrap: costruisce, registra, avvia. Nessuna logica.
core/              nucleo non visivo — non importa mai da ui/
  qtcompat.py      PySide6 dietro shim: il binding si cambia da un solo file
  eventbus.py      eventi tipizzati, consegna sempre nel thread GUI
  events.py        catalogo eventi + payload dataclass
  state/           tre macchine ortogonali + risoluzione visiva
  registry.py      service registry con DI e ordine topologico
  identity.py      identità locale persistente e identità del backend
  capabilities.py  negoziazione delle funzioni disponibili
  missions/        Mission Engine: proiezione degli eventi operativi
  settings.py      configurazione stratificata e validata
  frameclock.py    sorgente unica del tempo a 60 FPS
network/           comunicazione con il backend
  transport/       muove dizionari, non conosce JCP
  adapters/        traducono dialetto ↔ JCP: native, openclaw
  dispatcher.py    unico punto che conosce i tipi di messaggio
  reconnect.py     backoff esponenziale, jitter, interruttore
  service.py       thread asyncio dedicato, sessione, heartbeat, registrazione
ui/                presentazione — può importare da core, mai il contrario
  theme/           design token in JSON → QSS generato
  frameless.py     finestra senza cornice, ombra in cache
  reactor/         nucleo: parametri, animatore, renderer, widget
  devtools/        Developer Console (F12): timeline, ispettore, sessione
  ops/             livello operativo (F9): missioni, coda, conferme, strumenti
tests/             unit + integration + ui
```

Il protocollo, l'SDK e il backend simulato **non stanno qui**: sono pacchetti
autonomi (`../jarvis-protocol`, `../jarvis-sdk`, `../jarvis-sim`) che non
importano Qt, perché chi implementa un backend non deve installare un toolkit
grafico.

### Le cinque decisioni che spiegano il resto

**PySide6 dietro `qtcompat`.** PyQt6 è GPL o licenza commerciale; PySide6 è
LGPL e permette di distribuire un'applicazione proprietaria. Tutto il progetto
importa Qt da un unico modulo, quindi cambiare binding è la modifica di un
file.

**Un solo clock a 60 FPS.** `QPropertyAnimation` governa le *dissolvenze* fra
stati — una alla volta, con easing. Il *moto continuo* (rotazione, onde,
respiro) è integrato sul tempo dal `FrameClock`. Otto animazioni con otto timer
indipendenti producono frame sfasati e micro-stuttering.

**Tre macchine a stati, non una.** `AppState`, `LinkState` e `AgentState` sono
indipendenti; l'errore è una *condizione sovrapposta*, non uno stato. Con un
enum unico, entrare in errore mentre Jarvis parla cancellerebbe l'informazione
che stava parlando, e all'uscita non si saprebbe dove tornare.

**Nessun `QGraphicsDropShadowEffect` su ciò che si muove.** È rasterizzazione
software a ogni frame: su un cerchio grande costa da solo l'intero budget di
16 ms. Alone e ombra sono pixmap pre-renderizzate e messe in cache, con chiave
quantizzata su colore *e* raggio — senza quantizzare il raggio, il respiro
manca la cache a ogni frame.

**JCP indipendente dal backend.** Envelope versionato `major.minor`, handshake
con capability, autenticazione, stream generici, spazio `ext.` per le
estensioni. `major` diverso rifiuta la sessione; `minor` diverso la accetta —
è la regola che permette di aggiornare GUI e backend in momenti diversi. Un
backend con un dialetto proprio si collega scrivendo **un solo adapter**.

**Un solo meccanismo di stream.** `stream.open/data/close` con un campo `kind`:
audio, video e file condividono lo stesso framing. Tre famiglie di messaggi
quasi identiche sarebbero tre da mantenere in parallelo.

**Il Mission Engine non decide nulla.** È una proiezione degli eventi JCP:
registra ciò che il backend dichiara, non avvia azioni, non stabilisce esiti,
non deduce fallimenti da un timeout. L'unica eccezione è deliberata — alla
caduta del canale le operazioni attive passano a "esito ignoto", che non è una
deduzione ma l'ammissione di non sapere.

---

## Configurazione

Precedenza: `config/defaults.toml` → `settings.json` utente → variabili
d'ambiente → argomenti CLI.

I file utente **non** stanno nel repository ma nelle directory standard
dell'OS (`%APPDATA%/Jarvis`, `~/Library/Application Support/Jarvis`,
`~/.config/jarvis`): la cartella d'installazione può essere in sola lettura e
un aggiornamento non deve cancellare log e preferenze.

Override da ambiente: `JARVIS_<SEZIONE>__<CHIAVE>`, ad esempio
`JARVIS_BACKEND__URL=ws://192.168.1.10:8765/jarvis`.

**Nessuna chiave API nel codice, nella configurazione o nei log.** I segreti
vivono nel keyring dell'OS; il formatter di logging redige automaticamente i
pattern noti.

---

## Livello operativo

**F9** apre la barra delle operazioni: missioni con le loro azioni, coda di
esecuzione, cronologia. Le richieste di conferma compaiono come schede in alto
a destra, con il rischio dichiarato dal backend e un conto alla rovescia; per
le operazioni distruttive nessun pulsante è predefinito.

La barra compare solo se il backend dichiara `missions` o `actions`. Tool
Inspector e Metrics Dashboard stanno nella Developer Console: servono a
misurare il backend, non a usarlo.

---

## Developer Console

**F12** apre timeline degli eventi, Event Inspector, monitor dei servizi,
diagnostica in tempo reale, vista del traffico JCP, Tool Inspector, Metrics
Dashboard e il pannello **Sessione**. Si aggiorna solo quando è visibile. Si
disattiva con `app.developer_tools = false`.

È lo strumento che distingue "l'evento non è arrivato alla GUI" da "il backend
non l'ha mai inviato" — la prima domanda quando qualcosa non funziona, e quella
a cui senza questi pannelli si risponde per congetture.

Il pannello Sessione fa tre cose distinte:

* **registra** la sessione JCP in un file `.jcpl` — segreti e blocchi audio
  redatti, perché una registrazione nasce per essere allegata a una
  segnalazione;
* **riproduce** una registrazione. Durante il replay l'interfaccia non reagisce
  ai comandi: una registrazione riproduce, non simula. Per la reattività si usa
  `--transport sim`;
* **verifica** la conformità del backend alla specifica, in un thread proprio.

Dettagli in
[`../jarvis-docs/03-simulazione-e-replay.md`](../jarvis-docs/03-simulazione-e-replay.md).

---

## Contribuire

- Le dipendenze si dichiarano nel costruttore e si registrano nel registry.
  Nessun singleton globale: è il punto in cui SOLID si rompe per primo.
- Gli slot Qt vanno decorati con `@safe_slot`: un'eccezione dentro uno slot
  può terminare il processo senza traccia utile.
- I nuovi eventi si aggiungono a `EventType` **con il payload dichiarato** in
  `PAYLOAD_TYPES`, altrimenti il bus li rifiuta in modalità rigorosa.
- Niente lavoro lungo nel thread GUI. Mai toccare oggetti Qt della UI da un
  thread diverso: pubblicare sul bus, che marshalla da solo.
