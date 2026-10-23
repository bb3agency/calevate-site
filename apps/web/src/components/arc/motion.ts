/**
 * The kit's motion values for `motion/react`, which needs numbers rather than CSS variables.
 *
 * Shape adapted from uiarc's `arc-motion-tokens` (MIT, see ./LICENSE); the VALUES are
 * Calevate's, copied from `globals.css` so there is one motion scale, not Arc's beside ours:
 * `--duration-press` 140ms, `--duration-fast` 150ms, `--duration-base` 200ms,
 * `--duration-slow` 280ms, `--ease-out-strong`, `--ease-in-out-strong`, `--ease-drawer-curve`.
 * `tests/kit/motionTokens.test.ts` fails if the two drift.
 *
 * Arc's blur radii are not carried over: the kit does not blur-crossfade text (the
 * catalogue's "drop the blur crossfades that do not explain a state change").
 */
export const MOTION = {
  duration: { press: 0.14, fast: 0.15, base: 0.2, slow: 0.28 },
  ease: {
    out: [0.23, 1, 0.32, 1],
    inOut: [0.77, 0, 0.175, 1],
    drawer: [0.32, 0.72, 0, 1],
  },
  /** Springs never overshoot: a console control that bounces reads as unsure of its state. */
  spring: {
    snappy: { type: "spring", visualDuration: 0.22, bounce: 0 },
    smooth: { type: "spring", visualDuration: 0.32, bounce: 0 },
  },
} as const;

export const INSTANT = { duration: 0 } as const;
