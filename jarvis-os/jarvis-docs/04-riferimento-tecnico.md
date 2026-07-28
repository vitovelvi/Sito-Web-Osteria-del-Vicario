# Riferimento tecnico

Questo documento descrive **com'è fatto** JARVIS OS: pacchetti, contratti,
modello di threading e invarianti. La motivazione delle scelte sta in
[`00-architettura-proposta.md`](00-architettura-proposta.md); il contratto di
rete in [`01-jcp-specifica.md`](01-jcp-specifica.md).

---

## 1. I cinque pacchetti

```
jarvis-protocol   →  nessuna dipendenza oltre pydantic. Il contratto.
jarvis-sdk        →  dipende da jarvis-protocol. Estensioni e strumenti.
jarvis-sim        →  dipende da jarvis-protocol. Backend simulato.
openclaw-adapter  →  dipende da jarvis-protocol. Primo dialetto.
jarvis-desktop    →  dipende da tutti e quattro, più Qt. L'applicazione.
```

La regola che li tiene separati: **nessuno dei primi quattro importa Qt**. Chi
implementa un backend, un adapter o un plugin non installa un toolkit grafico.
Se un `import` violasse la regola, il pacchetto smetterebbe di essere
riutilizzabile fuori dall'applicazione — ed è esattamente ciò che accade quando
un protocollo nasce dentro un client.

Verifica meccanica:

```bash
grep -rn "PySide6\|PyQt" jarvis-protocol jarvis-sdk jarvis-sim openclaw-adapter
```

---

## 2. Il flusso di un messaggio

```
 backend
    │  dict grezzo (il dialetto del backend)
    ▼
 transport/      apre, invia, riceve, chiude. Non conosce JCP.
    │  dict
    ▼
 adapter/        traduce dialetto ↔ JCP. Non conosce il dominio.
    │  Envelope (JCP)
    ▼
 dispatcher      unico punto che conosce i tipi di messaggio.
    │  eventi di dominio
    ▼
 bus  ──► StateManager, MissionEngine, CapabilityManager, IdentityService
    │
    ▼
 ui/             disegna. Non parla mai con la rete.
```

Ogni freccia è un cambio di livello di astrazione, e ogni livello può essere
sostituito senza toccare gli altri. Le due sostituzioni che questo rende
possibili: un backend con un dialetto diverso richiede **solo** un nuovo adapter;
un secondo client (CLI, web, dispositivo) riparte dal `transport` e ricostruisce
tutto sopra.

### Le tre regole del confine

1. **Il trasporto muove dizionari.** Non valida, non interpreta, non conosce i
   tipi di messaggio. Un trasporto che sapesse cos'è un `session.hello` non
   sarebbe sostituibile con uno su TCP o su pipe.
2. **L'adapter non decide.** Può avere stato *tecnico* (una mappa di
   identificativi); non conserva stato di dominio, non tocca il bus, non
   conosce lo state manager.
3. **La UI non parla con la rete.** Legge il bus e chiama i metodi del
   `NetworkService`. Nessun widget costruisce buste JCP.

---

## 3. `jarvis-protocol` — il contratto

| Modulo | Contenuto |
|---|---|
| `envelope.py` | `Envelope`: `{v,id,t,ts,p,c}` sul filo, nomi lunghi in Python via alias pydantic. Id ULID monotoni, ordinabili anche entro lo stesso millisecondo. |
| `messages.py` | `MessageType` e i payload tipizzati di ciascun tipo. |
| `capabilities.py` | `Capability`, `CLIENT_CAPABILITIES`, negoziazione bidirezionale. |
| `missions.py` | Stati di missione e azione, livelli di rischio. |
| `auth.py` | Schemi `none` / `token` / `challenge`. Nessun segreto qui dentro. |
| `version.py` | `PROTOCOL_VERSION` `major.minor`. |
| `errors.py` | `ProtocolError`, `TransportError`. |

### Perché `TransportError` sta nel protocollo

Perché fa parte dell'**interfaccia del trasporto**, non dell'applicazione. Un
guasto simulato da `jarvis-sim` dev'essere indistinguibile da uno reale: se
l'eccezione vivesse in `jarvis-desktop`, il simulatore non potrebbe sollevarla
senza dipendere dall'applicazione che dovrebbe mettere alla prova.

### Le due regole di versione

* **`major` diverso ⇒ sessione rifiutata.** Nessun tentativo di
  interpretazione parziale.
* **`minor` diverso ⇒ sessione accettata.** È ciò che permette di aggiornare
  GUI e backend in momenti diversi. Chi riceve un campo che non conosce lo
  ignora.

