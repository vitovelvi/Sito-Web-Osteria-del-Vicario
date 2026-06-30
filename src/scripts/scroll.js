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

export function initHero() {
  const hero = document.querySelector(".hero");
  const imgs = hero?.querySelectorAll(".hero-img");
  const day = hero?.querySelector(".hero-img-day");
  const night = hero?.querySelector(".hero-img-night");
  const caption = hero?.querySelector(".hero-caption");
  if (!hero || !imgs?.length) return;

  gsap.set(imgs, { scale: 1.42, xPercent: 0, rotateX: 0, transformOrigin: "55% 38%" });

  // timeline pinnata multi-keyframe: simula uno "scrub" cinematico
  // (zoom verso l'arco -> dissolvenza giorno/notte -> buio verso il contenuto sotto)
  const tl = gsap.timeline({
    scrollTrigger: {
      trigger: hero,
      start: "top top",
      end: "+=160%",
      pin: true,
      pinSpacing: false,
      scrub: 1,
    },
  });

  tl.to(imgs, { scale: 1.16, xPercent: -2, rotateX: 4, duration: 0.5, ease: "none" }, 0)
    .to(imgs, { scale: 1, xPercent: 2, rotateX: 8, duration: 0.5, ease: "none" }, 0.5)
    .to(caption, { autoAlpha: 0, y: -80, duration: 0.3, ease: "power1.in" }, 0.45);

  if (day && night) {
    tl.to(night, { opacity: 1, duration: 0.45, ease: "none" }, 0.3).to(
      day,
      { opacity: 0, duration: 0.45, ease: "none" },
      0.3
    );
  }
}

export function initEmblem() {
  const stage = document.getElementById("emblem-stage");
  const emblem = document.getElementById("emblem-3d");
  if (!stage || !emblem) return;

  gsap.to(emblem, {
    y: -18,
    rotateZ: 3,
    duration: 2.6,
    ease: "sine.inOut",
    yoyo: true,
    repeat: -1,
  });

  const quickX = gsap.quickTo(emblem, "rotateY", { duration: 0.6, ease: "power3" });
  const quickY = gsap.quickTo(emblem, "rotateX", { duration: 0.6, ease: "power3" });

  window.addEventListener("pointermove", (event) => {
    const { innerWidth, innerHeight } = window;
    const relX = (event.clientX / innerWidth - 0.5) * 2;
    const relY = (event.clientY / innerHeight - 0.5) * 2;
    quickX(relX * 22);
    quickY(relY * -16);
  });
}

export function initCinemaGallery(selector = ".cinema-pin") {
  const wrap = document.querySelector(selector);
  const track = wrap?.querySelector(".cinema-track");
  if (!wrap || !track) return;

  const mq = window.matchMedia("(max-width: 760px)");
  if (mq.matches) return;

  ScrollTrigger.create({
    trigger: wrap,
    start: "top top",
    end: "bottom bottom",
    scrub: 1,
    onUpdate: (self) => {
      const max = track.scrollWidth - track.clientWidth;
      gsap.set(track, { x: -max * self.progress });
    },
  });
}

export function initPageHeader() {
  const header = document.querySelector(".page-header");
  const img = header?.querySelector(".page-header-img");
  if (!header || !img) return;

  gsap.set(img, { scale: 1.22 });

  ScrollTrigger.create({
    trigger: header,
    start: "top top",
    end: "bottom top",
    scrub: true,
    onUpdate: (self) => {
      gsap.set(img, {
        scale: 1.22 - self.progress * 0.16,
        y: self.progress * 40,
      });
    },
  });
}

export function initReveal(selector = ".reveal") {
  gsap.utils.toArray(selector).forEach((el) => {
    gsap.fromTo(
      el,
      { autoAlpha: 0, y: 48 },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.9,
        ease: "power3.out",
        scrollTrigger: {
          trigger: el,
          start: "top 85%",
          toggleActions: "play none none reverse",
        },
      }
    );
  });
}

export function initTilt(selector = ".tilt-card") {
  const cards = gsap.utils.toArray(selector);

  cards.forEach((card) => {
    const quickX = gsap.quickTo(card, "rotateY", { duration: 0.4, ease: "power3" });
    const quickY = gsap.quickTo(card, "rotateX", { duration: 0.4, ease: "power3" });

    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      const relX = (event.clientX - rect.left) / rect.width - 0.5;
      const relY = (event.clientY - rect.top) / rect.height - 0.5;
      quickX(relX * 14);
      quickY(relY * -14);
    });

    card.addEventListener("pointerleave", () => {
      quickX(0);
      quickY(0);
    });
  });
}
