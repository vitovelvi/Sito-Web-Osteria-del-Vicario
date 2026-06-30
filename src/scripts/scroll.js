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

export function initHeroIntro() {
  const hero = document.querySelector(".hero");
  if (!hero) return;

  const eyebrow = hero.querySelector(".eyebrow");
  const h1 = hero.querySelector("h1");
  const text = hero.querySelector(".hero-text");
  const actions = hero.querySelector(".hero-actions");

  gsap.set([eyebrow, h1, text, actions], { autoAlpha: 0, y: 30 });

  const tl = gsap.timeline({ delay: 0.2 });
  tl.to(eyebrow, { autoAlpha: 1, y: 0, duration: 0.8, ease: "power2.out" })
    .to(h1, { autoAlpha: 1, y: 0, duration: 1, ease: "power2.out" }, "-=0.5")
    .to(text, { autoAlpha: 1, y: 0, duration: 0.9, ease: "power2.out" }, "-=0.6")
    .to(actions, { autoAlpha: 1, y: 0, duration: 0.7, ease: "power2.out" }, "+=0.5");
}

export function initNavScroll() {
  const nav = document.querySelector(".nav-funnel.nav-transparent");
  if (!nav) return;

  const onScroll = () => {
    nav.classList.toggle("scrolled", window.scrollY > 60);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });
}

export function initStorytelling(selector = ".storytelling") {
  const section = document.querySelector(selector);
  const pin = section?.querySelector(".story-pin");
  if (!section || !pin) return;

  const lines = gsap.utils.toArray(section.querySelectorAll(".story-line"));
  if (!lines.length) return;

  gsap.set(lines, { autoAlpha: 0, y: 30 });
  gsap.set(lines[0], { autoAlpha: 1, y: 0 });

  const tl = gsap.timeline({
    scrollTrigger: {
      trigger: section,
      start: "top top",
      end: "bottom bottom",
      pin,
      pinSpacing: false,
      scrub: 1,
    },
  });

  lines.forEach((line, i) => {
    if (i === 0) return;
    tl.to(lines[i - 1], { autoAlpha: 0, y: -30, duration: 0.3 }, i - 0.5)
      .to(line, { autoAlpha: 1, y: 0, duration: 0.3 }, i - 0.5);
  });
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

export function initProgressBar() {
  const bar = document.getElementById("progressBar");
  if (!bar) return;

  ScrollTrigger.create({
    trigger: document.body,
    start: "top top",
    end: "bottom bottom",
    onUpdate: (self) => {
      bar.style.width = `${self.progress * 100}%`;
    },
  });
}

export function initStatement(selector = ".statement") {
  const section = document.querySelector(selector);
  const el = section?.querySelector(".statement-text");
  if (!section || !el) return;

  const text = el.textContent.trim();
  el.innerHTML = text
    .split(" ")
    .map((w) => `<span class="word">${w}</span>`)
    .join(" ");
  const words = el.querySelectorAll(".word");

  gsap.timeline({
    scrollTrigger: { trigger: section, start: "top 70%", end: "top 20%", scrub: true },
  }).to(words, { opacity: 1, stagger: { each: 0.04, from: "start" } });
}

export function initGrowImage(selector = ".grow-wrap") {
  const wrap = document.querySelector(selector);
  const img = wrap?.querySelector(".grow-img");
  const caption = wrap?.querySelector(".grow-caption");
  if (!wrap || !img) return;

  gsap.timeline({
    scrollTrigger: { trigger: wrap, start: "top top", end: "+=100%", scrub: true, pin: true },
  })
    .to(img, { width: "100%", height: "100%", borderRadius: "0rem", ease: "none" })
    .to(caption, { opacity: 1, ease: "none" }, 0.5);
}

export function initMarquee(selector = ".marquee-pin") {
  const wrap = document.querySelector(selector);
  const track = wrap?.querySelector(".marquee-track");
  if (!wrap || !track) return;

  gsap.to(track, {
    xPercent: -50,
    ease: "none",
    scrollTrigger: { trigger: wrap, start: "top top", end: "+=120%", scrub: true, pin: true },
  });
}

export function initParallax(selector = ".parallax-img", triggerSelector = ".terrazza") {
  const img = document.querySelector(selector);
  const trigger = document.querySelector(triggerSelector);
  if (!img || !trigger) return;

  gsap.to(img, {
    yPercent: 15,
    ease: "none",
    scrollTrigger: { trigger, start: "top bottom", end: "bottom top", scrub: true },
  });
}

export function initCounters(selector = ".rec-stat") {
  gsap.utils.toArray(selector).forEach((stat) => {
    const target = parseFloat(stat.dataset.count);
    const decimals = stat.dataset.decimals ? parseInt(stat.dataset.decimals, 10) : 0;

    ScrollTrigger.create({
      trigger: stat,
      start: "top 85%",
      once: true,
      onEnter: () => {
        gsap.to(
          {},
          {
            duration: 1.6,
            ease: "power2.out",
            onUpdate: function () {
              stat.textContent = (target * this.progress()).toFixed(decimals);
            },
          }
        );
      },
    });
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
