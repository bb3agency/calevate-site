"use client";

/**
 * The voice band on the public auth screens: an ASCII speech waveform, drawn from
 * `lib/voiceWave.ts`, that sits above the form as atmosphere. It is DECORATIVE: the screen
 * reads the same with it removed, so it is `aria-hidden` and holds nothing focusable.
 *
 * ## Canvas rather than a `<pre>`
 *
 * A canvas holds no text node, so nothing in it can be read as text — by a screen reader,
 * find-in-page, a long-press selection or a contrast check — and it can be drawn at partial
 * alpha, which is what keeps the band quieter than the card's text and its button. Each
 * frame is one `fillText` per row in the app's mono face, backed at `devicePixelRatio`, so
 * it is as sharp as DOM text; a `<pre>` would re-lay out its text on every frame and could
 * only be made quiet with a colour lighter than any text is allowed to be.
 *
 * ## What it costs
 *
 * 15 frames a second from `requestAnimationFrame`, and none at all while the tab is hidden,
 * while the band is scrolled out of view, after unmount, or under
 * `prefers-reduced-motion: reduce` — which gets one still frame (`STILL_TIME`), redrawn
 * only when the band changes size. The grid comes from the band's measured width, so it
 * can never overflow sideways, and the band's height is fixed by its class before any
 * script runs, so drawing into it shifts nothing.
 */

import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

import { STILL_TIME, voiceWaveFrame } from "@/lib/voiceWave";

const FRAME_MS = 1000 / 15;
/** Quiet enough that the card and its button stay the first thing the eye lands on. */
const ALPHA = 0.7;

export function VoiceWave({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const reduced = useReducedMotion() === true;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let ctx: CanvasRenderingContext2D | null = null;
    let cols = 0;
    let rows = 0;
    let originX = 0;
    let originY = 0;
    let linePx = 10;

    const draw = (timeS: number) => {
      if (!ctx) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      voiceWaveFrame(cols, rows, timeS).forEach((line, i) => {
        ctx?.fillText(line, originX, originY + i * linePx);
      });
    };

    // Sizing resets the context, so the font and colour are set again every time.
    const measure = () => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      // A band with no box (not laid out yet, or a DOM without layout) draws nothing,
      // and is not worth a context until it has one.
      if (width === 0 || height === 0) {
        cols = rows = 0;
        return;
      }
      ctx ??= canvas.getContext("2d");
      if (!ctx) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const style = getComputedStyle(canvas);
      // The type size comes from the band's class, so each breakpoint sets its own
      // density; a row is exactly one type size tall.
      linePx = parseFloat(style.fontSize) || 10;
      ctx.font = `${linePx}px ${style.fontFamily}`;
      ctx.fillStyle = style.color;
      ctx.globalAlpha = ALPHA;
      ctx.textBaseline = "top";
      const cell = ctx.measureText("0".repeat(32)).width / 32 || linePx * 0.6;
      cols = Math.floor(width / cell);
      rows = Math.floor(height / linePx);
      // An odd count puts one row on the centre line, where silence is drawn.
      if (rows % 2 === 0) rows -= 1;
      originX = (width - cols * cell) / 2;
      originY = (height - rows * linePx) / 2;
    };

    let frame = 0;
    let last = -1;
    let elapsedS = 0;
    let onScreen = true;

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (last >= 0 && now - last < FRAME_MS - 2) return;
      // Capped so a long stall resumes where it was rather than jumping ahead.
      if (last >= 0) elapsedS += Math.min(now - last, 250) / 1000;
      last = now;
      draw(elapsedS);
    };

    const sync = () => {
      const run = !reduced && onScreen && document.visibilityState === "visible";
      if (run && frame === 0) {
        last = -1;
        frame = requestAnimationFrame(tick);
      } else if (!run && frame !== 0) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    };

    const redraw = () => {
      measure();
      draw(reduced ? STILL_TIME : elapsedS);
    };
    redraw();

    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(redraw);
    resize?.observe(canvas);
    const visible =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver(([entry]) => {
            onScreen = entry?.isIntersecting ?? true;
            sync();
          });
    visible?.observe(canvas);
    document.addEventListener("visibilitychange", sync);
    // The mono face is a web font; the first measure may have used its fallback.
    let alive = true;
    void document.fonts?.ready.then(() => {
      if (alive) redraw();
    });
    sync();

    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      frame = 0;
      resize?.disconnect();
      visible?.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, [reduced]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`pointer-events-none block w-full select-none font-mono text-brand-strong [mask-image:linear-gradient(to_right,transparent,black_15%,black_85%,transparent)] ${className}`}
    />
  );
}
