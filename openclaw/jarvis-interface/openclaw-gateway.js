/**
 * Client WebSocket per il Gateway OpenClaw (protocollo v4).
 *
 * È lo stesso piano di controllo che usano Control UI e WebChat: il messaggio
 * entra nell'agente con la RPC `chat.send` e la risposta torna in streaming
 * sugli eventi `chat` (delta -> final). L'agente e il modello sono quelli
 * configurati nel gateway, quindi identici a quelli che risponde su Telegram.
 *
 * Riferimenti di protocollo:
 *  - frame richiesta: {type:"req", id, method, params}
 *  - frame risposta:  {type:"res", id, ok, payload|error}
 *  - frame evento:    {type:"event", event, payload, seq?}
 */

const PROTOCOL_VERSION = 4;

// client.id e client.mode devono appartenere al set chiuso accettato dal
// gateway, altrimenti l'handshake viene rifiutato.
const CLIENT_ID = "webchat-ui";
const CLIENT_MODE = "webchat";
const CLIENT_VERSION = "1.0.0";
const PLATFORM = "browser";
const DEVICE_FAMILY = "";

const SCOPES = ["operator.read", "operator.write"];

const IDENTITY_STORAGE_KEY = "openclaw.deviceIdentity.v1";
const DEVICE_TOKEN_STORAGE_KEY = "openclaw.deviceToken.v1";

const REQUEST_TIMEOUT_MS = 30_000;
const HANDSHAKE_TIMEOUT_MS = 15_000;
const INITIAL_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
const DEFAULT_TICK_INTERVAL_MS = 30_000;

/* ------------------------------------------------------------------ *
 * Encoding
 * ------------------------------------------------------------------ */

const textEncoder = new TextEncoder();

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value) {
  const binary = atob(value);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

function base64UrlEncode(bytes) {
  return bytesToBase64(bytes)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

async function sha256Hex(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/* ------------------------------------------------------------------ *
 * Identità di dispositivo (Ed25519)
 *
 * Il gateway richiede che ogni connessione firmi il nonce di challenge.
 * deviceId = sha256(chiave pubblica raw a 32 byte) in esadecimale, esattamente
 * come fa OpenClaw lato Node.
 * ------------------------------------------------------------------ */

const ED25519_SPKI_PREFIX_LENGTH = 12;

async function exportPublicKeyRaw(publicKey) {
  try {
    return new Uint8Array(await crypto.subtle.exportKey("raw", publicKey));
  } catch {
    const spki = new Uint8Array(await crypto.subtle.exportKey("spki", publicKey));
    return spki.slice(ED25519_SPKI_PREFIX_LENGTH);
  }
}

async function loadOrCreateDeviceIdentity() {
  if (!globalThis.crypto?.subtle) {
    throw new Error(
      "WebCrypto non disponibile. Servi l'interfaccia su http://localhost:3000 o su https, non aprendo il file direttamente.",
    );
  }

  const stored = localStorage.getItem(IDENTITY_STORAGE_KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      const privateKey = await crypto.subtle.importKey(
        "pkcs8",
        base64ToBytes(parsed.privateKeyPkcs8),
        { name: "Ed25519" },
        true,
        ["sign"],
      );
      const publicKeyRaw = base64ToBytes(parsed.publicKeyRaw);
      return { privateKey, publicKeyRaw, deviceId: await sha256Hex(publicKeyRaw) };
    } catch {
      // Identità illeggibile: la rigeneriamo sotto.
      localStorage.removeItem(IDENTITY_STORAGE_KEY);
      localStorage.removeItem(DEVICE_TOKEN_STORAGE_KEY);
    }
  }

  let pair;
  try {
    pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  } catch {
    throw new Error(
      "Questo browser non espone Ed25519 in WebCrypto. Servono Chrome 137+, Safari 17+ o Firefox 129+.",
    );
  }

  const publicKeyRaw = await exportPublicKeyRaw(pair.publicKey);
  const privateKeyPkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));

  localStorage.setItem(
    IDENTITY_STORAGE_KEY,
    JSON.stringify({
      privateKeyPkcs8: bytesToBase64(privateKeyPkcs8),
      publicKeyRaw: bytesToBase64(publicKeyRaw),
    }),
  );

  return { privateKey: pair.privateKey, publicKeyRaw, deviceId: await sha256Hex(publicKeyRaw) };
}

