#!/usr/bin/env node
// Genera un'immagine still ad alta qualità via Google Cloud Imagen ("Nano Banana").
// Richiede GOOGLE_CLOUD_API_KEY in .env. Non inventa risultati se la key manca.
// Uso: node generate-still.mjs "<prompt>" <output.png>

const apiKey = process.env.GOOGLE_CLOUD_API_KEY;
const [, , prompt, outputPath] = process.argv;

if (!apiKey) {
  console.error(
    "Manca GOOGLE_CLOUD_API_KEY in .env. Aggiungila e riprova: la generazione " +
      "immagine reale richiede questa key, non può essere simulata."
  );
  process.exit(1);
}

if (!prompt || !outputPath) {
  console.error('Uso: node generate-still.mjs "<prompt>" <output.png>');
  process.exit(1);
}

// Endpoint indicativo: adattare al modello Imagen effettivamente disponibile
// sul progetto Google Cloud dell'utente (nome modello, region, versione API).
const ENDPOINT =
  "https://us-central1-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/us-central1/publishers/google/models/imagen-3.0:predict";

console.error(
  "Placeholder di integrazione: imposta PROJECT_ID e verifica il nome modello " +
    "Imagen attivo sul tuo account Google Cloud prima di eseguire la chiamata reale."
);
process.exit(1);

// Esempio di chiamata reale una volta configurato PROJECT_ID:
//
// const res = await fetch(ENDPOINT, {
//   method: "POST",
//   headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
//   body: JSON.stringify({ instances: [{ prompt }], parameters: { sampleCount: 1 } }),
// });
// const data = await res.json();
// const base64 = data.predictions[0].bytesBase64Encoded;
// await writeFile(outputPath, Buffer.from(base64, "base64"));