Corollario applicato ovunque, anche fuori dal protocollo (vedi
`Scenario.from_dict`): **i campi sconosciuti si ignorano, non fanno fallire.**

---

## 4. `jarvis-desktop/core` — il nucleo non visivo

`core/` **non importa mai da `ui/`**. È verificato implicitamente dai test: i
test del nucleo girano senza display, e se uno richiedesse una finestra
vorrebbe dire che la regola si è rotta.

### `eventbus.py`

Bus tipizzato su `QObject`.

* `publish()` è chiamabile **da qualunque thread**; la consegna avviene sempre
  nel thread grafico (Qt `AutoConnection`). È l'unico punto di marshalling del
  sistema: nessun altro modulo deve preoccuparsi dei thread.
* I riferimenti ai metodi legati sono **deboli**: un widget distrutto non tiene
  in vita il proprio handler né riceve eventi da un oggetto morto.
* Cronologia ad anello con `last()`, `history()`, `replay_last` alla
  sottoscrizione — un pannello aperto dopo l'evento vede comunque lo stato
  corrente invece di restare vuoto fino al prossimo aggiornamento.
* Eventi senza sottoscrittori vengono contati (*dead letter*): un contatore che
  cresce è la firma di un evento pubblicato ma mai consumato.
* Spazio `plugin.` riservato alle estensioni.

Un evento nuovo si dichiara in `EventType` **con il payload** in
`PAYLOAD_TYPES`, altrimenti il bus lo rifiuta in modalità rigorosa.

### `state/`

Tre macchine **ortogonali**, non un enum unico:

| Macchina | Valori |
|---|---|
| `AppState` | `BOOTING`, `RUNNING`, `STANDBY`, `SHUTTING_DOWN` |
| `LinkState` | `OFFLINE`, `CONNECTING`, `ONLINE`, `DEGRADED` |
| `AgentState` | `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`, `SPEAKING` |

`ErrorCondition` è una **condizione sovrapposta**, non uno stato: con un enum
unico, entrare in errore mentre Jarvis parla cancellerebbe l'informazione che
stava parlando, e all'uscita non si saprebbe dove tornare.

Il `resolver` combina le tre macchine più l'errore in un unico `VisualMode`
(`BOOT`, `OFFLINE`, `CONNECTING`, `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`,
`SPEAKING`, `SUCCESS`, `ERROR`, `STANDBY`) secondo una **tabella di precedenza
dichiarata**, non secondo una catena di `if` sparsa nei widget.

**Stato ottimistico e riconciliazione.** L'interfaccia può anticipare un
`AgentState` localmente — premere il microfono passa subito a `LISTENING` — ma
la transizione dev'essere confermata dal backend entro un timeout, altrimenti
viene revocata. `set_agent_state(..., authoritative=True)` cancella la
riconciliazione **anche quando lo stato non cambia**: è il caso più comune, il
backend che conferma ciò che l'interfaccia aveva già anticipato.

### `missions/`

Il Mission Engine è una **proiezione**. Registra ciò che il backend dichiara:
non avvia azioni, non stabilisce esiti, non deduce fallimenti da un timeout.

L'unica eccezione è deliberata: `on_link_lost()` porta missioni e azioni attive
in `UNKNOWN`. Non è una deduzione ma l'**ammissione di non sapere**, e per
questo le azioni `UNKNOWN` sono escluse dal tasso di successo — contarle come
fallimenti attribuirebbe al backend guasti che potrebbe non aver avuto.

`derived_progress` calcola l'avanzamento di una missione contando come concluse
le azioni **assenti dagli attivi**, non cercando quelle concluse fra gli
attivi — da cui sono appena state rimosse.

### `registry.py`

Service registry con iniezione dal costruttore e ordine di avvio topologico.
Nessun singleton globale: è il punto in cui SOLID si rompe per primo.

* Un servizio non critico che fallisce viene isolato: l'applicazione parte
  ugualmente e il pannello Servizi mostra `FAILED`.
* `IService` è un `Protocol` runtime-checkable e non una ABC, perché le
  metaclassi di `QObject` e `ABCMeta` sono incompatibili.
* `restart(key)` riavvia un singolo servizio senza toccare gli altri.

### `frameclock.py`

**Una sola sorgente del tempo a 60 FPS.** Il moto continuo (rotazione, onde,
respiro) è integrato sul tempo del clock; `QPropertyAnimation` governa solo le
*dissolvenze* fra stati. Otto animazioni con otto timer indipendenti producono
frame sfasati e micro-stuttering.

### `settings.py`