function normalizeDeviceMetadata(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

/** Payload di firma v3: deve combaciare byte per byte con quello del gateway. */
function buildDeviceAuthPayloadV3({
  deviceId,
  clientId,
  clientMode,
  role,
  scopes,
  signedAtMs,
  token,
  nonce,
  platform,
  deviceFamily,
}) {
  return [
    "v3",
    deviceId,
    clientId,
    clientMode,
    role,
    scopes.join(","),
    String(signedAtMs),
    token ?? "",
    nonce,
    normalizeDeviceMetadata(platform),
    normalizeDeviceMetadata(deviceFamily),
  ].join("|");
}

/* ------------------------------------------------------------------ *
 * Estrazione testo dagli snapshot del messaggio assistente
 * ------------------------------------------------------------------ */

export function extractAssistantText(message) {
  if (!message) return "";
  if (typeof message === "string") return message;
  if (Array.isArray(message)) return message.map(extractAssistantText).filter(Boolean).join("");

  if (typeof message === "object") {
    if (typeof message.text === "string") return message.text;
    if (Array.isArray(message.content)) {
      return message.content
        .map((block) => {
          if (typeof block === "string") return block;
          if (block && typeof block === "object" && typeof block.text === "string") {
            return block.type && block.type !== "text" ? "" : block.text;
          }
          return "";
        })
        .filter(Boolean)
        .join("");
    }
    if (typeof message.content === "string") return message.content;
  }
  return "";
}

/* ------------------------------------------------------------------ *
 * Client
 * ------------------------------------------------------------------ */

export class OpenClawGatewayClient {
  /**
   * @param {object} options
   * @param {string} [options.url]        URL del gateway (default ws://127.0.0.1:18789)
   * @param {string} [options.token]      gateway.auth.token, se auth.mode === "token"
   * @param {string} [options.password]   gateway.auth.password, se auth.mode === "password"
   * @param {string} [options.sessionKey] sessione dell'agente da usare
   */
  constructor(options = {}) {
    this.url = options.url ?? "ws://127.0.0.1:18789";
    this.token = options.token ?? null;
    this.password = options.password ?? null;
    this.sessionKey = options.sessionKey ?? "jarvis-interface";
    this.agentId = options.agentId ?? undefined;

    this.ws = null;
    this.identity = null;
    this.helloOk = null;
    this.connected = false;
    this.stopped = false;

    this.nextRequestId = 1;
    this.pendingRequests = new Map();
    this.listeners = new Map();

    /** Run attivi: runId -> {onDelta, onFinal, onError, text, resolve, reject} */
    this.activeRuns = new Map();
    /** Eventi chat arrivati prima che il runId fosse noto. */
    this.orphanChatEvents = new Map();

    this.backoffMs = INITIAL_BACKOFF_MS;
    this.tickIntervalMs = DEFAULT_TICK_INTERVAL_MS;
    this.tickWatchdog = null;
    this.reconnectTimer = null;
    this.connectPromise = null;
  }

  /* -------------------- eventi -------------------- */

  on(event, handler) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(handler);
    return () => this.listeners.get(event)?.delete(handler);
  }

  emit(event, payload) {
    for (const handler of this.listeners.get(event) ?? []) {
      try {
        handler(payload);
      } catch (err) {
        console.error(`[openclaw] handler "${event}" ha lanciato:`, err);
      }
    }
  }

  /* -------------------- connessione -------------------- */

  async connect() {
    if (this.connected) return this.helloOk;
    if (this.connectPromise) return this.connectPromise;

    this.stopped = false;
    this.connectPromise = this.#openSocket().finally(() => {
      this.connectPromise = null;
    });
    return this.connectPromise;
  }

  async #openSocket() {
    this.identity ??= await loadOrCreateDeviceIdentity();

    return new Promise((resolve, reject) => {
      let settled = false;
      const ws = new WebSocket(this.url);
      this.ws = ws;

      const fail = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(handshakeTimer);
        reject(error);
      };

      const handshakeTimer = setTimeout(() => {
        fail(new Error("timeout durante l'handshake con il gateway"));
        ws.close(1000, "handshake timeout");
      }, HANDSHAKE_TIMEOUT_MS);

      ws.addEventListener("open", () => {
        this.emit("status", { state: "connecting" });
      });

      ws.addEventListener("message", (event) => {
        let frame;
        try {
          frame = JSON.parse(typeof event.data === "string" ? event.data : "");
        } catch {
          return;
        }

        // Il gateway apre con la challenge: la firmiamo e rispondiamo con connect.
        if (frame.type === "event" && frame.event === "connect.challenge") {
          this.#sendConnect(frame.payload?.nonce).catch(fail);
          return;
        }

        this.#handleFrame(frame, {
          onHelloOk: (payload) => {
            if (settled) return;
            settled = true;
            clearTimeout(handshakeTimer);
            this.helloOk = payload;
            this.connected = true;
            this.backoffMs = INITIAL_BACKOFF_MS;
            this.tickIntervalMs = payload?.policy?.tickIntervalMs ?? DEFAULT_TICK_INTERVAL_MS;

            const deviceToken = payload?.auth?.deviceToken;
            if (deviceToken) localStorage.setItem(DEVICE_TOKEN_STORAGE_KEY, deviceToken);

            this.#armTickWatchdog();
            this.emit("status", { state: "connected", helloOk: payload });
            resolve(payload);
          },
          onConnectError: fail,
        });
      });

      ws.addEventListener("error", () => {
        fail(new Error("errore di rete verso il gateway"));
      });

      ws.addEventListener("close", (event) => {
        this.connected = false;
        this.#clearTickWatchdog();
        this.#rejectAllPending(new Error(`connessione chiusa (${event.code})`));
        this.emit("status", { state: "disconnected", code: event.code, reason: event.reason });
        fail(new Error(`connessione chiusa prima dell'handshake (${event.code})`));
        if (!this.stopped) this.#scheduleReconnect();
      });
    });
  }

  async #sendConnect(nonce) {
    if (!nonce) throw new Error("challenge senza nonce");

    const role = "operator";
    const signedAtMs = Date.now();
    const deviceToken = localStorage.getItem(DEVICE_TOKEN_STORAGE_KEY);

    // Il token che entra nella firma è lo stesso che finisce in auth.token.
    const signatureToken = this.token ?? deviceToken ?? null;

    const payload = buildDeviceAuthPayloadV3({
      deviceId: this.identity.deviceId,
      clientId: CLIENT_ID,
      clientMode: CLIENT_MODE,
      role,
      scopes: SCOPES,
      signedAtMs,
      token: signatureToken,
      nonce,
      platform: PLATFORM,
      deviceFamily: DEVICE_FAMILY,
    });

    const signature = base64UrlEncode(
      new Uint8Array(
        await crypto.subtle.sign({ name: "Ed25519" }, this.identity.privateKey, textEncoder.encode(payload)),
      ),
    );

    const auth = {};
    if (this.token) auth.token = this.token;
    else if (deviceToken) auth.token = deviceToken;
    if (this.password) auth.password = this.password;

    this.#sendFrame({
      type: "req",
      id: `connect-${this.nextRequestId++}`,
      method: "connect",
      params: {
        minProtocol: PROTOCOL_VERSION,
        maxProtocol: PROTOCOL_VERSION,
        client: {
          id: CLIENT_ID,
          version: CLIENT_VERSION,
          platform: PLATFORM,
          mode: CLIENT_MODE,
        },
        role,
        scopes: SCOPES,
        caps: [],
        ...(Object.keys(auth).length ? { auth } : {}),
        locale: navigator.language || "it-IT",
        userAgent: `jarvis-interface/${CLIENT_VERSION}`,
        device: {
          id: this.identity.deviceId,
          publicKey: base64UrlEncode(this.identity.publicKeyRaw),
          signature,
          signedAt: signedAtMs,
          nonce,
        },
      },
    });
  }

  #handleFrame(frame, { onHelloOk, onConnectError } = {}) {
    if (frame.type === "res") {
      // Risposta all'handshake.
      if (typeof frame.id === "string" && frame.id.startsWith("connect-")) {
        if (frame.ok && frame.payload?.type === "hello-ok") onHelloOk?.(frame.payload);
        else onConnectError?.(this.#connectError(frame.error));
        return;
      }

      const pending = this.pendingRequests.get(frame.id);
      if (!pending) return;
      this.pendingRequests.delete(frame.id);
      clearTimeout(pending.timer);
      if (frame.ok) pending.resolve(frame.payload);
      else pending.reject(Object.assign(new Error(frame.error?.message ?? "RPC fallita"), { code: frame.error?.code, details: frame.error?.details }));
      return;
    }

    if (frame.type === "event") {
      this.#noteActivity();
      if (frame.event === "chat") this.#handleChatEvent(frame.payload);
      this.emit(frame.event, frame.payload);
    }
  }

  #connectError(error) {
    const code = error?.code ?? "CONNECT_FAILED";
    const base = error?.message ?? "connessione al gateway rifiutata";

    if (code === "PAIRING_REQUIRED") {
      return Object.assign(
        new Error(
          `${base}\nQuesto browser è un dispositivo nuovo: approvalo una volta con "openclaw devices" (o dalla Control UI) e ricarica la pagina.`,
        ),
        { code },
      );
    }
    if (code === "AUTH_TOKEN_MISMATCH" || code === "AUTH_REQUIRED") {
      return Object.assign(
        new Error(`${base}\nControlla gateway.auth.mode e passa token o password corretti al client.`),
        { code },
      );
    }
    return Object.assign(new Error(base), { code });
  }

  /* -------------------- keepalive -------------------- */

  #noteActivity() {
    if (!this.tickWatchdog) return;
    this.#armTickWatchdog();
  }

  #armTickWatchdog() {
    this.#clearTickWatchdog();
    this.tickWatchdog = setTimeout(() => {
      // Silenzio oltre il doppio del tick: la socket è morta senza close().
      this.ws?.close(4000, "tick timeout");
    }, this.tickIntervalMs * 2);
  }

  #clearTickWatchdog() {
    if (this.tickWatchdog) clearTimeout(this.tickWatchdog);
    this.tickWatchdog = null;
  }

  #scheduleReconnect() {
    if (this.reconnectTimer || this.stopped) return;
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
    this.emit("status", { state: "reconnecting", delayMs: delay });
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect().catch((err) => this.emit("error", err));
    }, delay);
  }

  #rejectAllPending(error) {
    for (const [, pending] of this.pendingRequests) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pendingRequests.clear();

    for (const [, run] of this.activeRuns) {
      run.onError?.(error);
      run.reject?.(error);
    }
    this.activeRuns.clear();
    this.orphanChatEvents.clear();
  }

  /* -------------------- RPC -------------------- */

  #sendFrame(frame) {
    if (this.ws?.readyState !== WebSocket.OPEN) throw new Error("socket non aperta");
    this.ws.send(JSON.stringify(frame));
  }

  request(method, params = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
    return new Promise((resolve, reject) => {
      const id = `req-${this.nextRequestId++}`;
      const timer = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(new Error(`timeout RPC ${method}`));
      }, timeoutMs);

      this.pendingRequests.set(id, { resolve, reject, timer });
      try {
        this.#sendFrame({ type: "req", id, method, params });
      } catch (err) {
        clearTimeout(timer);
        this.pendingRequests.delete(id);
        reject(err);
      }
    });
  }

  /* -------------------- chat -------------------- */

  #handleChatEvent(payload) {
    const runId = payload?.runId;
    if (!runId) return;

    const run = this.activeRuns.get(runId);
    if (!run) {
      // L'evento può precedere la risposta di chat.send: lo mettiamo da parte.
      const buffered = this.orphanChatEvents.get(runId) ?? [];
      buffered.push(payload);
      this.orphanChatEvents.set(runId, buffered);
      return;
    }

    switch (payload.state) {
      case "delta": {
        // replace=true significa che deltaText sostituisce il testo accumulato.
        run.text = payload.replace ? payload.deltaText : run.text + payload.deltaText;
        run.onDelta?.(payload.deltaText, run.text, payload);
        break;
      }
      case "final": {
        const finalText = extractAssistantText(payload.message) || run.text;
        this.activeRuns.delete(runId);
        run.onFinal?.(finalText, payload);
        run.resolve?.(finalText);
        break;
      }
      case "aborted": {
        const partial = extractAssistantText(payload.message) || run.text;
        this.activeRuns.delete(runId);
        run.onFinal?.(partial, payload);
        run.resolve?.(partial);
        break;
      }
      case "error": {
        this.activeRuns.delete(runId);
        const error = Object.assign(new Error(payload.errorMessage ?? "l'agente ha restituito un errore"), {
          kind: payload.errorKind,
        });
        run.onError?.(error);
        run.reject?.(error);
        break;
      }
      default:
        break;
    }
  }

  /**
   * Manda il messaggio all'agente e risolve con la risposta completa.
   * I delta arrivano su onDelta man mano che il modello produce testo.
   */
  async sendMessage(text, { onDelta, onFinal, onError, sessionKey } = {}) {
    if (!this.connected) await this.connect();

    const idempotencyKey =
      globalThis.crypto?.randomUUID?.() ?? `jarvis-${Date.now()}-${Math.random().toString(16).slice(2)}`;

    const ack = await this.request("chat.send", {
      sessionKey: sessionKey ?? this.sessionKey,
      ...(this.agentId ? { agentId: this.agentId } : {}),
      message: text,
      idempotencyKey,
    });

    const runId = ack?.runId;
    if (!runId) throw new Error("chat.send non ha restituito un runId");

    return new Promise((resolve, reject) => {
      const run = { text: "", onDelta, onFinal, onError, resolve, reject };
      this.activeRuns.set(runId, run);

      // Riproduciamo gli eventi arrivati prima dell'ack.
      const buffered = this.orphanChatEvents.get(runId);
      if (buffered) {
        this.orphanChatEvents.delete(runId);
        for (const payload of buffered) this.#handleChatEvent(payload);
      }
    });
  }

  abort(sessionKey) {
    return this.request("chat.abort", { sessionKey: sessionKey ?? this.sessionKey });
  }

  /**
   * Sintesi vocale lato gateway: usa il provider TTS configurato in OpenClaw
   * (ElevenLabs con la voce Jarvis) e restituisce l'audio già renderizzato.
   * La chiave ElevenLabs resta sul gateway, non nel browser.
   */
  async speak(text) {
    const result = await this.request("tts.speak", { text });
    return {
      audioBase64: result.audioBase64,
      mimeType: result.mimeType ?? "audio/mpeg",
      provider: result.provider,
    };
  }

  close() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.#clearTickWatchdog();
    this.ws?.close(1000, "client closed");
  }
}
