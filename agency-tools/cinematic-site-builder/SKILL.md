---
name: cinematic-site-builder
description: >
  Genera siti web "cinematici" in autopilota a partire dall'URL di un vecchio
  sito (ristorante, hotel, negozio locale): analizza il brand, propone scene
  video AI, mappa il video sullo scroll, assembla il sito da template di
  settore e lo pubblica su Vercel. Usa questa skill quando l'utente fornisce
  un URL e chiede di "generare/rifare il sito" in stile cinematografico.
---

# Cinematic Site Builder

Pipeline a 4 fasi. Ogni fase produce un artefatto verificabile dall'utente
PRIMA di passare alla fase successiva — non saltare le approvazioni.

## Input richiesto all'avvio

- `url`: sito esistente del cliente (obbligatorio)
- `settore`: ristorante | hotel | negozio | altro (se omesso, dedurlo dal sito)
- API key necessarie per le fasi 2 e 4 (vedi sotto) — se assenti, fermarsi e
  chiederle, non inventare chiamate.

## Fase 1 — Brand Analysis

1. `WebFetch` sull'`url` fornito: estrarre nome attività, tono di voce,
   prodotti/servizi principali, colori dominanti (se rilevabili da CSS/immagini),
   font usati, eventuali foto reali riutilizzabili.
2. Derivare:
   - **Palette** (3-5 colori: primario, accento, neutro scuro, neutro chiaro)
   - **Coppia tipografica** (1 display serif/decorativo + 1 body sans, da Google Fonts)
   - **Tono/slogan**: 1 headline cinematografica (max 8 parole) + 1 sottotitolo
3. Generare `templates/brand-card.html` (copiare lo scheletro in
   `templates/brand-card.template.html`) con: palette swatch, font preview,
   headline/slogan, 3 bullet di posizionamento ("perché questo brand è unico").
4. **STOP**: mostrare il percorso del file all'utente e chiedere conferma
   esplicita prima di procedere alla Fase 2. Se l'utente chiede modifiche,
   rigenerare solo le parti contestate.

## Fase 2 — Scene Generation (richiede API key utente)

Richiede in `.env` (mai committare):
- `GOOGLE_CLOUD_API_KEY` (per generazione immagine "Nano Banana"/Imagen)
- `WAVESPEED_API_KEY` o equivalente (per image-to-video, es. Cling 3.0)

Se le key non sono presenti: fermarsi e chiedere all'utente di fornirle,
spiegando dove inserirle (`.env`, variabile per variabile). Non procedere
con chiamate finte o placeholder spacciati per risultati reali.

Con le key disponibili:
1. Proporre 3 concetti di scena cinematica coerenti col settore e la brand
   card (es. ristorante → piatto che fuma, hotel → tenda che si apre su vista,
   negozio → prodotto che ruota in luce calda).
2. Per il concetto scelto dall'utente: generare l'immagine still via
   `scripts/generate-still.mjs`, poi animarla in video 3-6s via
   `scripts/animate-still.mjs`.
3. Scaricare il video in `public/video/hero-scene.mp4`.
4. **STOP**: mostrare il video, chiedere conferma prima della Fase 3.

## Fase 3 — Website Build (scroll-mapped video)

Tecnica: il video NON viene mai riprodotto come `<video>` — viene
decomposto in frame e i frame vengono "scrubbati" in base alla posizione di
scroll (stessa tecnica delle pagine prodotto Apple). Vedi
`scripts/extract-frames.mjs` (richiede `ffmpeg` installato) e
`templates/scroll-scrubber.js` per il modulo runtime pronto all'uso.

Passi:
1. Estrarre N frame (default 90, ~15/s per un video di 6s) dal video con
   `node scripts/extract-frames.mjs public/video/hero-scene.mp4 public/frames/hero`.
2. Inserire `templates/scroll-scrubber.js` nella pagina hero, puntandolo
   alla cartella frame e al numero di frame generati.
3. Selezionare i moduli cinematici di settore da `templates/modules/`
   (accordion menu animato, scritte kinetic-type, gallerie a scroll, glitch
   transition) e assemblare le sezioni nell'ordine del template di settore
   in `templates/site-structures/<settore>.md`.
4. Riusare sempre contenuti reali del cliente (testi, foto, indirizzo,
   contatti) raccolti in Fase 1 — non inventare dati di business.
5. **STOP**: far girare il sito in locale (`npm run dev`), verificare lo
   scroll-scrub a 60fps, chiedere conferma prima del deploy.

## Fase 4 — Autopilot Deploy (richiede account utente)

Richiede che l'utente abbia già eseguito `vercel login` sulla macchina, o
fornito un `VERCEL_TOKEN`. Senza questo, fermarsi e chiederlo.

1. `vercel --prod --yes` dalla root del progetto generato.
2. Restituire l'URL live all'utente.
3. Non eseguire deploy automatici ripetuti senza che l'utente lo richieda
   esplicitamente per quella iterazione.

## Principi non negoziabili

- Mai inventare contenuti di business (numeri di telefono, indirizzi,
  recensioni, prezzi) — solo dati reali raccolti dal sito di origine o
  forniti dal cliente.
- Mai spacciare un placeholder per un risultato di API reale.
- Fermarsi alle 4 checkpoint di approvazione: non procedere in autonomia
  totale tra una fase e l'altra se l'utente non ha confermato.
- I template per settore vivono in `templates/site-structures/` e vanno
  estesi (non duplicati) quando emerge un nuovo settore ricorrente.
