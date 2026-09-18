/**
 * EGUP — Shared site behaviour
 * Mobile navigation, header scroll state, scroll reveals,
 * back-to-top control, footer year. Runs on every page.
 */

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
// Exposed so other page-specific scripts (the registration wizard, etc.)
// can share this single check rather than each re-querying matchMedia.
window.egupPrefersReducedMotion = prefersReducedMotion;

function smoothScrollTo(options) {
  // JS's own `behavior: "smooth"` argument overrides the CSS
  // `scroll-behavior` reduced-motion fallback in base.css — that CSS
  // rule only changes what "smooth" defaults to, it doesn't stop an
  // explicit request for it. Every scrollTo call in this project should
  // go through this helper instead of calling window.scrollTo directly.
  window.scrollTo({ ...options, behavior: prefersReducedMotion() ? "auto" : (options.behavior || "smooth") });
}

function initNav() {
  const header = document.querySelector(".site-header");
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".site-nav");
  if (!header) return;

  const onScroll = () => {
    header.classList.toggle("is-solid", window.scrollY > 48);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  if (toggle && nav) {
    // Content behind the full-screen mobile nav overlay (<main>, <footer>)
    // stays in the tab order and screen-reader tree by default even
    // though it's visually hidden underneath — a real gap against §38's
    // "modal focus" requirement. Marking it inert while the menu is open
    // is additive only: it doesn't touch any of the working open/close/
    // Escape/scroll-lock behavior below, so the existing behavior your
    // brief said not to break stays exactly as it was.
    const inertTargets = [document.getElementById("main"), document.querySelector("footer")].filter(Boolean);
    const setBackgroundInert = (isInert) => {
      inertTargets.forEach((el) => {
        if (isInert) {
          el.setAttribute("aria-hidden", "true");
          el.setAttribute("inert", "");
        } else {
          el.removeAttribute("aria-hidden");
          el.removeAttribute("inert");
        }
      });
    };

    const closeNav = () => {
      nav.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.classList.remove("is-active");
      document.body.style.overflow = "";
      setBackgroundInert(false);
    };
    const openNav = () => {
      nav.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
      toggle.classList.add("is-active");
      document.body.style.overflow = "hidden";
      setBackgroundInert(true);
    };

    toggle.addEventListener("click", () => {
      if (nav.classList.contains("is-open")) closeNav();
      else openNav();
    });
    nav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", closeNav);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && nav.classList.contains("is-open")) {
        closeNav();
        toggle.focus();
      }
    });
  }
}

function initReveals() {
  const items = document.querySelectorAll(".reveal");
  if (!items.length) return;
  if (!("IntersectionObserver" in window)) {
    items.forEach((el) => el.classList.add("is-visible"));
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" }
  );
  items.forEach((el) => observer.observe(el));
}

function initBackToTop() {
  const btn = document.querySelector(".to-top");
  if (!btn) return;
  window.addEventListener(
    "scroll",
    () => btn.classList.toggle("is-visible", window.scrollY > 700),
    { passive: true }
  );
  btn.addEventListener("click", () => smoothScrollTo({ top: 0 }));
}

function initFooterYear() {
  document.querySelectorAll("[data-current-year]").forEach((el) => {
    el.textContent = new Date().getFullYear();
  });
}

function initFadeImages() {
  const images = document.querySelectorAll("img.fade-img");
  images.forEach((img) => {
    if (img.complete && img.naturalWidth > 0) {
      img.classList.add("is-loaded");
    } else {
      img.addEventListener("load", () => img.classList.add("is-loaded"), { once: true });
      // Never leave an image permanently invisible if 'load' never fires
      // for some reason (cached edge case, broken src, etc.).
      img.addEventListener("error", () => img.classList.add("is-loaded"), { once: true });
    }
  });
}

function initStatCounters() {
  const counters = document.querySelectorAll("[data-count-to]");
  if (!counters.length) return;
  const animate = (el) => {
    const target = parseInt(el.dataset.countTo, 10);
    if (!Number.isFinite(target)) return;
    if (prefersReducedMotion()) {
      // Not a CSS transition/animation, so the global reduced-motion
      // override in base.css doesn't touch this requestAnimationFrame
      // loop — skip straight to the final number instead.
      el.textContent = target.toLocaleString();
      return;
    }
    const duration = 1400;
    const start = performance.now();
    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out-cubic
      el.textContent = Math.round(target * eased).toLocaleString();
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  };
  if (!("IntersectionObserver" in window)) {
    counters.forEach(animate);
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          animate(entry.target);
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.4 }
  );
  counters.forEach((el) => observer.observe(el));
}

function initCountdown() {
  const root = document.querySelector("[data-countdown-to]");
  if (!root) return;
  const target = new Date(root.dataset.countdownTo).getTime();
  if (!Number.isFinite(target)) return;

  const daysEl = root.querySelector("[data-cd-days]");
  const hoursEl = root.querySelector("[data-cd-hours]");
  const minsEl = root.querySelector("[data-cd-mins]");

  function tick() {
    const diff = target - Date.now();
    if (diff <= 0) {
      root.hidden = true;
      return;
    }
    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const mins = Math.floor((diff % 3600000) / 60000);
    if (daysEl) daysEl.textContent = days;
    if (hoursEl) hoursEl.textContent = String(hours).padStart(2, "0");
    if (minsEl) minsEl.textContent = String(mins).padStart(2, "0");
  }
  tick();
  setInterval(tick, 60000);
}

function initCopyButtons() {
  document.querySelectorAll("[data-copy-target]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const targetSpec = btn.dataset.copyTarget;
      // Supports either a CSS selector ("#htp-paybill") or a bare
      // data-attribute name ("data-manual-paybill") scoped to the
      // nearest containing paragraph/div.
      const targetEl = targetSpec.startsWith("#") || targetSpec.startsWith(".")
        ? document.querySelector(targetSpec)
        : btn.closest("p, div")?.querySelector(`[${targetSpec}]`);
      const text = targetEl ? targetEl.textContent.trim() : "";
      if (!text) return;
      const original = btn.textContent;
      try {
        await navigator.clipboard.writeText(text);
      } catch (e) {
        window.prompt("Copy this value:", text);
      }
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = original; }, 1600);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initNav();
  initReveals();
  initBackToTop();
  initFooterYear();
  initFadeImages();
  initStatCounters();
  initCountdown();
  initCopyButtons();
});
