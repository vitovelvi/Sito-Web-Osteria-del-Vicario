# Simulazione, registrazione e replay

Tre strumenti che rispondono a tre domande diverse. Confonderli è l'errore più
comune, e produce fiducia mal riposta:

| Strumento | Domanda | Reagisce ai comandi? |
|---|---|---|
| **Simulazione** (`jarvis-sim`) | «come si comporta l'interfaccia se il backend fa *questo*?» | sì |
| **Registrazione** (`.jcpl`) | «com'era la sessione quando è successo?» | — |
| **Replay** | «fammelo rivedere» | **no** |

> **La simulazione reagisce, il replay riproduce.** Uno scenario risponde a ciò
> che il client fa; una registrazione è una sequenza fissa e la ripete identica
> anche se il client si comporta in modo diverso. Un replay non è mai una prova
> funzionale.

---

## 1. Ambiente di simulazione

`jarvis-sim` implementa JCP 1.0 per intero: handshake, capability, heartbeat,
chat in streaming, missioni, azioni, conferme, stream audio, e i modi in cui
una connessione si comporta male. Non dipende da Qt e si usa anche senza
interfaccia.

### Uso in-process

```python
from jarvis_sim import SimTransport
from jarvis_sim.library import by_name

transport = SimTransport(by_name("rete-instabile"))
```

`SimTransport` rispetta il contratto del trasporto (`connect`, `send`,
`receive`, `close`): al resto del sistema è indistinguibile da una WebSocket.

### Uso come server autonomo

```bash
jarvis-sim --list                          # elenca gli scenari
jarvis-sim --scenario tempesta --port 8765
jarvis-sim --scenario nominale --export scenario.json
jarvis-sim --file scenario.json --seed 42
```

Ogni connessione riceve un `SimTransport` nuovo, quindi due client collegati
allo stesso server non condividono stato.

### Dall'interfaccia

```bash
python main.py --transport sim --scenario conferme-distruttive
```

---

## 2. Anatomia di uno scenario

Uno scenario è **solo dati**: si serializza in JSON, si allega a una
segnalazione, si versiona accanto ai test. Descrive due cose distinte.

**Il profilo di canale** (`Channel`) — i modi in cui una connessione si
comporta male: `latency`, `jitter`, `handshake_delay`, `fail_connect`,
`refuse_handshake`, `drop_after`, `malformed_every`, `protocol_major/minor`,
`require_auth`, `emit_unknown`.

**Il comportamento** (`Behaviour`) — cosa fa il backend quando il canale
funziona: `reply_streaming`, `emit_audio`, `emit_missions`, `actions_min/max`,
`action_steps_min/max`, `step_delay`, `failure_rate`, `confirm_probability`,
`confirm_timeout_s`, `task_probability`.

Tenerli separati permette di **comporli** invece di scrivere uno scenario per
ogni combinazione:

```python
from jarvis_sim.library import NOMINAL

instabile_ma_sano = NOMINAL.with_channel(drop_after=2.0, jitter=0.8)
loquace          = NOMINAL.with_behaviour(actions_min=8, failure_rate=0.4)
```

### Riproducibilità

Il campo `seed` governa un unico `random.Random`. **Lo stesso seme produce la
stessa sessione**: stessi strumenti scelti, stessi fallimenti, stesse conferme
richieste. È ciò che trasforma uno scenario da aneddoto in prova ripetibile —
un difetto che compare «ogni tanto» diventa affrontabile solo quando si riesce
a farlo comparire a comando, e con un backend reale non si può.

### Compatibilità in avanti

`Scenario.from_dict` **ignora i campi sconosciuti**: uno scenario scritto per
una versione più recente resta caricabile, con i default per ciò che questa
build non conosce. È la stessa regola del protocollo, applicata agli scenari.

---

## 3. Gli scenari inclusi

| Nome | Cosa mette alla prova |
|---|---|
| `nominale` | il riferimento: latenza bassa, nessun guasto |
| `lento` | «Connessione a Jarvis…» osservabile; soglia di canale degradato |
| `rete-instabile` | riconnessione, backoff, esito ignoto delle operazioni in corso |
| `irraggiungibile` | l'interfaccia resta viva e riprova senza bloccarsi |
| `muto` | timeout di handshake, distinto da quello di connessione |
| `autenticazione-richiesta` | i tentativi si fermano invece di ripetersi all'infinito |
| `protocollo-incompatibile` | major diverso ⇒ sessione rifiutata senza interpretare |
| `protocollo-piu-recente` | minor superiore ⇒ sessione accettata |
| `rumoroso` | malformati, tipi sconosciuti, `ext.` non negoziate: nulla interrompe |
| `conferme-distruttive` | trattamento visivo del rischio e conto alla rovescia |
| `tempesta` | coda, metriche e tenuta della timeline sotto carico |
| `task-legacy` | `task.update` senza missioni resta supportato |
| `minimale` | il minimo che un backend conforme può offrire |

`jarvis_sim.library.names()` li elenca; `by_name()` solleva un `KeyError` che
**contiene i nomi validi** — un errore che dice solo «non trovato» costringe a
cercare il nome altrove.

---

## 4. Registrazione (formato JCPL)

Una riga JSON per record, la prima è l'intestazione:

