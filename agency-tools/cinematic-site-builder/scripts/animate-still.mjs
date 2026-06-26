#!/usr/bin/env node
// Anima un'immagine still in un breve video cinematico (image-to-video, es. Cling 3.0
// via un aggregatore come Wave Speed). Richiede WAVESPEED_API_KEY in .env.
// Uso: node animate-still.mjs <input.png> <output.mp4> "<motion-prompt>"

const apiKey = process.env.WAVESPEED_API_KEY;
const [, , inputImage, outputVideo, motionPrompt] = process.argv;

if (!apiKey) {
  console.error(
    "Manca WAVESPEED_API_KEY (o la key del tuo aggregatore image-to-video) in .env. " +
      "Aggiungila e riprova: l'animazione reale richiede questa key."
  );
  process.exit(1);
}

if (!inputImage || !outputVideo) {
  console.error('Uso: node animate-still.mjs <input.png> <output.mp4> "<motion-prompt>"');
  process.exit(1);
}

console.error(
  "Placeholder di integrazione: verifica l'endpoint e il formato richiesta esatti " +
    "dell'aggregatore scelto (Wave Speed o altro) per il modello Cling 3.0 prima di " +
    "eseguire la chiamata reale. Ogni provider ha contratto API diverso."
);
process.exit(1);

// Esempio indicativo (formato da adattare al provider reale):
//
// const upload = await fetch(`${BASE_URL}/upload`, { method: "POST", body: imageBuffer, headers: {...} });
// const { taskId } = await fetch(`${BASE_URL}/image-to-video`, {
//   method: "POST",
//   headers: { Authorization: `Bearer ${apiKey}` },
//   body: JSON.stringify({ image_url: upload.url, prompt: motionPrompt, duration: 5 }),
// }).then((r) => r.json());
// poll taskId until status === "completed", then download result to outputVideo.
