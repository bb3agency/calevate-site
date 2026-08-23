"use client";

/**
 * A one-shot success (or error) flourish: concentric ripples expand and fade while a filled
 * disc springs in behind a check — recoloured to the Calevate green from the blue sample.
 *
 * ## Colour
 *
 * Every blue in the sample (`#5686FF` and its alpha variants) becomes a brand token: the
 * disc is `--brand`, the ripples `--brand-bright`, the glyph white. The optional
 * `variant="error"` is the ONE place a non-green is allowed — a single red (`#dc2626`) with
 * an X in place of the check — because a failure that reads as green is worse than an
 * off-palette colour.
 *
 * ## Responsive and reduced-motion
 *
 * The container defaults to `h-32 w-32 sm:h-48 sm:w-48`, so it is 128px on a phone and grows
 * to 192px from `sm` up; the SVG is a `viewBox` so every ripple and the glyph scale with it.
 * A caller can replace that with `sizeClassName` (this repo has no tailwind-merge, so a size
 * passed through `className` would not reliably win — a dedicated prop is the clean override).
 * Under `useReducedMotion` nothing animates: the disc and glyph render at their final state
 * and the ripples stay hidden, so the reader sees a settled success mark, not a blank box.
 */

import { motion, useReducedMotion } from "motion/react";
import type { ComponentPropsWithoutRef } from "react";
import clsx from "clsx";

type SuccessRippleProps = ComponentPropsWithoutRef<"div"> & {
  variant?: "success" | "error";
  /** Accessible name when the mark is not decorative. Pass `aria-hidden` to silence it. */
  label?: string;
  /** Overrides the default responsive box size (see the class note above). */
  sizeClassName?: string;
};

/** The ripple rings, by the delay each starts at — staggered so they read as a pulse. */
const RIPPLE_DELAYS = [0, 0.18];

export function SuccessRipple({
  variant = "success",
  label,
  sizeClassName = "h-32 w-32 sm:h-48 sm:w-48",
  className,
  ...rest
}: SuccessRippleProps) {
  const reduced = useReducedMotion();
  const isError = variant === "error";

  const disc = isError ? "#dc2626" : "var(--brand)";
  const ripple = isError ? "#dc2626" : "var(--brand-bright)";
  // Scale around each element's own centre — the SVG2 CSS-transform way, so framer's scale
  // does not pivot on the viewBox origin.
  const spin = { transformBox: "fill-box", transformOrigin: "center" } as const;

  return (
    <div
      role="img"
      aria-label={label ?? (isError ? "Error" : "Success")}
      className={clsx("relative grid place-items-center", sizeClassName, className)}
      {...rest}
    >
      <svg viewBox="0 0 100 100" className="h-full w-full" aria-hidden focusable="false">
        {RIPPLE_DELAYS.map((delay, index) => (
          <motion.circle
            key={index}
            cx={50}
            cy={50}
            r={30}
            fill="none"
            stroke={ripple}
            strokeWidth={2}
            style={spin}
            initial={{ scale: 0.6, opacity: reduced ? 0 : 0.7 }}
            animate={reduced ? { opacity: 0 } : { scale: 1.75, opacity: 0 }}
            transition={{ duration: reduced ? 0 : 1.1, delay: reduced ? 0 : delay, ease: "easeOut" }}
          />
        ))}

        <motion.circle
          cx={50}
          cy={50}
          r={30}
          fill={disc}
          style={spin}
          initial={reduced ? false : { scale: 0 }}
          animate={{ scale: 1 }}
          transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 260, damping: 18, delay: 0.05 }}
        />

        {isError ? (
          <>
            <motion.path
              d="M40 40 L60 60"
              fill="none"
              stroke="#ffffff"
              strokeWidth={5}
              strokeLinecap="round"
              initial={reduced ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={reduced ? { duration: 0 } : { duration: 0.3, delay: 0.25, ease: "easeOut" }}
            />
            <motion.path
              d="M60 40 L40 60"
              fill="none"
              stroke="#ffffff"
              strokeWidth={5}
              strokeLinecap="round"
              initial={reduced ? false : { pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={reduced ? { duration: 0 } : { duration: 0.3, delay: 0.4, ease: "easeOut" }}
            />
          </>
        ) : (
          <motion.path
            d="M37 51 L46 61 L64 40"
            fill="none"
            stroke="#ffffff"
            strokeWidth={5}
            strokeLinecap="round"
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={reduced ? { duration: 0 } : { duration: 0.35, delay: 0.28, ease: "easeOut" }}
          />
        )}
      </svg>
    </div>
  );
}