```text
{"jcpl":1,"recorded_at":1730000000.0,"client":"jarvis-desktop 0.4.0","backend":"jarvis-sim 1.0.0"}
{"t":0.000,"dir":"out","env":{"v":"1.0","t":"session.hello", ...}}
{"t":0.412,"dir":"in","env":{"v":"1.0","t":"session.welcome", ...}}
```

Testuale di proposito: si legge con `head`, si filtra con `grep`, si allega a
una segnalazione. Il costo in byte è irrilevante rispetto al valore di poterlo
aprire ovunque.

### Redazione

Una registrazione nasce per **uscire dalla macchina** su cui è stata prodotta.
`redact_envelope` toglie, prima della scrittura:

* `auth.token` e `client.instance_id`;
* qualunque chiave che *sembri* un segreto — `token`, `secret`, `password`,
  `api_key` — a qualsiasi profondità;
* il contenuto dei `stream.data` oltre 64 caratteri, sostituito da
  `_omitted_chars`: conserva l'informazione utile (quanti byte, in che
  sequenza) senza gonfiare il file di megabyte che non aiutano a capire nulla.

Non è una funzione di sicurezza — chi ha accesso alla memoria del processo ha
già tutto. È una funzione di **igiene**: impedisce che un segreto finisca per
distrazione in un file destinato a essere condiviso.

### Registrare

Dall'interfaccia: **F12 → Sessione → Avvia registrazione**, poi *Salva…*.

Da codice:

```python
network.start_recording(note="coda appesa dopo la riconnessione")
...
registrazione = network.stop_recording()
registrazione.save(Path("~/segnalazioni/coda-appesa.jcpl").expanduser())
```

Il registratore ha un tetto di 20 000 messaggi e alza il flag `truncated`
quando lo raggiunge, invece di consumare memoria senza limite. Il pannello
mostra l'avviso: una registrazione troncata resta utile, ma va saputo.

### Rileggere

```python
from jarvis_sdk import Recording

r = Recording.load(path)
r.summary()   # {'messaggi': 412, 'durata_s': 37.4, 'in': 380, 'tipi': {...}, ...}
```

Una riga troncata — il caso normale di un file salvato mentre il processo
moriva, cioè proprio quello che interessa — viene **saltata**, non considerata
fatale.

---

## 5. Replay

`SessionReplayer` implementa lo stesso contratto del trasporto e ripete i soli
messaggi `in` rispettando gli intervalli originali.

```python
network.set_replay(recording)   # riavvia il servizio in modalità replay
network.set_replay(None)        # torna al backend configurato
```

Tre comportamenti da conoscere:

* **`send()` scarta.** Un replay non risponde: i messaggi del client vengono
  contati (`client_messages_ignored`) e buttati. Il pannello lo dichiara a
  chiare lettere, perché chi non lo sapesse concluderebbe che l'interfaccia è
  rotta.
* **`speed`** comprime o dilata i tempi; **`max_gap`** (3 s) tronca le pause
  lunghe — riguardare tre minuti di silenzio non aggiunge informazione.
* **`loop`** ripete dall'inizio, utile per lavorare su un difetto visivo.

---

## 6. Verifica di conformità

I punti di §10 della specifica sono affermazioni verificabili. Finché restano
prosa, «conforme a JCP» significa «l'autore crede di esserlo».

| id | Verifica |
|---|---|
| `handshake` | risponde a `session.hello` con `welcome` o `denied` motivato |
| `capabilities` | dichiara le proprie capability e non ne inventa di sconosciute |
| `heartbeat` | risponde al `ping` con un `pong` correlato |
| `unknown` | tollera un tipo di messaggio che non conosce |
| `malformed` | tollera un payload della forma sbagliata |
| `extensions` | ignora le `ext.` non negoziate senza chiudere il canale |

Ogni controllo apre una **connessione nuova**: un backend che fallisce
l'handshake ottiene comunque il verdetto sugli altri punti, perché sapere
quante cose sono rotte vale più che sapere quale si è rotta per prima. I
controlli sono tolleranti sui tempi e severi sulla semantica — un backend lento
è conforme, uno che chiude il canale davanti a un messaggio sconosciuto no.

```bash
python tools/jcp_validate.py --url ws://127.0.0.1:8765
python tools/jcp_validate.py --scenario nominale --json
```

Esce con `0` se conforme, `1` altrimenti: si mette in integrazione continua
senza interpretare l'output. Dall'interfaccia: **F12 → Sessione → Verifica il
backend**, che gira in un thread proprio — farlo nel thread grafico
bloccherebbe l'interfaccia proprio mentre si sta diagnosticando un problema di
connessione.

---

## 7. Quale strumento, quando

* «l'interfaccia si comporta male quando la rete cade» → **scenario**
  `rete-instabile`, riproducibile e automatizzabile in un test;
* «un utente segnala un difetto che non riesco a riprodurre» → chiedigli una
  **registrazione**, poi **replay**;
* «ho scritto un backend, è a posto?» → **conformità**;
* «il backend risponde ma l'interfaccia non mostra nulla» → **Developer
  Console**, traffico JCP: distingue «l'evento non è arrivato alla GUI» da «il
  backend non l'ha mai inviato».
