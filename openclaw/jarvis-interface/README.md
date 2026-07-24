# Jarvis ↔ Gateway OpenClaw

Sostituisce la risposta simulata di `script.js` con una connessione reale al
gateway OpenClaw su `ws://127.0.0.1:18789`.

I due file vanno copiati in `.openclaw/workspace/jarvis-interface/`, accanto a
`script.js`.

## Come funziona davvero il canale Telegram (e perché qui si usa `chat.send`)

Il canale Telegram **non è un client WebSocket**: gira dentro il processo del
gateway. Riceve gli update dall'API di Telegram, ricava una chiave di sessione
`telegram:<chatId>` e consegna il messaggio allo stesso *agent runner*; la
risposta esce dal percorso di delivery del canale. Un browser non può quindi
"fare il canale Telegram".

Il percorso equivalente lato client — quello che usano Control UI e WebChat per
raggiungere **lo stesso agent runner e lo stesso modello Gemini** — è la RPC
`chat.send` con le risposte in streaming sugli eventi `chat`. È quello
implementato qui.

## Il collegamento in tre passaggi

1. **Handshake firmato.** Il gateway apre con un evento `connect.challenge`
   contenente un nonce. Il client genera un'identità Ed25519 (WebCrypto,
   conservata in `localStorage`), firma il payload `v3` che lega deviceId,
   client, ruolo, scope, timestamp e nonce, e risponde con `connect`. Il
   gateway risponde `hello-ok`.
2. **Invio.** `chat.send` con `sessionKey`, `message` e `idempotencyKey`. È
   **non bloccante**: risponde subito `{ runId, status: "started" }`.
3. **Streaming.** Gli eventi `chat` con lo stesso `runId` portano il testo:
   `state:"delta"` con `deltaText` (se `replace:true`, sostituisce invece di
   accodare), poi `state:"final"` con lo snapshot completo. Gli stati
   `aborted` ed `error` chiudono il run.

Gli eventi `chat` possono arrivare **prima** della risposta di `chat.send`: il
client li mette in buffer per `runId` e li riproduce appena l'ack arriva,
quindi la prima parola non si perde mai.

## Modifica a `script.js`

Al posto del blocco che simulava la risposta (intorno a riga 215):

```js
// PRIMA — da rimuovere
console.log("Risposta dal server locale (simulata per ora):", { status: "received" });
```

metti:

```js
import { JarvisAgent } from "./jarvis-agent.js";

const jarvis = new JarvisAgent({
  url: "ws://127.0.0.1:18789",
  sessionKey: "jarvis-interface",
  // token: "...",    // solo se gateway.auth.mode è "token"
  // password: "...", // solo se gateway.auth.mode è "password"
});

jarvis.onStatus(({ state }) => console.log("[gateway]", state));
await jarvis.connect();

// dove prima c'era la simulazione, dopo la trascrizione del vocale:
const risposta = await jarvis.ask(testoTrascritto, {
  onDelta: (testoParziale) => mostraRisposta(testoParziale), // aggiorna la UI mentre scrive
  onFinal: (testoCompleto) => mostraRisposta(testoCompleto),
});
```

`ask()` risolve con la risposta reale dell'agente e nel frattempo la legge ad
alta voce. Se il tag `<script>` non è già un modulo, serve
`<script type="module" src="script.js"></script>`.

## Voce ElevenLabs Jarvis

La sintesi passa dalla RPC `tts.speak` del gateway: la chiave ElevenLabs resta
sul server e non finisce nel browser. Configura la voce in `openclaw.json`:

```json5
{
  messages: {
    tts: {
      provider: "elevenlabs",
      providers: {
        elevenlabs: {
          apiKey: "${ELEVENLABS_API_KEY}",
          speakerVoiceId: "Nw7Rghp67eaUlozsAvCk",
          model: "eleven_multilingual_v2",
        },
      },
    },
  },
}
```

La chiave della voce è `speakerVoiceId`: `voiceId` è legacy e viene migrata da
`openclaw doctor --fix`. Serve anche `ELEVENLABS_API_KEY` nell'ambiente del
gateway.

**Non serve** impostare `messages.tts.auto`. La RPC `tts.speak` sintetizza
direttamente con il provider configurato senza passare dall'auto-TTS, quindi
questa configurazione **non cambia il comportamento di Telegram**: le risposte
là restano testo. Con `auto: "always"` diventerebbero invece note vocali.

Le frasi vengono sintetizzate appena sono complete e riprodotte in ordine, così
Jarvis comincia a parlare mentre il modello sta ancora scrivendo. Per disattivare
la voce: `new JarvisAgent({ speak: false })`.

Nota: molti browser bloccano l'autoplay finché non c'è stata un'interazione
dell'utente. Dato che qui si parte da un comando vocale l'interazione c'è già;
in caso contrario l'audio viene saltato con un warning e il testo resta a schermo.

## Sessione

Di default l'interfaccia usa la sessione `jarvis-interface`, separata dalla
cronologia di Telegram ma sullo stesso agente. Per condividere la conversazione
con una chat Telegram, passa `sessionKey: "telegram:<chatId>"`.

## Ordine di avvio

1. Copia i due `.js` accanto a `script.js`. **Da soli non fanno nulla**: la
   simulazione va rimossa a mano da `script.js` (vedi sopra).
2. Assicurati che `script.js` sia caricato come modulo:
   `<script type="module" src="script.js"></script>`.
3. Configura la voce in `openclaw.json`, esporta `ELEVENLABS_API_KEY` e
   riavvia il gateway.
4. Controlla `gateway.auth.mode`: se è `token` o `password`, passa la
   credenziale al costruttore di `JarvisAgent`.
5. Apri `http://localhost:3000` e guarda la console. Se compare
   `PAIRING_REQUIRED`, approva il dispositivo e ricarica:

   ```bash
   openclaw devices list
   openclaw devices approve <requestId>
   ```

Se lo stato in console arriva a `connected`, il collegamento è a posto.

## Se la connessione viene rifiutata

- **`PAIRING_REQUIRED`** — il browser è un dispositivo nuovo. Approvalo una
  volta con `openclaw devices` o dalla Control UI, poi ricarica la pagina.
  Cancellare `localStorage` genera una nuova identità e richiede una nuova
  approvazione.
- **`AUTH_TOKEN_MISMATCH` / `AUTH_REQUIRED`** — controlla `gateway.auth.mode` e
  passa `token` o `password` al costruttore.
- **Ed25519 non supportato** — servono Chrome 137+, Safari 17+ o Firefox 129+.
- La pagina deve essere servita da `http://localhost:3000` (contesto sicuro),
  non aperta come file locale, altrimenti WebCrypto non è disponibile.

## Verifica

La logica di firma è stata validata contro il verificatore reale di OpenClaw
(`verifyDeviceSignature`, `deriveDeviceIdFromPublicKey` dal pacchetto
`openclaw@2026.7.1-2`): il `deviceId` derivato dal browser combacia con quello
calcolato dal gateway e la firma WebCrypto viene accettata, mentre un payload
alterato viene rifiutato. Il flusso completo (handshake, delta, final, evento
pre-ack, `tts.speak`) è stato eseguito contro un gateway di prova che parla il
protocollo v4.
