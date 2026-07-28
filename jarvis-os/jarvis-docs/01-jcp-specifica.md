# JARVIS Communication Protocol (JCP) — versione 1.0

Protocollo di comunicazione fra l'interfaccia desktop di J.A.R.V.I.S. e un
backend conversazionale.

**JCP non è il protocollo di OpenClaw.** È il dialetto che la GUI parla; OpenClaw
è il primo backend a essere collegato, tramite un adapter. Se domani il backend
cambia, si scrive un altro adapter e nient'altro dell'applicazione si accorge
del cambiamento.

---

## 1. Principi

1. **Il backend è l'autorità.** La GUI non deduce nulla: mostra ciò che il
   backend dichiara. Ciò che non è stato dichiarato non viene mostrato.
2. **Ignorare è lecito, indovinare no.** Un campo o un messaggio sconosciuto si
   scarta in silenzio. Un campo malformato dove lo schema ne prevede uno valido
   invalida il messaggio, non la sessione.
3. **Nessun messaggio può chiudere il canale**, tranne quelli che lo dicono
   esplicitamente (`session.denied`, `session.close`) e il fallimento
   dell'handshake.
4. **Estendere non deve rompere.** Aggiungere un campo, un messaggio o una
   capability è sempre retrocompatibile. Rimuoverli richiede una versione
   maggiore.

---

## 2. Trasporto

JCP è indipendente dal trasporto. Requisiti minimi: canale bidirezionale,
consegna ordinata, messaggi delimitati. WebSocket è il trasporto di
riferimento; stdio, TCP e pipe locali sono ammessi.

Codifica di riferimento: **JSON UTF-8, un messaggio per frame**.

Se entrambi i lati dichiarano la capability `stream.binary`, i messaggi
`stream.data` possono viaggiare come **frame binari** con intestazione:

```
byte 0        : versione del framing (0x01)
byte 1..16    : stream_id, 16 byte ASCII, riempito con spazi
byte 17..20   : sequenza, uint32 big-endian
byte 21..     : payload
```

Motivazione: base64 aggiunge il 33% di traffico. Su una risposta vocale di
trenta secondi a 24 kHz sono circa 480 KB in più — irrilevante in locale,
non irrilevante attraverso la rete. Il framing binario è **facoltativo e
negoziato**: un backend che non lo dichiara continua a ricevere JSON.

---

## 3. Envelope

Ogni messaggio, in entrambe le direzioni, ha la stessa busta:

```jsonc
{
  "v":  "1.0",           // versione del protocollo, "major.minor"
  "id": "01J8…",         // ULID monotono: ordinabile nel tempo
  "t":  "chat.delta",    // tipo, dominio puntato
  "ts": 1730000000.123,  // epoch dell'emissione, secondi
  "p":  { },             // payload, forma dipendente dal tipo
  "c":  "01J7…"          // opzionale: id del messaggio correlato
}
```

I nomi sono brevi di proposito: la busta si ripete su ogni frame di uno stream
audio, dove il rapporto fra intestazione e contenuto conta.

### Versionamento

`major` cambia solo per modifiche incompatibili. `minor` cresce a ogni aggiunta.

* **major diverso** → sessione rifiutata con `session.denied`, codice
  `protocol.unsupported`. Non si tenta di interpretare.
* **minor diverso** → sessione accettata. Il lato più vecchio ignora ciò che non
  conosce; il lato più recente non deve pretendere le novità senza averle
  negoziate via capability.

Questa è la regola che permette di aggiornare GUI e backend in momenti diversi,
cioè l'unico modo in cui un progetto sopravvive agli anni.

### Correlazione

`c` contiene l'`id` del messaggio a cui si risponde. È ciò che rende possibile
`richiesta → attesa della risposta` senza che il chiamante gestisca gli
identificativi.

---

## 4. Handshake

```
client                                   server
  │──── session.hello ────────────────────▶│
  │                                        │  verifica versione e credenziali
  │◀──── session.welcome ──────────────────│  (oppure session.denied)
  │                                        │
  │◀════ sessione attiva ═════════════════▶│
```

L'handshake ha un **timeout proprio**, distinto da quello di connessione: un
backend che accetta il socket ma non risponde è un caso reale (servizio in
avvio, porta occupata da un altro processo) e va distinto da un host
irraggiungibile.

