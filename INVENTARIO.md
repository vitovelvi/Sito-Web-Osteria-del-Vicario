# INVENTARIO FORENSE

**Repository:** `vitovelvi/Sito-Web-Osteria-del-Vicario`
**Commit analizzato:** `09cc6ea` — ramo `claude/jarvis-inventario-forense-d4p91l`
**Data:** 3 settembre 2026
**Metodo:** sola lettura + una build reale (`npm run build`) per verificare l'output effettivo.

---

## ⚠️ AVVERTENZA PRELIMINARE — IL SISTEMA RICHIESTO NON ESISTE IN QUESTO REPOSITORY

L'audit richiesto descrive **Jarvis**, un assistente vocale Python con pipeline microfono → VAD →
wake word → Whisper → Gemini → Piper → altoparlante, worker cognitivo a eventi, GUI, sistema di
skill e memoria persistente.

**Niente di tutto questo esiste qui.** Non è una deduzione dai nomi: è verificato.

| Verifica | Comando | Esito |
|---|---|---|
| File Python nel worktree | `find . -name '*.py'` | **0** |
| File Python mai esistiti nella storia | `git log --all --diff-filter=A --name-only` su 24 commit | **0** |
| `requirements.txt` / `pyproject.toml` | ricerca worktree + storia | **assenti** |
| Menzioni testuali di jarvis/gemini/whisper/piper/VAD/TTS | `grep -rn` su tutti i file di testo | **0** |

> Nota: un `grep` non filtrato produce falsi positivi su `.jpg`/`.webp` — sono byte casuali dentro
> immagini binarie, non codice. Verificato uno per uno.

**Cosa c'è davvero:** un sito web statico **Astro 4** per l'Osteria del Vicario (Certaldo Alto, FI),
più una cartella `agency-tools/` che contiene una *skill* per Claude Code e gli scarti di un pilota
abbandonato. Zero backend, zero Python, zero AI a runtime.

Le due ipotesi plausibili sono che il task sia stato lanciato sul repository sbagliato, oppure che
Jarvis viva in un repository separato non collegato a questa sessione.

**Cosa ho fatto invece di indovinare:** ho applicato lo stesso metodo forense — e la stessa regola
di raggiungibilità — al codice che esiste realmente. Le sezioni che riguardano capacità inesistenti
(pipeline vocale, eventi, memoria, prompt LLM) sono compilate con la prova della loro assenza, non
lasciate vuote né riempite di supposizioni.

### Caricamento dinamico — dichiarazione preliminare

La regola impone di verificare i meccanismi dinamici prima di dichiarare qualcosa irraggiungibile.

**Questo progetto non ne usa nessuno.** Nessun `import()` dinamico, nessun registry, nessuna
factory, nessun plugin discovery, nessun percorso letto da YAML/JSON. Tutti i 49 import sono
statici e letterali (0 occorrenze di `import(`). L'unico meccanismo "implicito" è la **routing file-based di Astro**
(`src/pages/**` → URL) e la generazione da `getStaticPaths()`, entrambi risolti a build time e
verificati sull'output reale.

**Conseguenza: l'affidabilità del grafo di raggiungibilità in questo documento è alta.** Non è il
caso, comune in Python, in cui l'assenza di import diretti non significa niente.

---

## 1 — STRUTTURA

```
Sito-Web-Osteria-del-Vicario/
├── astro.config.mjs, package.json, vercel.json, .gitignore, README.md
├── src/
│   ├── pages/          8 rotte  (index, camere, tavolo, menu, chi-siamo,
│   │   └── piatti/     scopri-certaldo, piatti/[slug])
│   ├── components/    16 componenti .astro
│   ├── layouts/        Layout.astro  (unico layout)
│   ├── data/           piatti.js     (unica fonte dati)
│   ├── scripts/        scroll.js     (unico JS runtime)
│   └── styles/         global.css
├── public/immagini/   67 immagini in 6 cartelle (camere, dettagli, hero,
│                       luogo, piatti, video[vuota])
└── agency-tools/cinematic-site-builder/
    ├── SKILL.md, scripts/ (4 .mjs), templates/
    └── output/osteria-del-vicario/  ← pilota abbandonato (60 frame + 3 lib minificate)
```

| Metrica | Valore |
|---|---|
| **File Python** | **0** (la metrica richiesta non si applica) |
| File `.astro` | 24 |
| Righe di codice `src/` | **3.128** (pages 1.158 · components 1.411 · layouts 99 · scripts 183 · data 114 · styles 163) |
| Righe `agency-tools/` (escluse lib minificate) | 1.303 |
| Peso `src/` | 160 KB |
| Peso `public/` | **9,3 MB** (99% immagini) |
| Peso `agency-tools/` | 1,8 MB |
| Peso `dist/` (build) | 9,7 MB |
| **"Modelli"** | **0 byte** — nessun modello ML nel progetto |

L'equivalente locale del "peso dei modelli" è il **peso degli asset statici: 9,3 MB di immagini**,
cioè 58 volte il codice sorgente. È lì che sta il peso di questo progetto, ed è trattato nella §12E.

---

## 2 — ENTRY POINT E FLUSSO REALE

Non esiste un processo che "si avvia". Il sistema ha **due entry point distinti**, entrambi a build
time; a runtime non c'è nessun server applicativo.

### Catena di build (verificata eseguendo `npm run build`)

```
vercel.json (buildCommand)
  └→ npm run build → astro build
       └→ astro.config.mjs  [site: osteriadelvicario.it, integrations: sitemap()]
            └→ scansione src/pages/**            ← routing file-based
                 ├→ 7 rotte statiche
                 └→ piatti/[slug].astro
                      └→ getStaticPaths() ← import { piatti } from src/data/piatti.js
                           └→ 8 rotte generate (una per piatto)
            └→ ogni pagina → Layout.astro → global.css + JSON-LD + <slot/>
            └→ Vite bundla i <script> hoisted → _astro/scroll.<hash>.js
            └→ @astrojs/sitemap → sitemap-index.xml
       └→ dist/  →  Vercel serve i file statici
```

**Esito reale della build:** ✅ verde, 551 ms, **14 pagine HTML** generate, nessun errore né warning.

### Catena di una richiesta utente completa

