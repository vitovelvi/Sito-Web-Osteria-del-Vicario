/**
 * Scroll-bound video frame scrubber (tecnica Apple-style).
 * Disegna un frame su <canvas> in base al progresso di scroll, senza mai
 * riprodurre un <video> reale: nessun problema di autoplay/buffering mobile.
 *
 * Uso:
 *   import { createScrollScrubber } from "./scroll-scrubber.js";
 *   createScrollScrubber({
 *     canvas: document.querySelector("#hero-canvas"),
 *     framePathPattern: (i) => `/frames/hero/frame-${String(i).padStart(4, "0")}.jpg`,
 *     frameCount: 90,
 *     trigger: document.querySelector(".hero"), // sezione che definisce 0%-100% di scroll
 *   });
 */
export function createScrollScrubber({ canvas, framePathPattern, frameCount, trigger }) {
  const ctx = canvas.getContext("2d");
  const images = new Array(frameCount);
  let loadedCount = 0;
  let currentFrame = -1;

  function resize() {
    canvas.width = trigger.clientWidth;
    canvas.height = trigger.clientHeight;
    if (currentFrame >= 0) draw(currentFrame);
  }

  function draw(index) {
    const img = images[index];
    if (!img || !img.complete) return;
    const canvasRatio = canvas.width / canvas.height;
    const imgRatio = img.width / img.height;
    let drawW, drawH, offsetX, offsetY;

    if (imgRatio > canvasRatio) {
      drawH = canvas.height;
      drawW = drawH * imgRatio;
      offsetX = (canvas.width - drawW) / 2;
      offsetY = 0;
    } else {
      drawW = canvas.width;
      drawH = drawW / imgRatio;
      offsetX = 0;
      offsetY = (canvas.height - drawH) / 2;
    }

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, offsetX, offsetY, drawW, drawH);
  }

  function preload() {
    for (let i = 0; i < frameCount; i++) {
      const img = new Image();
      img.src = framePathPattern(i);
      img.onload = () => {
        loadedCount++;
        if (i === 0) draw(0);
      };
      images[i] = img;
    }
  }

  function onScroll() {
    const rect = trigger.getBoundingClientRect();
    const total = rect.height + window.innerHeight;
    const progress = Math.min(1, Math.max(0, (window.innerHeight - rect.top) / total));
    const frameIndex = Math.min(frameCount - 1, Math.floor(progress * frameCount));

    if (frameIndex !== currentFrame) {
      currentFrame = frameIndex;
      draw(frameIndex);
    }
  }

  window.addEventListener("resize", resize);
  window.addEventListener("scroll", onScroll, { passive: true });

  resize();
  preload();
  onScroll();

  return {
    destroy() {
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", onScroll);
    },
  };
}