### `session.hello` — client → server

```jsonc
{
  "protocol": {"major": 1, "minor": 0},
  "client": {
    "name": "jarvis-desktop", "version": "0.4.0",
    "instance_id": "…",        // stabile fra i riavvii
    "device": "…", "platform": "…", "locale": "it"
  },
  "capabilities": ["chat.stream", "tts.stream", "…"],
  "auth": {"scheme": "token", "token": "…"}   // opzionale
}
```

### `session.welcome` — server → client

```jsonc
{
  "protocol": {"major": 1, "minor": 0},
  "server": {
    "name": "OpenClaw", "version": "2.4.1",
    "assistant_name": "J.A.R.V.I.S.",
    "model": "…", "persona": "…", "accent_color": "#3fa9f5",
    "instance_id": "…"
  },
  "capabilities": ["…"],
  "session_id": "…",
  "limits": {"max_message_bytes": 8388608, "max_stream_chunk_bytes": 65536}
}
```

`limits` esiste perché la GUI deve poter rifiutare **prima dell'invio** ciò che
il backend rifiuterebbe dopo: un allegato troppo grande va segnalato subito, non
dopo trenta secondi di trasferimento.

### `session.denied` — server → client

```jsonc
{"code": "auth.denied", "message": "Token non valido", "retryable": false}
```

Dopo `session.denied` il canale si chiude. Se `retryable` è falso, la GUI
**smette di riprovare** con le stesse credenziali e lo dice all'utente: insistere
con un token sbagliato non lo rende valido, riempie solo i log.

---

## 5. Autenticazione

Tre schemi, dichiarati in `auth.scheme`:

| Schema | Uso |
|---|---|
| `none` | Backend su `localhost` in un ambiente fidato. Default. |
| `token` | Segreto condiviso, inviato nell'handshake. |
| `challenge` | Riservato a una versione futura: il server invia un nonce, il client risponde con un HMAC. Definito ora per non doverlo infilare a forza dopo. |

**Il token non sta nella configurazione né nel codice**: vive nel keyring
dell'OS e viene letto all'avvio. Il formatter di logging redige gli schemi noti.

Nota onesta sul modello di minaccia: con un backend su `localhost`,
l'autenticazione non protegge dalla rete ma da **altri processi locali** che
potrebbero connettersi alla stessa porta. Su una macchina personale a utente
singolo è una protezione modesta; diventa necessaria appena il backend ascolta
su un'interfaccia non locale. Per questo lo schema è configurabile e non
imposto.

---

## 6. Catalogo dei messaggi

Direzione: **C→S** client verso server, **S→C** server verso client.

### Sessione e canale

| Tipo | Dir | Payload |
|---|---|---|
| `session.hello` | C→S | vedi §4 |
| `session.welcome` | S→C | vedi §4 |
| `session.denied` | S→C | `code`, `message`, `retryable` |
| `session.close` | ↔ | `code`, `message` |
| `link.ping` | ↔ | — |
| `link.pong` | ↔ | — (con `c`) |

L'heartbeat è **applicativo** e non il ping di protocollo del trasporto: misura
la latenza end-to-end, che è l'informazione utile. Un socket TCP aperto non
garantisce che dall'altra parte ci sia ancora qualcuno.

### Assistente e conversazione

| Tipo | Dir | Payload |
|---|---|---|
| `agent.state` | S→C | `state` ∈ {idle, listening, thinking, executing, speaking}, `reason?` |
| `chat.send` | C→S | `text`, `message_id`, `attachments?` |
| `chat.delta` | S→C | `text`, `message_id` |
| `chat.done` | S→C | `message_id`, `reason?` |
| `chat.cancel` | C→S | `message_id?` |
| `voice.start` / `voice.stop` | C→S | — |

`agent.state` è **autorevole**: la GUI può anticiparlo localmente per reattività
percepita, ma deve riconciliarsi entro un timeout.

### Stream (audio, video, file)

Un solo meccanismo per tutti i flussi. Nella versione precedente l'audio aveva
messaggi propri; con webcam e allegati sarebbero diventate tre famiglie quasi
identiche, da mantenere in parallelo.