L'equivalente locale della "richiesta vocale" è il caricamento di una pagina:

```
browser → CDN Vercel → dist/<rotta>/index.html   [HTML già completo, nessun render server]
   ├→ CSS inline nel <head>                                   → pagina visibile
   ├→ Google Fonts (fonts.googleapis.com + fonts.gstatic.com) → tipografia
   ├→ 35 immagini da /immagini/** (raw, non ottimizzate)      → contenuto visivo
   └→ <script type="module"> _astro/hoisted.<hash>.js
        └→ import _astro/scroll.<hash>.js  [136 KB — GSAP + ScrollTrigger + Lenis]
             └→ init*() → animazioni scroll
```

### 🔴 DOVE LA CATENA SI INTERROMPE

Come richiesto, questa è l'informazione più importante della sezione. Tre rotture confermate:

**A. `initScroll()` esegue un ciclo su un array sempre vuoto — codice morto in produzione.**

`src/scripts/scroll.js:22-59` è costruito attorno a `gsap.utils.toArray(".scene")`, e per ogni
`.scene` cerca `.scene-img` e `.scene-caption`. **Nessuno di questi tre selettori esiste in
nessun file di `src/`** (verificato con grep su `.astro` e `.css`). L'array è vuoto, il `forEach`
non entra mai, 38 righe di coreografia pinnata non vengono mai eseguite.

