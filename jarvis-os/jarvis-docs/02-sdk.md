# SDK — guida

`jarvis-sdk` contiene ciò che serve per **estendere** la piattaforma senza
dipendere dall'interfaccia. L'unica dipendenza è `jarvis-protocol`: chi scrive
un plugin o un adapter non installa Qt.

```bash
pip install jarvis-sdk
```

---

## 1. Scrivere un adapter

Un adapter traduce fra il dialetto di un backend e JCP. Serve quando il backend
non parla JCP nativamente — che è il caso normale, perché JCP è nato per la GUI
e i backend esistono già.

### Il minimo

```python
from jarvis_protocol.messages import MessageType
from jarvis_sdk import BaseAdapter

class MioAdapter(BaseAdapter):
    name = "mio-backend"

    TO_BACKEND = {MessageType.CHAT_SEND: "invia"}
    FROM_BACKEND = {"risposta": MessageType.CHAT_DELTA}
    CORRELATION_KEY = "request_id"

    def translate_outgoing(self, envelope):
        return {"testo": envelope.payload["text"]}

    def translate_incoming(self, jcp_type, data):
        return {"text": data["frammento"], "message_id": data["id"]}
```

Le due tabelle coprono la maggior parte del lavoro. I due metodi gestiscono i
payload.

### Le tre regole

**Un adapter non decide.** Non conserva stato di dominio, non tocca il bus, non
conosce lo state manager. Può avere stato *tecnico* — una mappa di
identificativi, un contatore di sequenza. La distinzione fra stato di traduzione
e stato di dominio è il confine oltre il quale la sostituibilità del backend è
persa.

**Restituire `None` è lecito, inventare no.** Se un valore non è traducibile —
uno stato che il backend chiama in un modo che JCP non prevede — si scarta il
messaggio:

```python
def translate_incoming(self, jcp_type, data):
    if jcp_type == MessageType.AGENT_STATE:
        stato = {"pensa": "thinking"}.get(data["v"])
        return None if stato is None else {"state": stato}   # niente ipotesi
```

L'interfaccia resterà sull'ultimo stato confermato. Inventarne uno la farebbe
mostrare con sicurezza qualcosa che nessuno ha dichiarato.

**La cardinalità non è uno a uno.** Un backend che invia blocchi audio senza
aprire lo stream richiede due buste JCP per il primo blocco. In quel caso si
sovrascrive `from_backend`:

```python
def from_backend(self, raw):
    if raw.get("type") == "audio":
        buste = []
        if raw["data"]["id"] not in self._aperti:
            self._aperti.add(raw["data"]["id"])
            buste.append(self.envelope(MessageType.STREAM_OPEN, {...}))
        buste.append(self.envelope(MessageType.STREAM_DATA, {...}))
        return buste
    return super().from_backend(raw)

def reset(self):
    self._aperti.clear()   # obbligatorio se c'è stato tecnico
```

Dimenticare `reset()` produce difetti che si manifestano solo alla **seconda**
connessione, fra i più fastidiosi da trovare.

### Verificare la copertura

```python
adapter.coverage({MessageType.SESSION_HELLO, MessageType.CHAT_SEND})
# → {'session.hello'}  ← non traducibile: l'handshake non funzionerà mai
```

---

## 2. Scrivere un plugin

> **Stato**: il contratto è definito e validabile. Il caricatore a runtime
> nell'interfaccia arriverà con la fase dedicata ai plugin. Oggi si può
> scrivere, validare e collaudare un plugin; non ancora attivarlo dentro
> l'applicazione.

### Struttura

```
acme.meteo/
├── plugin.json
└── plugin.py
```

```json
{
  "id": "acme.meteo",
  "name": "Meteo",
  "version": "1.0.0",
  "api_version": 1,
  "entry_point": "plugin:Plugin",
  "description": "Mostra le previsioni nel pannello laterale.",
  "requires_capabilities": ["ext.acme.meteo"]
}
```

```python
class Plugin:
    def activate(self, context):
        self._log = context.logger
        self._token = context.subscribe("aggiornato", self._on_update)
        self._log.info("Meteo attivo")

    def deactivate(self):
        self._token.unsubscribe()

    def _on_update(self, event):
        ...
```

### Perché il manifesto è separato dal codice

Si può ispezionare un plugin — nome, versione, capability richieste — **senza
importarlo**, cioè senza eseguirlo:

```python
from jarvis_sdk import discover, validate_manifest

for manifest in discover(Path("~/.local/share/Jarvis/plugins").expanduser()):
    problemi = validate_manifest(manifest)
    print(manifest.id, "ok" if not problemi else problemi)
```

`validate_manifest` restituisce **tutti** i problemi insieme invece di sollevare
al primo: correggerne uno per volta scoprendo il successivo a ogni tentativo è
tempo perso.

### Cosa un plugin può fare

`PluginContext` espone bus namespaced, registro dei pannelli, logger e
configurazione isolata. **Non** espone la finestra principale, i servizi o lo
state manager. Se un plugin potesse raggiungere gli interni, in due anni il core
non sarebbe più modificabile senza rompere i plugin.

Un plugin può inviare messaggi JCP **solo** nello spazio `ext.`: potrebbe
altrimenti dichiarare stati o esiti che il backend non ha prodotto, e
l'interfaccia smetterebbe di essere una proiezione fedele.

### Modello di sicurezza — detto chiaramente

I plugin girano **in-process, con piena fiducia**. Python non offre sandboxing
reale. La versione di API li protegge dalle rotture del core; non protegge il
core da un plugin malevolo. Installare un plugin equivale a eseguire codice
arbitrario sulla propria macchina.

---

## 3. Scrivere un backend

Il riferimento minimo è `examples/minimal-backend/backend.py`: centoventi righe
che superano la verifica di conformità. Tutto ciò che contiene è obbligatorio,
tutto ciò che manca è facoltativo.

Il riferimento completo — missioni, azioni, conferme, stream, guasti — è
l'ambiente di simulazione (`jarvis-sim`), che implementa JCP 1.0 per intero.

Verifica:

```bash
python tools/jcp_validate.py --url ws://127.0.0.1:8765
```

Esce con `0` se conforme, `1` altrimenti: si mette in integrazione continua
senza interpretare l'output.

---

## 4. Collaudare un'estensione

```python
from jarvis_sdk.testing import CollectingTransport, assert_sequence, make_hello, make_welcome

async def test_handshake():
    transport = CollectingTransport([make_welcome(capabilities=["chat.stream"])])
    await transport.connect()
    await transport.send(make_hello().to_wire())

    assert transport.sent[0].type == "session.hello"
```

`assert_sequence` verifica che i tipi attesi compaiano **in ordine, anche non
adiacenti**: fra due messaggi che interessano ne possono comparire altri
legittimi, e un test che si rompe per questo verrebbe presto disattivato.

---

## 5. Registrazione e replay

Vedi [`03-simulazione-e-replay.md`](03-simulazione-e-replay.md).