| Tipo | Dir | Payload |
|---|---|---|
| `stream.open` | ↔ | `stream_id`, `kind` ∈ {audio, video, file}, `encoding`, `sample_rate?`, `channels?`, `mime?`, `filename?`, `related_id?` |
| `stream.data` | ↔ | `stream_id`, `seq`, `data` (base64, o frame binario) |
| `stream.close` | ↔ | `stream_id`, `truncated?` |

`related_id` collega lo stream al messaggio che lo ha generato: è ciò che
permette di sapere **quale** risposta si sta ascoltando.

`seq` è obbligatorio e monotono per stream. Un buco nella sequenza è
rilevabile: il consumatore decide se attendere o proseguire, ma non ignora il
problema in silenzio.

### Task, telemetria, errori

| Tipo | Dir | Payload |
|---|---|---|
| `task.update` | S→C | `task_id`, `label`, `status`, `progress?` |
| `telemetry.system` | C→S | metriche della macchina locale |
| `error` | ↔ | `code`, `message`, `severity`, `detail?`, `retryable?` |

`error` **non** chiude la sessione. Segnala un problema su una richiesta o sul
backend; il canale resta utilizzabile.

### Estensioni

| Tipo | Dir | Payload |
|---|---|---|
| `ext.<vendore>.<nome>` | ↔ | libero |

Regole:

1. Il prefisso `ext.` è **riservato** alle estensioni: il core non lo userà mai.
2. Un'estensione va dichiarata come capability `ext.<vendore>.<nome>` prima di
   essere usata. Inviarla senza averla negoziata è un errore del mittente.
3. Chi riceve un `ext.*` sconosciuto lo **ignora**. Sempre.
4. I plugin della GUI ricevono gli `ext.*` sul bus con namespace
   `plugin.<id>.…`, quindi possono estendere il protocollo senza toccare il
   core — che è il punto dell'intero meccanismo.

---

## 7. Capability

Una capability è una funzione che un lato **dichiara di saper fare**. La
negoziazione è bidirezionale: anche il backend deve sapere cosa la GUI sa
mostrare, altrimenti invierebbe flussi che nessuno consuma.

| Nome | Significato |
|---|---|
| `chat.stream` | risposte token per token |
| `chat.cancel` | interruzione di una risposta in corso |
| `tts.stream` | il backend sintetizza la voce e ne invia lo stream |
| `stt.stream` | il backend accetta audio in ingresso |
| `vision.ingest` | il backend accetta frame video |
| `tasks` | eventi di avanzamento delle azioni |
| `identity` | il backend dichiara nome, modello, persona |
| `telemetry.system` | il backend accetta metriche locali |
| `stream.binary` | frame binari per `stream.data` |
| `auth.token` | il backend supporta l'autenticazione a token |
| `ext.*` | estensioni |

Effetto pratico: un pannello la cui capability non è dichiarata **non viene
costruito**. Non viene nascosto per prudenza, non viene mostrato disabilitato:
non esiste. Mostrare un pannello che non si popolerà mai è peggio che non
mostrarlo.

---

## 8. Codici di errore

| Codice | Significato | `retryable` |
|---|---|---|
| `protocol.unsupported` | versione maggiore incompatibile | no |
| `protocol.malformed` | messaggio non conforme | sì |
| `auth.required` | credenziali assenti | no |
| `auth.denied` | credenziali rifiutate | no |
| `capability.missing` | funzione non disponibile | no |
| `rate_limit` | troppe richieste | sì |
| `unavailable` | backend temporaneamente non operativo | sì |
| `internal` | guasto lato backend | sì |

`retryable` è un'informazione per la GUI, non una cortesia: distingue "riprova
fra poco" da "smetti e dillo all'utente".

---

## 9. Adapter Layer

```
      GUI  ──▶  eventi di dominio
                     ▲
                     │
              MessageDispatcher          (conosce solo JCP)
                     ▲
                     │  JCP
              IBackendAdapter
              ╱             ╲
    NativeJcpAdapter    OpenClawAdapter      … altri backend
              ╲             ╱
                 ITransport                 (WebSocket, mock, stdio)
```

L'adapter traduce fra il dialetto reale del backend e JCP, in entrambe le
direzioni. Ha tre responsabilità e nessun'altra:

1. `to_backend(envelope)` — da JCP al dialetto del backend;
2. `from_backend(raw)` — dal dialetto del backend a JCP;
3. dichiarare quali capability sa mappare.

