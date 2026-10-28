"use client";

/**
 * The voice field behind the public auth screens: lanes of ASCII speech waveforms, drawn
 * from `lib/voiceWave.ts`, filling the viewport behind the header, the form and the
 * footer. It is DECORATIVE: the screen reads the same with it removed, so it is
 * `aria-hidden`, takes no pointer events and holds nothing focusable.
 *
 * ## Canvas rather than a `<pre>`
 *
 * A canvas holds no text node, so nothing in it can be read as text — by a screen reader,
 * find-in-page, a long-press selection or a contrast check — and it can be drawn at partial
 * alpha, which lets the quiet texture stay light while the loud peaks carry full brand ink.
 * Each frame is three `fillText` calls per row (one per ink layer) in the app's mono face,
 * backed at `devicePixelRatio`, so it is as sharp as DOM text; a full-screen `<pre>` would
 * re-lay out thousands of glyphs every frame.
 *
 * ## Keeping the text in front readable
 *
 * The mask dims the field to a fraction of its strength in an ellipse behind the centre
 * column (the heading and the form) and along the header and footer strips, so text
 * never sits on full-strength characters; the card itself is opaque. Everywhere else the
 * field runs at full strength, which is what fills the screen.
 *
 * ## What it costs
 *
 * 15 frames a second from `requestAnimationFrame`, backed at most at 2x, and none at all
 * while the tab is hidden, after unmount, or under `prefers-reduced-motion: reduce` — which
 * gets one still frame (`STILL_TIME`), redrawn only when the viewport changes size. It is
 * `position: fixed`, so it is always in view and needs no IntersectionObserver, never takes
 * part in layout and cannot cause a sideways scroll; the grid comes from its measured size.
 */

import { useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

import { STILL_TIME, inkLayers, voiceField } from "@/lib/voiceWave";

const FRAME_MS = 1000 / 15;
const MAX_DPR = 2;
/** Opacity of the faint, mid and full ink layers (`inkLayers`). */
const INK_ALPHA = [0.4, 0.75, 1] as const;

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
      const { lines, centres } = voiceField(cols, rows, timeS);
      inkLayers(lines, centres).forEach((layer, tier) => {
        if (!ctx) return;
        ctx.globalAlpha = INK_ALPHA[tier]!;
        layer.forEach((line, i) => ctx?.fillText(line, originX, originY + i * linePx));
      });
    };

    // Sizing resets the context, so the font and colour are set again every time.
    const measure = () => {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      // A canvas with no box (not laid out yet, or a DOM without layout) draws nothing,
      // and is not worth a context until it has one.
      if (width === 0 || height === 0) {
        cols = rows = 0;
        return;
      }
      ctx ??= canvas.getContext("2d");
      if (!ctx) return;
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const style = getComputedStyle(canvas);
      // The type size comes from the class, so each breakpoint sets its own density; a row
      // is exactly one type size tall.
      linePx = parseFloat(style.fontSize) || 10;
      ctx.font = `${linePx}px ${style.fontFamily}`;
      ctx.fillStyle = style.color;
      ctx.textBaseline = "top";
      const cell = ctx.measureText("0".repeat(32)).width / 32 || linePx * 0.6;
      cols = Math.floor(width / cell);
      rows = Math.floor(height / linePx);
      originX = (width - cols * cell) / 2;
      originY = (height - rows * linePx) / 2;
    };

    let frame = 0;
    let last = -1;
    let elapsedS = 0;

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (last >= 0 && now - last < FRAME_MS - 2) return;
      // Capped so a long stall resumes where it was rather than jumping ahead.
      if (last >= 0) elapsedS += Math.min(now - last, 250) / 1000;
      last = now;
      draw(elapsedS);
    };

    const sync = () => {
      const run = !reduced && document.visibilityState === "visible";
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
      document.removeEventListener("visibilitychange", sync);
    };
  }, [reduced]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`voice-field pointer-events-none fixed inset-0 z-below block h-full w-full select-none font-mono text-[10px] text-brand-strong sm:text-xs lg:text-[13px] ${className}`}
    />
  );
}