Origine ricostruita dalla storia git: il markup `.scene` esisteva in `index.astro` fino al commit
`1f657ae`, ed è stato rimosso da `0251630` ("Ristruttura il sito attorno all'esperienza di Certaldo
Alto"). **Il markup è stato cancellato, il codice che lo animava no.**

La parte di `initScroll()` che *funziona* è solo l'inizializzazione di Lenis (righe 8-18) e il
`ScrollTrigger.refresh()` finale. La funzione fa quindi metà di ciò che il suo corpo dichiara.

**B. Lo smooth scroll Lenis è attivo solo sulla home, ma tutte le pagine ne pagano il peso.**

`initScroll()` — l'unica funzione che istanzia Lenis — è chiamata **solo da `index.astro:61`**.
Le altre 6 rotte hanno scroll nativo. Ma il bundle è unico: `_astro/scroll.<hash>.js` (136 KB
raw / 51 KB gzip) contiene Lenis + GSAP + ScrollTrigger e viene scaricato da **tutte** le pagine
che importano una qualsiasi `init*`. `chi-siamo` usa solo `initPageHeader` + `initReveal` e scarica
comunque l'intera libreria di smooth scrolling che non userà mai. Verificato sull'output:
`dist/_astro/hoisted.CkUmKMxF.js` importa lo stesso chunk da 136 KB.

**C. Le 8 pagine piatto non caricano nessun JavaScript.**

`piatti/[slug].astro` è l'unica rotta senza blocco `<script>`. Verificato sull'output: in
`dist/piatti/melanzana-hummus/index.html` l'unico tag `<script>` è il JSON-LD del Layout. Non è
necessariamente un bug — la pagina non usa `.reveal` né `.tilt-card` — ma è un'**incoerenza di
esperienza**: 8 delle 14 pagine del sito si comportano diversamente da tutte le altre.

---

## 3 — MODULI

Grafo completo. **Tutti i 49 import sono statici**, quindi la colonna di raggiungibilità è
determinata con certezza, non stimata.

| File | Cosa fa | Importato da | **Raggiungibile dall'entry point?** |
|---|---|---|---|
| `astro.config.mjs` | Config build, `site`, sitemap | runtime Astro | **SÌ** — letto da `astro build` |
| `src/layouts/Layout.astro` | `<html>`, meta/OG, JSON-LD, Google Fonts | tutte le 7 rotte | **SÌ** |
| `src/styles/global.css` | Token colore/font, `.btn`, `.glass`, `.tilt-card` | `Layout.astro:2` | **SÌ** |
| `src/data/piatti.js` | 8 piatti + risotto + dolci | `menu`, `[slug]`, `PiattiPreview` | **SÌ** |
| `src/scripts/scroll.js` | 6 funzioni di animazione | 6 rotte via `<script>` | **SÌ — parzialmente** (vedi §2A) |
| `src/pages/index.astro` | Home | routing file-based | **SÌ** — `/` |
| `src/pages/camere.astro` | B&B + form | routing | **SÌ** — `/camere` |
| `src/pages/tavolo.astro` | Ristorante + form | routing | **SÌ** — `/tavolo` |
| `src/pages/menu.astro` | Menu completo | routing | **SÌ** — `/menu` |
| `src/pages/chi-siamo.astro` | Storia | routing | **SÌ** — `/chi-siamo` |
| `src/pages/scopri-certaldo.astro` | Territorio | routing | **SÌ** — `/scopri-certaldo` |
| `src/pages/piatti/[slug].astro` | Scheda piatto | `getStaticPaths()` | **SÌ** — 8 URL generati |
| `src/components/NavFunnel.astro` | Nav logo + 2 CTA | 7 rotte | **SÌ** |
| `src/components/Footer.astro` | Footer | 7 rotte | **SÌ** |
| `src/components/PageHeader.astro` | Header con parallax | 5 rotte | **SÌ** |
| `src/components/BookingForm.astro` | Form prenotazione | `camere`, `tavolo` | **SÌ** |
| `src/components/Gallery.astro` | Griglia immagini | `camere`, `tavolo`, `GalleriaMix` | **SÌ** |
| `src/components/GalleriaMix.astro` | Galleria home (10 foto) | `index` | **SÌ** |
| `src/components/FloatingEmblem.astro` | Stemma 3D | `index` | **SÌ** |
| `src/components/MagiaCertaldo.astro` | Sezione borgo | `index` | **SÌ** |
| `src/components/DormiNellaStoria.astro` | Sezione camere | `index` | **SÌ** |
| `src/components/AssaporaToscana.astro` | Sezione osteria | `index` | **SÌ** |
| `src/components/Esperienze.astro` | 6 card esperienze | `index` | **SÌ** |
| `src/components/PiattiPreview.astro` | 4 piatti in anteprima | `index` | **SÌ** |
| `src/components/Terrazza.astro` | Sezione terrazza | `index` | **SÌ** |
| `src/components/Recensioni.astro` | 2 link piattaforme | `index` | **SÌ** |
| `src/components/FAQ.astro` | 6 FAQ + JSON-LD | `index` | **SÌ** |
| `src/components/Contatti.astro` | Contatti + mappa | `index` | **SÌ** |
| `src/env.d.ts` | Tipi Astro (file vuoto, 0 righe) | TypeScript | **NON DETERMINATO** — nessun typecheck nella pipeline |
| `agency-tools/.../SKILL.md` | Skill Claude Code | — | **NO** — fuori da `src/`, mai letta dalla build |
| `agency-tools/.../scripts/*.mjs` (4) | Generazione AI immagini/video/frame | — | **NO** — eseguibili solo a mano |
| `agency-tools/.../templates/*` | Template skill | — | **NO** |
| `agency-tools/.../output/**` | Pilota abbandonato | — | **NO** |

**Osservazione:** ogni componente in `src/components/` è usato almeno una volta. **Non c'è un solo
componente orfano.** Il codice morto di questo progetto non è nei file, è *dentro* le funzioni
(§2A) e negli asset (§12E).

---

## 4 — PIPELINE VOCALE

**La pipeline vocale non esiste.** Nessuno dei suoi anelli è presente in alcuna forma.

| Anello | Esiste | Chiamato | Riceve dati | Restituisce | Collegato |
|---|---|---|---|---|---|
| microfono | ❌ | — | — | — | — |
| cattura audio | ❌ | — | — | — | — |
| VAD | ❌ | — | — | — | — |
| wake word | ❌ | — | — | — | — |
| STT | ❌ | — | — | — | — |
| intent | ❌ | — | — | — | — |
| agente | ❌ | — | — | — | — |
| LLM | ❌ | — | — | — | — |
| TTS | ❌ | — | — | — | — |
| altoparlante | ❌ | — | — | — | — |

**Prova:** nessuna API `getUserMedia`, `AudioContext`, `MediaRecorder`, `SpeechRecognition` o
`speechSynthesis` compare in `src/`. Nessun file audio nel progetto. `public/immagini/video/`
contiene solo un `.gitkeep` (0 byte).

**L'unica pipeline reale del progetto** è quella dello scroll, che riporto nello stesso formato
perché è l'unica catena a stadi che esiste davvero:

```
scroll utente → Lenis (solo home) → ScrollTrigger.update → GSAP → transform CSS
```

| Anello | Esiste | Chiamato | Riceve dati | Restituisce | Collegato al successivo |
|---|---|---|---|---|---|
| Lenis smooth scroll | ✅ | ✅ solo `index` | ✅ eventi wheel | ✅ progress | ✅ → ScrollTrigger |
| `initHero` (`.hero`) | ✅ | ✅ `index` | ✅ `.hero-img` presente | ✅ timeline | ✅ |
| **ciclo `.scene`** | ✅ | ✅ | ❌ **array vuoto** | ❌ | 🔴 **SCOLLEGATO** — vedi §2A |
| `initEmblem` (`#emblem-3d`) | ✅ | ✅ `index` | ✅ | ✅ | ✅ |
| `initPageHeader` (`.page-header`) | ✅ | ✅ 5 rotte | ✅ | ✅ | ✅ |
| `initReveal` (`.reveal`) | ✅ | ✅ 5 rotte | ✅ 14 nel markup → 19 resi | ✅ | ✅ |
| `initTilt` (`.tilt-card`) | ✅ | ✅ 4 rotte | ✅ | ✅ | ✅ |

**Un solo anello scollegato: il ciclo `.scene`.** Gli altri sei sono correttamente cablati ai loro
selettori DOM (verificato incrociando ogni selettore con il markup che lo contiene).

---

## 5 — GUI

Questa sezione è la più rilevante fra quelle trasferibili: il sospetto originale — *un'interfaccia
che sembra funzionare senza essere collegata a un backend* — **si verifica anche qui**.

### Il fatto centrale: non esiste alcun backend

Nessun endpoint API, nessun `fetch()` verso un server proprio, nessun database, nessuna Astro
action, nessuna serverless function. `vercel.json` dichiara `framework: astro` e
`outputDirectory: dist`: **hosting puramente statico**. Qualunque elemento dell'interfaccia che
sembri "inviare" o "leggere" qualcosa va guardato con sospetto.

### Widget istanziati e handler reali

| Elemento | Handler | Cosa fa davvero | Verdetto |
|---|---|---|---|
| `BookingForm` — submit (`camere`, `tavolo`) | ✅ `BookingForm.astro:52` | `preventDefault()` → costruisce corpo email → **`window.location.href = mailto:`** | ⚠️ **FUNZIONA MA NON È UN BACKEND** |
| Pulsante "Chiama" | ✅ nativo `tel:` | apre il dialer | ✅ reale |
| Pulsante "Scrivi email" | ✅ nativo `mailto:` | apre il client | ✅ reale |
| WhatsApp (`Contatti`) | ✅ nativo | `wa.me/393472248182` | ✅ reale |
| Accordion FAQ | ✅ nativo `<details>` | apre/chiude senza JS | ✅ reale |
| Card `.tilt-card` | ✅ `initTilt` | `pointermove` → rotazione 3D | ✅ reale |
| Stemma `#emblem-3d` | ✅ `initEmblem` | float + parallasse puntatore | ✅ reale |
| Link piatto → `/piatti/<slug>` | ✅ nativo | pagina reale generata | ✅ reale |
| Mappa Google (`Contatti`) | `<iframe>` | mappa reale di terze parti | ✅ reale |
| Link Booking.com / Instagram / Facebook | ✅ nativi | destinazioni esterne reali | ✅ reale |

**Nessun pulsante finto, nessun handler vuoto, nessun segnale scollegato.** Da questo punto di
vista la GUI è più onesta di quanto il sospetto iniziale suggerisse.

### 🔴 Il problema vero del form di prenotazione

Il form **non è finto, ma non è nemmeno una prenotazione**. Alla submit apre il client di posta
dell'utente con un corpo precompilato. Conseguenze reali, non teoriche:

1. **Nessuna persistenza.** Nessuna richiesta è registrata da nessuna parte. Se l'utente non preme
   "invia" nel proprio client, la prenotazione **non esiste** e il ristorante non saprà mai che
   qualcuno ci ha provato.
2. **Fallimento silenzioso.** Su un dispositivo senza client di posta configurato (comune su
   desktop e su molti Android), `window.location.href = "mailto:..."` **non fa assolutamente
   nulla**. L'utente ha compilato il modulo, premuto "Invia richiesta tavolo", e la pagina resta
   ferma senza errore né spiegazione.
3. **Nessuno stato di conferma.** Non c'è messaggio di successo, spinner, o reset del form: nessun
   feedback distingue "inviato" da "non è successo niente".
4. **Nessuna validazione oltre `required`**: nessun controllo che la data sia futura, che il
   telefono sia plausibile, nessuna protezione anti-spam.

### Elementi SOLO VISUALI (elenco esplicito, come richiesto)

| Elemento | Perché è solo visuale |
|---|---|
| `Recensioni.astro` — *"Le voci di chi è già stato qui"* | **Non contiene nessuna recensione.** Solo 2 link a piattaforme esterne. Il titolo promette testimonianze che la sezione non mostra. Va detto a credito del codice: una nota dichiara apertamente il rinvio alle piattaforme — è una scelta trasparente, non un inganno. |
| `Recensioni` — *"400+ recensioni"*, *"300+ recensioni"* | Stringhe **statiche scritte a mano**, non conteggi reali. Invecchiano da sole e nessuno se ne accorgerà. |
| `Recensioni` — card **"TripAdvisor"** | 🔴 **Etichetta sbagliata:** `href` punta a `mytreats.app/food_identity/curation/osteria_del_vicario/`, **non a TripAdvisor**. L'utente clicca su un marchio e ne raggiunge un altro. |
| `Footer` — **`P.IVA 00000000000`** | 🔴 **Segnaposto mai sostituito.** Undici zeri pubblicati in produzione. Per un'attività italiana la partita IVA nel footer è un obbligo di legge: qui è visibilmente falsa. |
| `menu.astro` — nota allergeni *"in attesa di conferma definitiva dalla cucina"* | Ammette che i dati allergeni **non sono validati**, pubblicati comunque su una cucina che dichiara di gestire celiachia e allergie alla frutta a guscio. |
| `Esperienze` — 6 card | Testi statici, nessun link a fonti o dettagli: puramente decorative. |
| Ramo `og:type = "business.business"` in `Layout.astro:74` | **Irraggiungibile:** nessuna pagina passa mai `type`. Verificato sull'output: tutte e 14 le pagine emettono `og:type="website"`. |

---

## 6 — TOOL E SKILL

Non esiste un sistema di skill a runtime. Esiste **una** skill, ma è per Claude Code, non per il
sito: `agency-tools/cinematic-site-builder/SKILL.md`.

| Nome | Esiste | Registrato | Raggiungibile | Autorizzato | Eseguito almeno una volta |
|---|---|---|---|---|---|
| `cinematic-site-builder` (SKILL.md) | ✅ | ⚠️ solo come file in `agency-tools/`, **non in `.claude/skills/`** | ❌ dal sito · ⚠️ da Claude Code solo se spostata | n/d | ⚠️ **parzialmente** — vedi sotto |
| `scripts/generate-still.mjs` (Imagen) | ✅ | ❌ | ❌ solo CLI manuale | ❌ richiede `GOOGLE_CLOUD_API_KEY`, assente | ❌ **mai** — nessun `.png` generato |
| `scripts/animate-still.mjs` (image-to-video) | ✅ | ❌ | ❌ solo CLI manuale | ❌ richiede `WAVESPEED_API_KEY`, assente | ❌ **mai** — nessun `.mp4` nel repo |
| `scripts/extract-frames.mjs` (ffmpeg) | ✅ | ❌ | ❌ solo CLI manuale | ⚠️ richiede `ffmpeg` di sistema | ❌ **mai** su video reale |
| `scripts/generate-test-frames.mjs` (Playwright) | ✅ | ❌ | ❌ solo CLI manuale | ✅ `playwright` è in `devDependencies` | ✅ **sì** — ha prodotto i 60 frame in `output/` |
| `templates/scroll-scrubber.js` | ✅ | ❌ | ❌ **mai integrato in `src/`** | n/d | ⚠️ solo in `scroll-test.html`, fuori dal sito |

**La distinzione che la consegna chiede di fare, applicata qui:**

- **Codice morto** (esiste, non registrato): i 4 script `.mjs` e i template. Nessun percorso li
  raggiunge dalla build del sito.
- **Promessa non mantenuta** (registrata, non raggiungibile): la pipeline della SKILL.md. Il
  documento descrive 4 fasi che culminano in uno scroll-scrubbing di frame video in stile Apple.
  **Fase 2 (generazione AI) e Fase 4 (deploy autopilota) non sono mai state eseguite**, e la tecnica
  di Fase 3 **non è mai arrivata nel sito reale**: `src/` non contiene alcun frame-scrubbing.
  Quello che è finito in produzione è una timeline GSAP su una singola foto (`initHero`).

Va riconosciuto un merito alla SKILL.md: i suoi "principi non negoziabili" vietano di spacciare
placeholder per risultati reali, e gli script effettivamente escono con errore se la chiave manca,
invece di simulare. Il codice rispetta ciò che dichiara.

---

## 7 — EVENTI

**Non esiste un sistema a eventi.** Nessun worker cognitivo, nessun event bus, nessuna coda,
nessun publish/subscribe. Il "worker cognitivo con 8 tipi di evento" citato dalla consegna
appartiene al sistema assente.

Gli unici eventi sono listener DOM del browser. Elencati per completezza:

| Evento | Dichiarato | Pubblicato da | Ascoltato da | Usato davvero |
|---|---|---|---|---|
| `submit` | `BookingForm.astro:52` | browser (form) | handler `mailto:` | ✅ sì — ma vedi §5 |
| `pointermove` (window) | `scroll.js:113` | browser | `initEmblem` | ✅ sì — solo home |
| `pointermove` (card) | `scroll.js:170` | browser | `initTilt` | ✅ sì |
| `pointerleave` | `scroll.js:178` | browser | `initTilt` | ✅ sì |
| `scroll` (Lenis) | `scroll.js:13` | Lenis | `ScrollTrigger.update` | ✅ sì — solo home |
| `gsap.ticker` | `scroll.js:15` | GSAP | `lenis.raf` | ✅ sì — solo home |
| ScrollTrigger su `.scene` | `scroll.js:30` | — | — | 🔴 **FANTASMA** — nessun `.scene` esiste |

**Un evento fantasma su sette**, ed è lo stesso difetto già isolato in §2A.

---

## 8 — ISTRUZIONI E PROMPT

**Nessun prompt LLM esiste in questo progetto.** Nessun modulo invoca Gemini o qualsiasi altro
modello: non esiste "prompt di sistema che Gemini riceve a ogni turno", né a runtime né altrove.
Non c'è nulla da ricostruire e nessun conteggio token da produrre.

**Il totale dei token del prompt statico è quindi 0, ben sotto la soglia di 4.000.**

File di istruzioni e contenuto testuale realmente presenti:

| File | Righe | A cosa serve | **Letto a runtime?** | Da quale modulo |
|---|---|---|---|---|
| `agency-tools/.../SKILL.md` | 100 | Istruzioni per Claude Code (4 fasi) | ❌ **NO** dal sito. ⚠️ Da Claude Code solo se in `.claude/skills/` — **non lo è** | nessuno |
| `agency-tools/.../templates/site-structures/ristorante.md` | 26 | Template struttura di settore | ❌ **NO** — nessun modulo lo apre | nessuno |
| `README.md` | 1 | Solo il titolo | ❌ NO | nessuno |
| `src/data/piatti.js` | 114 | 8 piatti: nome, foto, ingredienti, allergeni, storia, vino | ✅ **SÌ** — a build time | `menu.astro`, `[slug].astro`, `PiattiPreview.astro` |
| `public/robots.txt` | 4 | Direttive crawler | ✅ SÌ — dai crawler | — |
| Testi editoriali nei `.astro` | ~350 | FAQ, esperienze, storia, itinerari | ✅ SÌ — a build time | i componenti stessi |

### Contenuti scritti a mano nel codice invece che in file esterni

È l'equivalente locale di "prompt scritti a mano nel codice". **Ampiamente diffuso:**

| Contenuto | Dove | Perché è un problema |
|---|---|---|
| 6 FAQ (domande + risposte) | `FAQ.astro:2-9` | Contenuto editoriale dentro un componente di presentazione |
| 6 esperienze | `Esperienze.astro:2-9` | idem |
| 5 sezioni + 2 itinerari | `scopri-certaldo.astro:6-50` | idem |
| 3 camere (vista + comfort) | `DormiNellaStoria.astro:2-6` | idem |
| Testo storico | `chi-siamo.astro` | idem |
| **Prezzi €40 / €50 / €65** | `menu.astro:27,32,37` | 🔴 **Dati commerciali hardcoded nel markup** |
| Telefono, email, indirizzo | ripetuti in `Layout`, `Contatti`, `Footer`, `camere`, `tavolo` | 🔴 **Duplicati in 5 file** |

Solo i piatti sono stati estratti in un file dati. Tutto il resto è inline: cambiare un prezzo o
un numero di telefono richiede di trovare e modificare più file, e ogni copia dimenticata diventa
un'incoerenza pubblicata.

### 🔴 Istruzioni duplicate o contraddittorie

| Contraddizione | Dettaglio |
|---|---|
| **`.btn-cotto` e `.btn-outline` definiti due volte** | `global.css:84-105` e poi **di nuovo** a `119-140`, con valori diversi (tinta unita → gradiente). La seconda definizione vince silenziosamente; la prima è codice morto che sembra governare l'aspetto dei pulsanti e non governa nulla. |
| **Fascia di prezzo incoerente** | JSON-LD dichiara `priceRange: "€€€"` (`Layout.astro:31`) mentre il menu vende 2 portate a €40. Google riceve un'informazione più cara del vero. |
| **Orari dichiarati ma non strutturati** | Il footer indica "Cena 19:30–22:30, chiuso il martedì"; il JSON-LD **non ha `openingHours`** (0 occorrenze). Il dato più utile ai motori di ricerca è l'unico non esposto in forma leggibile. |
| **Regola che descrive una capacità inesistente** | SKILL.md Fase 3 istruisce a inserire `scroll-scrubber.js` con i frame estratti. Nel sito reale non c'è. La skill descrive un sito che non è stato costruito così. |
| **`scroll-scrubber.js` duplicato byte per byte** | `templates/` e `output/osteria-del-vicario/` — file identici (`diff` conferma). |

---

## 9 — MEMORIA

**Non esiste memoria persistente di alcun tipo, né lato server né lato client.**

Verificato per esclusione esplicita, non per assenza di nomi: nessun database, nessun
`localStorage`, `sessionStorage`, `IndexedDB` o cookie applicativo compare in `src/`. Nessuna
scrittura su disco a runtime — non c'è runtime su cui scrivere.

- **Sopravvive al riavvio?** Nessuno stato da far sopravvivere.
- **Cosa viene salvato?** Nulla. Neanche le richieste di prenotazione (§5).
- **Chi scrive / chi rilegge?** Nessuno / nessuno.
- **Cresce senza limite?** Non applicabile.

L'unico stato "persistente" è il contenuto statico committato in git, che cambia solo con un
deploy. Conseguenza operativa concreta: **il sito non ha memoria di essere stato usato**. Zero
analytics, zero log applicativi, zero tracciamento conversioni. Non è possibile sapere quante
persone abbiano provato a prenotare.

---

## 10 — CONFIGURAZIONE E SERVIZI ESTERNI

### Configurazione

| Fonte | Esiste | **Chi la legge davvero** |
|---|---|---|
| `package.json` | ✅ | npm — script `dev/build/preview` |
| `astro.config.mjs` | ✅ | `astro build` — `site` usato per URL canonici, OG e sitemap ✅ |
| `vercel.json` | ✅ | Vercel in fase di deploy |
| `.gitignore` | ✅ | git — ignora `node_modules`, `dist`, `.astro`, `.env` |
| `src/env.d.ts` | ✅ ma **vuoto (0 righe)** | ⚠️ **nessuno** — nessun typecheck nella pipeline |
| **`.env`** | ❌ **non esiste** | — |
| `config/`, `settings/` | ❌ | — |

### 🔴 Configurazioni che sembrano governare qualcosa e non governano nulla

Esattamente la categoria che la consegna definisce più insidiosa:

| Variabile | Dichiarata in | Realtà |
|---|---|---|
| `GOOGLE_CLOUD_API_KEY` | `generate-still.mjs:6`, SKILL.md Fase 2 | **Nessun `.env` esiste.** Lo script esce con errore alla prima riga. Mai usata. |
| `WAVESPEED_API_KEY` | `animate-still.mjs:5`, SKILL.md Fase 2 | idem. Mai usata. |
| `VERCEL_TOKEN` | SKILL.md Fase 4 | Mai letto da nessuno script: la Fase 4 non ha implementazione. |
| `image` (prop di `Layout`) | `Layout.astro:14` | ⚠️ **Nessuna pagina la passa a `Layout`.** Le pagine passano `image` a `PageHeader`, che è un altro componente. Risultato verificato sull'output: **tutte e 14 le pagine condividono lo stesso `og:image`** (`hero/vicolo-insegna.jpg`), anche quelle che hanno una foto propria perfettamente adatta. La prop *sembra* rendere configurabile l'anteprima social, e non lo fa. |
| `type` (prop di `Layout`) | `Layout.astro:15` | ⚠️ Mai passata: il ramo `business.business` è irraggiungibile. |

**Nota positiva:** nessuna chiave API, credenziale o segreto è committato nel repository. Verificato.

### Servizi esterni

| Servizio | Dove | Bloccante? | Note |
|---|---|---|---|
| **Vercel** | `vercel.json` | sì — è l'hosting | — |
| **Google Fonts** (`googleapis` + `gstatic`) | `Layout.astro:89-94` | no, c'è fallback Georgia/Helvetica | 🔴 richiesta a Google **da ogni pagina**, con IP dell'utente |
| **Google Maps embed** | `Contatti.astro` | no | 🔴 iframe di terze parti sulla home |
| **Booking.com** | `camere.astro`, `Recensioni` | no | link in uscita |
| **mytreats.app** | `Recensioni`, `Footer` | no | 🔴 etichettato "TripAdvisor" (§5) |
| **Instagram / Facebook** | `Footer` | no | link in uscita |
| **WhatsApp** (`wa.me`) | `Contatti` | no | link in uscita |
| **Client email dell'utente** (`mailto:`) | `BookingForm` | 🔴 **sì — è l'unico canale di prenotazione** | §5 |

🔴 **Google Fonts e Google Maps caricano da server Google a ogni visita, con l'IP dell'utente.
Il progetto non ha né cookie banner né informativa privacy** (0 occorrenze di
privacy/cookie/informativa/GDPR in tutto il repository). Per un'attività italiana rivolta a
visitatori UE, questo è un problema di conformità reale, non teorico.

---

## 11 — CAPACITÀ REALI

### Le capacità richieste dalla consegna

Tutte assenti. Nessuna è "parziale": non esiste alcun frammento di codice che tenti di realizzarle.

| Capacità | Stato | Modulo | Prova |
|---|---|---|---|
| Ragionamento (Gemini) | **ASSENTE** | — | 0 occorrenze di API LLM; nessuna dipendenza AI in `package.json` |
| Voce in uscita (Piper) | **ASSENTE** | — | nessun TTS, nessun `speechSynthesis` |
| Trascrizione (Whisper) | **ASSENTE** | — | nessun STT, nessun file audio |
| VAD | **ASSENTE** | — | nessun `AudioContext` |
| Wake word | **ASSENTE** | — | nessuna cattura microfono |
| Memoria persistente | **ASSENTE** | — | §9 — nessuno storage di alcun tipo |
| Lettura file | **ASSENTE** a runtime | — | sito statico; `extract-frames.mjs` legge file ma solo da CLI manuale |
| Scrittura file | **ASSENTE** a runtime | — | idem (`mkdirSync` in script mai eseguiti nella build) |
| Esecuzione shell | **ASSENTE** a runtime | — | `execFileSync("ffmpeg")` esiste in `extract-frames.mjs:19`, irraggiungibile dalla build |
| Accesso web | **ASSENTE** a runtime | — | nessun `fetch` in `src/`; presente solo negli script AI mai eseguiti |
| Generazione immagini | **ASSENTE** | — | `generate-still.mjs` esiste ma senza key esce subito; nessun output prodotto |
| Generazione video | **ASSENTE** | — | `animate-still.mjs` idem; `public/immagini/video/` vuota |
| Email | **PARZIALE** ⚠️ | `BookingForm.astro` | Nessun invio: apre il client dell'utente via `mailto:`. Nessuna email parte dal sistema |
| Calendario | **ASSENTE** | — | nessuna gestione date/disponibilità |
| Meta Ads | **ASSENTE** | — | nessun pixel, nessuna integrazione |
| WordPress / ordini | **ASSENTE** | — | nessun CMS, nessun e-commerce |
| Scheduler | **ASSENTE** | — | nessun cron, nessun job |
| Sistema di skill | **ASSENTE** a runtime | — | §6 — una skill per Claude Code, mai caricata dal sito |

### Le capacità che il progetto ha davvero

Per ogni **FUNZIONANTE** riporto il percorso di esecuzione, non un file dal nome promettente.

| Capacità | Stato | Modulo | Prova (percorso di esecuzione) |
|---|---|---|---|
| Sito statico multipagina | **FUNZIONANTE** | Astro + `src/pages` | `npm run build` → **14 HTML generati**, build verde in 551 ms |
| Rotte dinamiche per piatto | **FUNZIONANTE** | `[slug].astro` + `piatti.js` | `getStaticPaths()` → 8 URL, tutti presenti in `dist/piatti/*/index.html` |
| SEO tecnico (canonical, OG, Twitter) | **PARZIALE** | `Layout.astro` | Meta emessi su tutte le pagine, ma `og:image` identico ovunque (§10) |
| Dati strutturati Schema.org | **PARZIALE** | `Layout` + `FAQ` | JSON-LD Restaurant+Lodging su **tutte e 14** le pagine (la stessa attività dichiarata 14 volte); manca `openingHours`; `priceRange` incoerente |
| Sitemap XML | **FUNZIONANTE** | `@astrojs/sitemap` | `sitemap-index.xml` + `sitemap-0.xml` con 14 `<loc>`, coerenti con `robots.txt` |
| Smooth scroll | **PARZIALE** | `scroll.js` + Lenis | Attivo **solo sulla home**; le altre 6 rotte pagano 136 KB e usano scroll nativo |
| Animazioni scroll (parallax/reveal/tilt) | **FUNZIONANTE** | `scroll.js` | 6 funzioni su 7 anelli correttamente cablate ai selettori (§4) |
| Coreografia `.scene` | **ASSENTE** | `scroll.js:22-59` | 🔴 Il codice esiste ed è eseguito, ma su un array vuoto |
| Raccolta prenotazioni | **PARZIALE** ⚠️ | `BookingForm.astro` | Handler reale, ma **nessuna persistenza e fallimento silenzioso** senza client di posta (§5) |
| Responsive | **FUNZIONANTE** | media query nei componenti | breakpoint presenti (es. `BookingForm:149`) |
| Ottimizzazione immagini | **ASSENTE** | — | 🔴 0 usi di `astro:assets`/`<Image>`: **67 file serviti raw** |
| Analytics / misurazione | **ASSENTE** | — | nessuno script di tracciamento: nessuna conversione è misurabile |
| Conformità privacy/cookie | **ASSENTE** | — | 🔴 Google Fonts + Maps senza informativa né banner (§10) |

---

## 12 — CANDIDATI ALLA RIMOZIONE

*Solo elenco. Nulla è stato cancellato o modificato.*

### A. Non raggiungibile — nessun percorso dall'entry point

| Voce | Percorso | Peso | Perché |
|---|---|---|---|
| Ciclo `.scene` in `initScroll` | `src/scripts/scroll.js:22-59` | ~38 righe | Itera `.scene`, selettore inesistente in tutto `src/`. Markup rimosso nel commit `0251630`, codice mai ripulito. |
| Ramo `og:type="business.business"` | `Layout.astro:74` | 1 riga | Nessuna pagina passa `type`: verificato, 14/14 pagine emettono `website`. |
| Prima definizione di `.btn-cotto`/`.btn-outline` | `global.css:84-105` | 22 righe | Sovrascritta dalle righe 119-140. Non ha effetto. |
| `src/env.d.ts` | `src/env.d.ts` | 0 byte | File vuoto; nessun typecheck nella pipeline. ⚠️ Vedi NON TOCCARE. |

### B. Istruzioni non lette — file che nessun modulo apre

| Voce | Percorso | Peso | Perché |
|---|---|---|---|
| `SKILL.md` | `agency-tools/cinematic-site-builder/` | 8 KB | Non in `.claude/skills/`, quindi non caricata automaticamente; e comunque invisibile alla build del sito. ⚠️ Vedi NON TOCCARE. |
| `ristorante.md` | `.../templates/site-structures/` | 26 righe | Template di settore mai letto da alcun modulo. |
| `README.md` | radice | 30 byte | Solo il titolo: non documenta né setup né deploy né struttura. Da **riempire**, non da rimuovere. |

### C. Duplicati — stessa funzione implementata due volte

| Voce | Percorso | Peso | Perché |
|---|---|---|---|
| `scroll-scrubber.js` ×2 | `templates/` e `output/osteria-del-vicario/` | 2× 87 righe | Byte-identici (`diff -q` conferma). |
| GSAP / ScrollTrigger / Lenis minificati | `agency-tools/.../output/osteria-del-vicario/` | **136 KB** | Copie manuali di librerie **già presenti in `devDependencies`** e già bundlate da Vite. Terza copia in `node_modules`. |
| `.btn-cotto` / `.btn-outline` | `global.css` | 22 righe | Vedi §A. |
| Contatti (telefono/email/indirizzo) | `Layout`, `Contatti`, `Footer`, `camere`, `tavolo` | 5 copie | Nessuna fonte unica: un cambio di numero richiede 5 modifiche. |
| JSON-LD Restaurant + LodgingBusiness | emesso su 14/14 pagine | — | La stessa attività dichiarata 14 volte, anche sulle schede piatto. |

### D. Sperimenti abbandonati

| Voce | Percorso | Peso | Perché |
|---|---|---|---|
| **60 frame placeholder** | `.../output/osteria-del-vicario/frames/frame-00*.jpg` | **~1,5 MB** | Gradienti generati da `generate-test-frames.mjs` per il pilota di Fase 3. Non sono contenuto del cliente e non compaiono nel sito. |
| `scroll-test.html` | `.../output/osteria-del-vicario/` | 55 righe | Banco di prova dello scrubbing, mai integrato. |
| `concept-vegetale.html` | `.../output/osteria-del-vicario/` | 642 righe | Concept single-page alternativo (commit `4640d2d`), **superato** dal sito Astro reale. È il file sorgente più lungo del repository e non serve a nulla. |
| `brand-card.html` | `.../output/osteria-del-vicario/` | 82 righe | Deliverable di Fase 1, già approvato: valore storico, non operativo. |
| Script AI mai eseguibili | `generate-still.mjs`, `animate-still.mjs` | 79 righe | Richiedono chiavi API che non esistono in nessun `.env`. |
| `public/immagini/video/` | — | 0 byte | Cartella vuota con solo `.gitkeep`, destinata a un `hero-scene.mp4` mai prodotto. |

### E. Peso inutile — asset non usati

| Voce | Peso | Perché |
|---|---|---|
| **25 immagini orfane** | **2,9 MB** | Presenti in `public/immagini/`, **mai referenziate da alcun file di `src/`**. Vengono comunque copiate in `dist/` e pubblicate. Elenco: `bagno-01/02.webp`, `camera-09.webp`, `logo-badge.jpg`, `menu.jpeg`, `servizio.webp`, `storico.webp`, `portone.jpg`, `entrata-esterna.webp`, `entrata-interna.jpg`, `entrate.jpeg`, `osteria-esterno.jpg`, `colazione-2.webp`, `piatto-01.webp`, `piatto-08/09/11/14/15/16/18/19/21`, `piatto-13b.jpg`, `spremuta.jpg`. |
| Immagini non ottimizzate | — | Le 42 immagini realmente usate pesano **6,3 MB** e sono servite **raw**: nessun `astro:assets`, nessun resize, nessun formato moderno automatico. `osteria-esterno.jpg` da solo pesa 755 KB (ed è pure orfano). |
| **Payload della home** | **5,1 MB su 35 immagini** | Anche con `loading="lazy"` su quasi tutte, è un peso fuori scala per una home page. |
| Bundle JS su pagine che non lo usano | 136 KB / pagina | `chi-siamo` e `scopri-certaldo` scaricano GSAP+ScrollTrigger+**Lenis** usando solo parallax e reveal. |

---

## ⛔ NON TOCCARE

Cose che sembrano morte e non lo sono. Prima di cancellare qualcosa da questo documento, leggere qui.

| Voce | Perché **non** va rimossa |
|---|---|
| **`src/pages/piatti/[slug].astro`** | Le parentesi quadre sembrano un segnaposto. **Non lo sono:** è la sintassi di routing dinamico di Astro e genera **8 delle 14 pagine** del sito. Rinominarlo distrugge un terzo delle rotte. |
| **`src/data/piatti.js`** | Non è importato da nessun `<script>` client: sembra inerte. È invece la fonte dati di **3 moduli** a build time, e i suoi `slug` **determinano gli URL pubblici**. Cambiare uno `slug` rompe link interni e indicizzazione. |
| **`src/env.d.ts` (0 righe)** | File vuoto, apparentemente inutile. È il riferimento ai tipi generati da Astro: serve agli editor e a un eventuale `astro check`. Costa 0 byte. |
| **`public/robots.txt`** e le `.gitkeep` | `robots.txt` è servito ai crawler (fuori dal grafo di import). Le `.gitkeep` mantengono in git cartelle altrimenti vuote. |
| **`agency-tools/.../SKILL.md`** | Invisibile alla build, ma è **documentazione di processo**: è il file che spiega perché esistono i frame, il concept e gli script. Rimuoverlo lascerebbe quegli artefatti senza spiegazione. Se la skill deve funzionare in Claude Code, va **spostata** in `.claude/skills/`, non cancellata. |
| **`generate-test-frames.mjs`** | Unico script della cartella realmente eseguito e funzionante; giustifica la dipendenza `playwright`. Se si rimuove, rimuovere anche la dipendenza. |
| **Immagini orfane — 3 sottoinsiemi** | Prima di cancellare i 2,9 MB: `bagno-01/02.webp` e `camera-09.webp` sono **materiale fotografico reale del B&B**, plausibilmente destinato alla pagina camere; `menu.jpeg` e `storico.webp` sono **documenti**, non decorazioni; `piatto-01.webp` è il **file corretto della referenza rotta** qui sotto — cancellarlo trasformerebbe un bug risolvibile in una foto perduta. Sono asset non collegati, non asset inutili. |
| **`dist/` e `node_modules/`** | Generati dalla mia build di verifica, entrambi in `.gitignore`. Non fanno parte del repository. |

---

## 🔴 UN BUG CONFERMATO, IN PRODUZIONE ORA

Emerso incrociando tutte le referenze immagine con il filesystem (43 referenze, 67 file):

```
src/data/piatti.js:83   img: "/immagini/piatti/piatto-01.jpeg"
file su disco:               /immagini/piatti/piatto-01.webp     ← estensione diversa
```

**Una sola referenza rotta in tutto il progetto, ma su due pagine pubbliche.** Verificato
nell'output della build (`grep -rl 'piatto-01.jpeg' dist/`):

- `dist/menu/index.html` — la card del piatto *"Melanzana, hummus, uvetta e basilico"* nella
  griglia del menu;
- `dist/piatti/melanzana-hummus/index.html` — dove l'immagine è l'**hero a tutta pagina**: la
  scheda si apre su un riquadro vuoto.

La correzione è di un carattere (`.jpeg` → `.webp`), il file corretto esiste già. Non l'ho
applicata: l'incarico è di sola lettura.

---

## 13 — I TRE PROBLEMI PRINCIPALI

**1. Il sistema oggetto dell'audit non esiste in questo repository.**
Jarvis — pipeline vocale, worker cognitivo, memoria, skill, Gemini — non c'è, e non c'è mai stato
in 24 commit: zero file Python nella storia. Finché non viene indicato il repository giusto,
qualunque conclusione su Jarvis sarebbe inventata, ed è il motivo per cui questo documento
inventaria ciò che esiste invece di descrivere ciò che era atteso.

**2. Il sito raccoglie prenotazioni senza avere un backend, e può fallire in silenzio.**
L'unico canale di prenotazione è un `mailto:` che apre il client di posta dell'utente: nessuna
richiesta viene registrata da nessuna parte, non c'è conferma, e su un dispositivo senza client
configurato il pulsante "Invia richiesta tavolo" **non fa assolutamente nulla** senza mostrare un
errore. Un ristorante che perde prenotazioni non se ne accorge: non esiste né persistenza né
analytics che lo rivelino.

**3. Ci sono difetti visibili al pubblico che nessuno ha notato perché nulla li controlla.**
`P.IVA 00000000000` nel footer di ogni pagina, un'immagine rotta sulla scheda piatto
*melanzana-hummus*, una card etichettata "TripAdvisor" che porta a `mytreats.app`, allergeni
dichiarati "in attesa di conferma" su una cucina che gestisce celiachia, e Google Fonts + Maps
senza informativa privacy. Nessuno di questi richiede più di pochi minuti per essere corretto: il
problema è che la build passa verde su tutti quanti, e senza un controllo di link/asset e senza
analytics resteranno online finché non li segnalerà un cliente.

---

### Nota di metodo

Tutte le classificazioni derivano da grafo di import statico, corrispondenza selettore↔markup,
cross-check delle referenze immagine contro il filesystem, storia git e **ispezione dell'output
reale della build**, non dai nomi dei file. Il progetto non usa caricamento dinamico (dichiarato in
apertura), quindi l'assenza di import è realmente indicativa. Nessun file è stato modificato o
cancellato; `npm install` e `npm run build` hanno prodotto solo `node_modules/` e `dist/`, entrambi
già in `.gitignore`.