Un adapter **non** decide, non conserva stato di dominio e non tocca il bus.
Se un adapter iniziasse ad avere logica di stato, sarebbe il segnale che il
confine è stato attraversato.

`NativeJcpAdapter` è l'identità: si usa con i backend che parlano JCP
direttamente, e serve anche da riferimento su cosa un adapter *non* deve fare.

---

## 10. Conformità

Un backend è conforme a JCP 1.0 se:

1. risponde a `session.hello` con `session.welcome` o `session.denied`;
2. dichiara le proprie capability e non usa funzioni non dichiarate;
3. risponde a `link.ping` con `link.pong` correlato;
4. non chiude il canale per un messaggio sconosciuto;
5. usa `stream.*` per ogni flusso continuo;
6. usa il prefisso `ext.` per tutto ciò che non è in questa specifica.

Il backend simulato in `network/mock/` implementa JCP 1.0 per intero ed è il
riferimento eseguibile di questa specifica.

---

## 11. Livello operativo: missioni e azioni

Aggiunto in JCP 1.0 accanto ai messaggi base. Il protocollo aveva già
`task.update`, sufficiente per una barra di avanzamento ma non per
rappresentare cosa un assistente **fa**.

### Modello

* **Missione** — un obiettivo, di solito nato da un messaggio dell'utente.
  Può contenere sotto-missioni (`parent_id`).
* **Azione** — una singola invocazione di uno strumento dentro una missione.
  Ha coda, stato, durata ed esito.
* **Strumento** — ciò che l'azione usa. Il registro è dichiarato dal backend.

### Messaggi

| Tipo | Dir | Payload |
|---|---|---|
| `mission.started` | S→C | `mission_id`, `title`, `goal?`, `parent_id?`, `related_message_id?` |
| `mission.updated` | S→C | `mission_id`, `status`, `progress?`, `summary?` |
| `mission.finished` | S→C | `mission_id`, `status`, `summary?`, `error?` |
| `mission.cancel` | C→S | `mission_id` |
| `action.queued` | S→C | `action_id`, `tool`, `title`, `mission_id?`, `args_preview?`, `risk`, `position?` |
| `action.started` | S→C | `action_id` |
| `action.progress` | S→C | `action_id`, `progress?`, `note?` |
| `action.finished` | S→C | `action_id`, `status`, `result_preview?`, `error?`, `duration_ms?` |
| `action.confirm_request` | S→C | `request_id`, `action_id`, `title`, `detail?`, `risk`, `expires_in_s?`, `options?` |
| `action.confirm_reply` | C→S | `request_id`, `approved`, `option?`, `remember?` |
| `action.cancel` | C→S | `action_id` |
| `tool.registry` | S→C | `tools[]`, `replace` |

Capability: `missions`, `actions`, `actions.cancel`, `actions.confirm`,
`tools.registry`.

### Regole

1. **Il backend decide, l'interfaccia registra.** Gli unici messaggi verso il
   backend sono `action.confirm_reply`, `action.cancel` e `mission.cancel` —
   e il primo trasporta una decisione dell'**utente**, non dell'interfaccia.
2. **`args_preview` è già ridotta dal backend.** Il protocollo non trasporta
   gli argomenti completi: possono contenere segreti, e la GUI non ha motivo
   di riceverli per mostrarli.
3. **Il rischio è dichiarato, mai dedotto.** La GUI decide quanto insistere su
   una conferma in base a `risk`; non prova a indovinarlo dal nome dello
   strumento.
4. **`retryable` vale anche qui**: `expires_in_s` dice quando smettere di
   chiedere. Una conferma a schermo per un'operazione già abbandonata invita a
   un gesto senza effetto.
5. **`task.update` resta valido** e viene proiettato come azione senza
   missione. Due rappresentazioni parallele nella GUI sarebbero il modo più
   rapido per farle divergere.

### Esito ignoto

Alla caduta del canale, missioni e azioni ancora attive assumono lo stato
`unknown`. Non è un esito dichiarato dal backend: è l'ammissione che
l'interfaccia **non sa più** come siano finite. Le due alternative sarebbero
peggiori — marcarle fallite significherebbe inventare, lasciarle "in corso"
significherebbe mostrare per sempre un'attività che nessuno sta più svolgendo.

Le azioni `unknown` sono **escluse dal tasso di successo**: contarle come
fallite falserebbe la metrica per colpa della rete.
