// A bar-style level meter drawn on <canvas>, driven by a single rAF loop.
//
// Silence still needs to look alive (a gentle shimmer says "I'm listening"),
// but the loop must not spin at 60fps forever, so it only runs while a take
// is active, and prefers-reduced-motion swaps the shimmer for a static meter
// that still tracks the incoming level.

const BAR_COUNT = 24;
const IDLE_LEVEL = 0.06;

export function createWaveform(canvas) {
  const ctx = canvas.getContext("2d");
  const reduceMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

  let level = 0;
  let running = false;
  let rafId = 0;
  let cssWidth = 0;
  let cssHeight = 0;
  let dpr = 1;

  // Per-bar phase offsets so the idle shimmer ripples instead of pulsing in
  // lockstep, and per-bar smoothed levels so a live signal doesn't jitter.
  const phases = Array.from({ length: BAR_COUNT }, (_, i) => (i / BAR_COUNT) * Math.PI * 2);
  const smoothed = new Array(BAR_COUNT).fill(IDLE_LEVEL);

  function tokens() {
    const style = getComputedStyle(canvas);
    return {
      accent: style.getPropertyValue("--accent").trim() || "currentColor",
      accent2: style.getPropertyValue("--accent2").trim() || "currentColor",
      muted: style.getPropertyValue("--text-muted").trim() || "currentColor",
    };
  }

  function measure() {
    const rect = canvas.getBoundingClientRect();
    cssWidth = rect.width || canvas.width;
    cssHeight = rect.height || canvas.height;
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(cssWidth * dpr));
    canvas.height = Math.max(1, Math.round(cssHeight * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function barHeights(t) {
    const reduced = reduceMotionQuery.matches;
    return phases.map((phase, i) => {
      const target = reduced
        ? Math.max(IDLE_LEVEL, level)
        : level > IDLE_LEVEL
          ? level * (0.6 + 0.4 * Math.sin(t / 260 + phase))
          : IDLE_LEVEL * (0.5 + 0.5 * Math.sin(t / 900 + phase));
      // Exponential smoothing keeps bars from snapping between frames.
      smoothed[i] += (target - smoothed[i]) * (reduced ? 1 : 0.25);
      return Math.max(0.04, Math.min(1, smoothed[i]));
    });
  }

  function draw(t) {
    const { accent, accent2 } = tokens();
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const gap = cssWidth / BAR_COUNT;
    const barWidth = Math.max(1, gap * 0.5);
    const heights = barHeights(t);

    for (let i = 0; i < BAR_COUNT; i++) {
      const h = Math.max(2, heights[i] * cssHeight);
      const x = i * gap + (gap - barWidth) / 2;
      const y = (cssHeight - h) / 2;
      const grad = ctx.createLinearGradient(0, y, 0, y + h);
      grad.addColorStop(0, accent2);
      grad.addColorStop(1, accent);
      ctx.fillStyle = grad;
      const r = Math.min(barWidth / 2, h / 2);
      roundedRect(ctx, x, y, barWidth, h, r);
      ctx.fill();
    }
  }

  function roundedRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function frame(t) {
    if (!running) return;
    draw(t);
    // Reduced motion: still redraw so setLevel() updates are reflected, but
    // there is no need to chase a smooth animation loop as aggressively —
    // rAF is fine either way since draw() itself is cheap and idempotent.
    rafId = requestAnimationFrame(frame);
  }

  function start() {
    if (running) return;
    running = true;
    measure();
    rafId = requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
    level = 0;
    smoothed.fill(IDLE_LEVEL);
    // Leave a resting frame drawn rather than a blank canvas.
    measure();
    draw(0);
  }

  function setLevel(l) {
    level = Math.max(0, Math.min(1, l || 0));
  }

  window.addEventListener("resize", () => {
    measure();
    if (!running) draw(0);
  });

  measure();
  draw(0);

  return { setLevel, start, stop };
}
