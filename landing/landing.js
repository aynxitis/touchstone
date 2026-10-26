// Landing page behaviour: a scroll progress hairline, and a reveal fallback for
// engines without scroll-driven animations. No dependencies.
// Everything here is optional: without JS the page is fully visible and readable.
(() => {
  "use strict";

  const bar = document.querySelector(".progress span");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const supportsView = typeof CSS !== "undefined" && CSS.supports
    && CSS.supports("animation-timeline: view()");

  // ── reveal fallback ──────────────────────────────────────────────────
  // Only engaged when the engine cannot drive the reveal from the scroll
  // timeline itself, so the two paths never fight.
  if (!supportsView && !reduced.matches) {
    document.documentElement.classList.add("motion-fallback");
    const items = document.querySelectorAll(".reveal");
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);      // once; never replays on scroll-out
        }
      }, { rootMargin: "0px 0px -10% 0px", threshold: 0.12 });
      items.forEach((el) => io.observe(el));
    } else {
      items.forEach((el) => el.classList.add("is-in"));
    }
  }

  // ── progress hairline ────────────────────────────────────────────────
  if (!bar) return;
  let frame = 0;
  const draw = () => {
    frame = 0;
    const doc = document.documentElement;
    const max = doc.scrollHeight - window.innerHeight;
    const progress = max > 0 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
    bar.style.transform = `scaleX(${progress})`;
  };
  const queue = () => { if (!frame) frame = window.requestAnimationFrame(draw); };
  window.addEventListener("scroll", queue, { passive: true });
  window.addEventListener("resize", queue);
  draw();
})();