Precedenza: `config/defaults.toml` → `settings.json` utente → variabili
d'ambiente `JARVIS_<SEZIONE>__<CHIAVE>` → argomenti CLI. Una configurazione non
valida **ricade sui default e non impedisce l'avvio**: un'interfaccia che non
parte per una virgola di troppo non è diagnosticabile.

I file utente stanno nelle directory standard dell'OS (`platformdirs`), non
nella cartella d'installazione, che può essere in sola lettura e viene
sovrascritta dagli aggiornamenti.

**Nessuna chiave API nel codice, nella configurazione o nei log.** I segreti
vivono nel keyring dell'OS; il formatter di logging redige i pattern noti.

---

## 5. `jarvis-desktop/network`

| Modulo | Responsabilità |
|---|---|
| `transport/base.py` | contratto: `connect`, `send`, `receive`, `close` |
| `transport/websocket.py` | trasporto reale |
| `adapters/native.py` | backend già conforme a JCP: traduzione identità |
| `adapters/base.py` | contratto dell'adapter lato applicazione |
| `dispatcher.py` | unico punto che conosce i tipi di messaggio |
| `reconnect.py` | backoff esponenziale, jitter, interruttore automatico |
| `service.py` | thread asyncio dedicato, sessione, heartbeat, registrazione |

`NetworkService` possiede **l'unico loop asyncio** dell'applicazione, confinato
in un `QThread` dedicato. La sua unica frontiera con la GUI sono le
pubblicazioni sul bus: nessun oggetto Qt della UI viene toccato da lì.

Metodi pubblici usati dall'interfaccia: `send_chat`, `cancel`, `voice_start`,
`voice_stop`, `send`, `health`, `diagnostics`, `traffic_history`,
`start_recording`, `stop_recording`, `set_replay`, `transport_factory`.

### Riconnessione

Backoff esponenziale con jitter, e un **interruttore automatico** dopo
`circuit_breaker_threshold` tentativi consecutivi falliti. Un errore
`retryable=false` — protocollo incompatibile, autenticazione rifiutata — ferma
i tentativi invece di ripeterli all'infinito: riprovare con le stesse
credenziali sbagliate non produrrà mai un esito diverso.

---

## 6. `jarvis-desktop/ui`

`ui/` può importare da `core/`, mai il contrario.

| Modulo | Contenuto |
|---|---|
| `theme/` | design token in JSON → QSS generato |
| `frameless.py` | finestra senza cornice, ombra in pixmap cache |
| `chrome.py`, `hud.py` | barra, stato, identità dichiarata |
| `reactor/` | il nucleo animato: `params`, `animator`, `renderers`, `widget` |
| `notifications.py` | toast, con `bottom_offset` per non coprire la barra di stato |
| `ops/` | livello operativo (**F9**): missioni, coda, conferme, metriche, strumenti |
| `devtools/` | Developer Console (**F12**) |

### Regole di rendering

**Nessun `QGraphicsDropShadowEffect` su ciò che si muove.** È rasterizzazione
software a ogni frame: su un cerchio grande costa da solo l'intero budget di
16 ms. Alone e ombra sono pixmap pre-renderizzate in cache, con chiave
quantizzata su **colore *e* raggio** — senza quantizzare il raggio, il respiro
manca la cache a ogni frame e la cache diventa un costo puro.

**Una capability non dichiarata non produce un pulsante disabilitato**, ma un
pannello che non viene proprio costruito. L'interfaccia mostra ciò che il
backend sa fare, non ciò che si spera sappia fare.

### Developer Console (F12)

Sette schede: **Eventi** (timeline + Event Inspector), **Servizi**,
**Diagnostica**, **Strumenti** (Tool Inspector), **Metriche**, **Traffico JCP**,
**Sessione** (registrazione, replay, conformità).

Si aggiorna **solo quando è visibile** e si disattiva con
`app.developer_tools = false`.

È lo strumento che distingue «l'evento non è arrivato alla GUI» da «il backend
non l'ha mai inviato»: la prima domanda quando qualcosa non funziona, e quella
a cui senza questi pannelli si risponde per congetture.

---

## 7. Modello di threading

| Thread | Cosa ci gira |
|---|---|
| **GUI** | tutto Qt, il `FrameClock`, tutti gli handler del bus |
| **rete** | l'unico loop asyncio: trasporto, sessione, heartbeat |
| **verifica** | thread effimero della conformità, che apre connessioni proprie |

Tre regole, senza eccezioni:

1. **Mai lavoro lungo nel thread GUI.** Il budget è 16 ms per frame.
2. **Mai toccare oggetti Qt della UI da un thread diverso.** Si pubblica sul
   bus, che marshalla da solo.
3. **Ogni slot Qt è decorato con `@safe_slot`.** Un'eccezione dentro uno slot
   può terminare il processo senza traccia utile: il decoratore la registra
   nella categoria giusta e lascia vivere l'interfaccia.

