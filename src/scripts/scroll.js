import Lenis from "lenis";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

export function initScroll() {
  const lenis = new Lenis({
    duration: 1.1,
    smoothWheel: true,
  });

  lenis.on("scroll", ScrollTrigger.update);

  gsap.ticker.add((time) => {
    lenis.raf(time * 1000);
  });
  gsap.ticker.lagSmoothing(0);

  // "Oltre la soglia": ogni scena attraversa il monastero in scrub,
  // l'immagine si rivela mentre il varco successivo si apre sopra.
  const scenes = gsap.utils.toArray(".scene");

  scenes.forEach((scene, i) => {
    const img = scene.querySelector(".scene-img");
    const caption = scene.querySelector(".scene-caption");

    gsap.set(img, { scale: 1.18 });

    ScrollTrigger.create({
      trigger: scene,
      start: "top top",
      end: "bottom top",
      pin: i < scenes.length - 1,
      pinSpacing: false,
      scrub: true,
      onUpdate: (self) => {
        gsap.set(img, { scale: 1.18 - self.progress * 0.18 });
        gsap.set(scene, { filter: `brightness(${1 - self.progress * 0.35})` });
      },
    });

    if (caption) {
      gsap.fromTo(
        caption,
        { autoAlpha: 0, y: 40 },
        {
          autoAlpha: 1,
          y: 0,
          duration: 0.8,
          scrollTrigger: {
            trigger: scene,
            start: "top 70%",
            toggleActions: "play none none reverse",
          },
        }
      );
    }
  });

  ScrollTrigger.refresh();

  return lenis;
}
