/**
 * EGUP — Hero carousel.
 * Auto-rotates .hero__slide elements with a crossfade, keeping the
 * headline/subtitle and dot indicators in sync. Only runs a timer when
 * there's more than one slide. Pauses on hover/focus so a visitor
 * reading the text isn't fighting a moving background, and does a
 * single static swap (no animation) for prefers-reduced-motion.
 */
function initHeroCarousel() {
  const root = document.querySelector("[data-hero-carousel]");
  if (!root) return;

  const slides = Array.from(root.querySelectorAll(".hero__slide"));
  const dots = Array.from(root.querySelectorAll("[data-hero-dots] button"));
  const titleEl = root.querySelector("[data-hero-title]");
  const subtitleEl = root.querySelector("[data-hero-subtitle]");
  if (slides.length <= 1) return; // nothing to rotate

  const INTERVAL_MS = 6000;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let current = 0;
  let timer = null;

  function goTo(index) {
    slides[current].classList.remove("is-active");
    dots[current] && dots[current].classList.remove("is-active");
    current = (index + slides.length) % slides.length;
    slides[current].classList.add("is-active");
    dots[current] && dots[current].classList.add("is-active");

    const slide = slides[current];
    if (titleEl && slide.dataset.title) titleEl.textContent = slide.dataset.title;
    if (subtitleEl && slide.dataset.subtitle) subtitleEl.textContent = slide.dataset.subtitle;
  }

  function next() { goTo(current + 1); }

  function start() {
    if (prefersReducedMotion || timer) return;
    timer = setInterval(next, INTERVAL_MS);
  }
  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  dots.forEach((dot, i) => {
    dot.addEventListener("click", () => { goTo(i); stop(); start(); });
  });

  root.addEventListener("mouseenter", stop);
  root.addEventListener("mouseleave", start);
  root.addEventListener("focusin", stop);
  root.addEventListener("focusout", start);

  start();
}

document.addEventListener("DOMContentLoaded", initHeroCarousel);
