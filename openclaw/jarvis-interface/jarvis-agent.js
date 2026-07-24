/**
 * Collega l'interfaccia Jarvis all'agente OpenClaw.
 *
 * Sostituisce la risposta simulata: il testo trascritto viene inviato al
 * gateway con `chat.send`, la risposta arriva in streaming sugli eventi `chat`
 * e viene letta ad alta voce con la voce ElevenLabs configurata nel gateway.
 */

import { OpenClawGatewayClient } from "./openclaw-gateway.js";

/* ------------------------------------------------------------------ *
 * Coda di sintesi vocale
 *
 * Le frasi vengono sintetizzate appena sono complete e riprodotte in ordine,
 * così Jarvis inizia a parlare mentre il modello sta ancora scrivendo.
 * ------------------------------------------------------------------ */

class SpeechQueue {
  constructor(client) {
    this.client = client;
    this.queue = [];
    this.playing = false;
    this.current = null;
    this.enabled = true;
  }

  enqueue(text) {
    const clean = text.trim();
    if (!clean || !this.enabled) return;
    this.queue.push(clean);
    if (!this.playing) void this.#drain();
  }

  async #drain() {
    this.playing = true;
    while (this.queue.length > 0 && this.enabled) {
      const text = this.queue.shift();
      try {
        const { audioBase64, mimeType } = await this.client.speak(text);
        await this.#play(`data:${mimeType};base64,${audioBase64}`);
      } catch (err) {
        console.error("[jarvis] sintesi vocale fallita:", err);
      }
    }
    this.playing = false;
  }

  #play(src) {
    return new Promise((resolve) => {
      const audio = new Audio(src);
      this.current = audio;
      const done = () => {
        this.current = null;
        resolve();
      };
      audio.addEventListener("ended", done, { once: true });
      audio.addEventListener("error", done, { once: true });
      // L'autoplay può essere bloccato finché l'utente non interagisce: non è
      // un errore fatale, la risposta resta comunque a schermo.
      audio.play().catch((err) => {
        console.warn("[jarvis] riproduzione bloccata dal browser:", err);
        done();
      });
    });
  }

  stop() {
    this.queue.length = 0;
    if (this.current) {
      this.current.pause();
      this.current = null;
    }
  }
}

/**
 * Accumula i delta e stacca le frasi complete, così la sintesi parte prima
 * della fine della risposta senza spezzare le parole a metà.
 */
class SentenceSplitter {
  constructor(onSentence) {
    this.buffer = "";
    this.onSentence = onSentence;
  }

  push(deltaText) {
    this.buffer += deltaText;
    const parts = this.buffer.split(/(?<=[.!?…])\s+/);
    // L'ultimo pezzo può essere una frase incompleta: resta nel buffer.
    this.buffer = parts.pop() ?? "";
    for (const sentence of parts) this.onSentence(sentence);
  }

  flush() {
    const rest = this.buffer.trim();
    this.buffer = "";
    if (rest) this.onSentence(rest);
  }

  reset() {
    this.buffer = "";
  }
}

/* ------------------------------------------------------------------ *
 * API pubblica
 * ------------------------------------------------------------------ */

export class JarvisAgent {
  /**
   * @param {object} options
   * @param {string} [options.url]        default ws://127.0.0.1:18789
   * @param {string} [options.token]      gateway.auth.token, se configurato
   * @param {string} [options.password]   gateway.auth.password, se configurato
   * @param {string} [options.sessionKey] sessione dell'agente
   * @param {boolean} [options.speak]     lettura ad alta voce (default true)
   */
  constructor(options = {}) {
    this.client = new OpenClawGatewayClient({
      url: options.url,
      token: options.token,
      password: options.password,
      sessionKey: options.sessionKey ?? "jarvis-interface",
      agentId: options.agentId,
    });
    this.speech = new SpeechQueue(this.client);
    this.speech.enabled = options.speak !== false;
  }

  onStatus(handler) {
    return this.client.on("status", handler);
  }

  async connect() {
    return this.client.connect();
  }

  /**
   * Invia il testo trascritto all'agente Gemini e restituisce la risposta reale.
   *
   * @param {string} text
   * @param {object} handlers
   * @param {(fullText: string) => void} [handlers.onDelta]  chiamato a ogni aggiornamento
   * @param {(fullText: string) => void} [handlers.onFinal]
   */
  async ask(text, { onDelta, onFinal } = {}) {
    this.speech.stop();

    const splitter = new SentenceSplitter((sentence) => this.speech.enqueue(sentence));

    const finalText = await this.client.sendMessage(text, {
      onDelta: (_chunk, fullText) => {
        onDelta?.(fullText);
        splitter.push(_chunk);
      },
      onFinal: (completed) => {
        splitter.flush();
        onFinal?.(completed);
      },
    });

    return finalText;
  }

  abort() {
    this.speech.stop();
    return this.client.abort();
  }

  close() {
    this.speech.stop();
    this.client.close();
  }
}
