#!/usr/bin/env node
// Estrae N frame da un video per il binding scroll-driven (tecnica "Apple-style scroll scrub").
// Uso: node extract-frames.mjs <input.mp4> <output-dir> [fps]
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";

const [, , input, outputDir, fpsArg] = process.argv;

if (!input || !outputDir) {
  console.error("Uso: node extract-frames.mjs <input.mp4> <output-dir> [fps]");
  process.exit(1);
}

const fps = fpsArg ? Number(fpsArg) : 15;

mkdirSync(outputDir, { recursive: true });

execFileSync(
  "ffmpeg",
  ["-i", input, "-vf", `fps=${fps}`, "-q:v", "2", `${outputDir}/frame-%04d.jpg`, "-y"],
  { stdio: "inherit" }
);

console.log(`Frame estratti in ${outputDir} a ${fps}fps.`);