### Arresto

`NetworkService.stop()` **invita** il ciclo a finire: chiude il canale e sveglia
l'attesa fra due tentativi, poi aspetta il thread. Non ferma il loop da sotto —
un `loop.stop()` mentre il ciclo attende fa uscire `asyncio.run` con un
`RuntimeError`, e ogni chiusura ordinaria finirebbe nei log come un guasto. In
log dove ogni uscita sembra un errore, i guasti veri smettono di distinguersi.

Il `loop.stop()` resta come ripiego dopo tre secondi, dove una traccia è
effettivamente un'informazione: significa che qualcosa non ha ceduto.

---

## 8. Invarianti

Le affermazioni che devono restare vere. Un cambiamento che ne rompe una è un
cambiamento di architettura, non un dettaglio.

1. **L'interfaccia non è il cervello.** Non decide, non deduce, non indovina.
   Se il backend non ha dichiarato un modello, l'HUD scrive «modello non
   dichiarato».
2. **`core/` non importa da `ui/`.**
3. **`jarvis-protocol`, `jarvis-sdk`, `jarvis-sim` e `openclaw-adapter` non
   importano Qt.**
4. **La consegna degli eventi avviene sempre nel thread GUI.**
5. **Un campo sconosciuto si ignora**, in JCP come negli scenari come nei
   manifesti dei plugin.
6. **Un adapter non conserva stato di dominio**, e se ha stato tecnico
   implementa `reset()` — dimenticarlo produce difetti che si manifestano solo
   alla *seconda* connessione.
7. **Nessun segreto nel codice, nella configurazione versionata o nei log.**
8. **Il Mission Engine registra, non conclude.** L'unica eccezione è `UNKNOWN`
   alla caduta del canale, ed è un'ammissione, non una deduzione.
9. **Un plugin può inviare solo messaggi `ext.`**: altrimenti potrebbe
   dichiarare esiti che il backend non ha prodotto, e l'interfaccia smetterebbe
   di essere una proiezione fedele.

---

## 9. Punti di estensione

| Voglio… | Estendo | Senza toccare |
|---|---|---|
| collegare un backend con un dialetto proprio | `BaseAdapter` (SDK) | trasporto, dispatcher, UI |
| aggiungere un tipo di stream (video, file, sensori) | il campo `kind` di `stream.open` | il framing del protocollo |
| aggiungere una funzione negoziabile | una `Capability`, o `ext.<vendor>.<nome>` | la versione del protocollo |
| aggiungere un pannello | `IPlugin` + `plugin.json` (SDK) | il core |
| aggiungere una situazione di prova | uno `Scenario` composto | il simulatore |
| aggiungere un trasporto | il contratto `ITransport` | tutto il resto |

---

## 10. Comandi di uso quotidiano

```bash
# applicazione
cd jarvis-desktop
.venv/bin/python main.py --transport sim --scenario rete-instabile
.venv/bin/python main.py --url ws://host:8765/jarvis
.venv/bin/python main.py --no-translucent --log-level DEBUG

# test
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest ../jarvis-sdk/tests ../jarvis-sim/tests -q
.venv/bin/ruff check . ../jarvis-protocol ../jarvis-sdk ../jarvis-sim ../openclaw-adapter

# backend
jarvis-sim --list
jarvis-sim --scenario tempesta
python tools/jcp_validate.py --url ws://127.0.0.1:8765
```

---

## 11. Glossario

**Adapter** — traduttore fra il dialetto di un backend e JCP. Non decide nulla.

**Busta** (*envelope*) — l'involucro comune di ogni messaggio JCP: versione,
id, tipo, timestamp, payload, correlazione.

**Capability** — funzione dichiarata e negoziata all'handshake. Ciò che il
backend *dichiara* di saper fare, non ciò che si spera sappia fare.

**Condizione sovrapposta** — l'errore: non sostituisce lo stato, gli si
sovrappone, e alla sua uscita si torna dove si era.

**JCPL** — formato di registrazione di una sessione, una riga JSON per
messaggio.

**Proiezione** — struttura che riflette lo stato dichiarato da qualcun altro
senza aggiungervi conclusioni proprie. Il Mission Engine è una proiezione.

**Riconciliazione** — la conferma, entro un timeout, di uno stato che
l'interfaccia aveva anticipato localmente. Senza conferma, si revoca.

**Scenario** — descrizione dichiarativa e riproducibile del comportamento di un
backend simulato.

**VisualMode** — l'unico stato che i widget consumano, risolto dalle tre
macchine più l'errore secondo una precedenza dichiarata.
