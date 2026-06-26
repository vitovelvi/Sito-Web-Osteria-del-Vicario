#!/usr/bin/env node
// Genera una sequenza di frame PLACEHOLDER (non AI) via Canvas + Playwright, per testare
// la fluidità di scroll-scrubber.js senza dipendere da Nano Banana / Cling 3.0 (Fase 2,
// a pagamento, saltata per il pilota). Simula una "scena" cinematica con un pan/zoom
// su un gradiente caldo (toni cotto/oro) e un overlay di testo, in stile monastero/candela.
// Uso: node generate-test-frames.mjs <output-dir> [frameCount]

import { chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

const [, , outputDir, frameCountArg] = process.argv;
if (!outputDir) {
  console.error("Uso: node generate-test-frames.mjs <output-dir> [frameCount]");
  process.exit(1);
}
const frameCount = frameCountArg ? Number(frameCountArg) : 60;
const WIDTH = 1280;
const HEIGHT = 720;

mkdirSync(outputDir, { recursive: true });

const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });

await page.setContent(`<canvas id="c" width="${WIDTH}" height="${HEIGHT}"></canvas>`);

for (let i = 0; i < frameCount; i++) {
  const t = i / (frameCount - 1);
  const dataUrl = await page.evaluate(
    ({ t, w, h }) => {
      const c = document.getElementById("c");
      const ctx = c.getContext("2d");

      const zoom = 1.15 - t * 0.15;
      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(zoom, zoom);
      ctx.translate(-w / 2, -h / 2);

      const grad = ctx.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, `rgb(${33 + t * 20},${23 + t * 10},${16})`);
      grad.addColorStop(0.5, `rgb(${176 - t * 40},${90 + t * 40},${48 + t * 60})`);
      grad.addColorStop(1, `rgb(${232 - t * 30},${177 - t * 20},${90})`);
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, w, h);

      ctx.globalAlpha = 0.15;
      ctx.fillStyle = "#000";
      for (let i = 0; i < 6; i++) {
        ctx.beginPath();
        ctx.arc(
          w * (0.2 + i * 0.15) + Math.sin(t * 6 + i) * 30,
          h * 0.6 + Math.cos(t * 4 + i) * 40,
          50 + i * 8,
          0,
          Math.PI * 2
        );
        ctx.fill();
      }
      ctx.restore();

      ctx.globalAlpha = 1 - t * 0.4;
      ctx.fillStyle = "#f2e9d7";
      ctx.font = "bold 28px sans-serif";
      ctx.fillText(`PLACEHOLDER SCENE — frame ${String(Math.round(t * 100)).padStart(3, "0")}%`, 40, h - 50);

      return c.toDataURL("image/jpeg", 0.85);
    },
    { t, w: WIDTH, h: HEIGHT }
  );

  const base64 = dataUrl.replace(/^data:image\/jpeg;base64,/, "");
  const filename = `${outputDir}/frame-${String(i + 1).padStart(4, "0")}.jpg`;
  writeFileSync(filename, Buffer.from(base64, "base64"));
}

await browser.close();
console.log(`${frameCount} frame placeholder generati in ${outputDir}.`);
