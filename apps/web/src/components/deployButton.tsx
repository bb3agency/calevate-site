"use client";

/**
 * A prominent pill CTA with a dot-panel that reveals on hover, keyboard focus, or a touch
 * press — adapted to the Calevate green from the "book a demo" sample.
 *
 * ## Why this is pure CSS and not framer-motion
 *
 * The reveal is a single `scale-x` transform driven by the button's own `:hover`,
 * `:focus-visible` and `:active` states through Tailwind's `group-*` variants. That is
 * deliberate rather than lazy: a CSS state transition is correct with no JavaScript, works
 * on the very first frame, and — because the reveal is bound to `group-active` too — a TAP
 * on a phone (where there is no hover) opens the panel and holds it for the press. A
 * framer-motion `whileHover` would not fire on touch and would leave the mobile CTA inert.
 * `motion-reduce:` (the `prefers-reduced-motion` variant Tailwind ships) freezes every
 * transition for a reader who asked for none, so the panel simply appears rather than
 * sliding.
 *
 * ## Why the revealed panel is a LIGHT green and the label flips DARK
 *
 * The sample revealed a bright panel and kept white text, which reads at roughly 2:1 —
 * below WCAG 1.4.3's 4.5:1 for a 14px label, and this repo holds text contrast as a gate
 * (`tests/contrastTokens.test.ts`, `tests/a11y.ts`). So the revealed state inverts
 * instead: a `--brand-soft` panel (a fixed light-green token that does NOT flip in dark
 * mode) with the label recoloured to `--brand-deep`, which clears AA comfortably in both
 * themes. The dots are dark green over that light panel, which is the sample's intent —
 * "dark dots for contrast on the green panel" — landing on the light panel that keeps the
 * text legible. The RESTING pill is a deep-green ground with white text, itself AA.
 *
 * Keeps `forwardRef`, spreads `...props` (so it is a real submit/click button), and lets a
 * caller override `className`. The label is the button's `children`.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";

/**
 * Two green-family shades, both resting dark with white text and both revealing the same
 * light panel — collapsed from the sample's colourful set to what the brand actually has.
 * `primary` is the deepest and is the default; `strong` sits one step brighter for a CTA
 * that shares a row with a `primary` one and should not read as the same button twice.
 */
export type DeployButtonVariant = "primary" | "strong";

const VARIANT_GROUND: Record<DeployButtonVariant, string> = {
  primary: "bg-brand-deep",
  strong: "bg-brand-strong",
};

/**
 * The dot texture, as a tiled radial-gradient rather than an image asset — the sample's
 * `master.png` overlay has no equivalent in this repo and an inline gradient needs no
 * network fetch and no CSP allowance. `--brand-deep` at half alpha reads as dark green
 * pips over the light `--brand-soft` panel; `color-mix` keeps it the BRAND token (so a
 * rebrand carries the dots with it) rather than a frozen hex — the same primitive Tailwind
 * v4 already uses for its `/opacity` modifiers, so it is available everywhere the console is.
 */
const DOT_TEXTURE =
  "radial-gradient(color-mix(in srgb, var(--brand-deep) 55%, transparent) 1.5px, transparent 1.6px)";

type DeployButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: DeployButtonVariant;
  children: ReactNode;
};

export const DeployButton = forwardRef<HTMLButtonElement, DeployButtonProps>(
  function DeployButton({ variant = "primary", className, children, type = "button", ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={clsx(
          // `isolate` gives the reveal its own stacking context so `-z-10` stays behind the
          // label without escaping the button. `overflow-hidden` clips the scaling panel to
          // the pill's rounded edge. `h-11` is the 44px touch target.
          "group relative isolate inline-flex h-11 items-center justify-center gap-2 overflow-hidden rounded-full px-6 text-sm font-semibold text-white shadow-sm",
          VARIANT_GROUND[variant],
          "transition-shadow duration-200 hover:shadow-md motion-reduce:transition-none",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app",
          "disabled:cursor-not-allowed disabled:opacity-60 disabled:shadow-sm",
          className,
        )}
        {...props}
      >
        {/* The dot-panel. Scales in from the left on hover / keyboard focus / touch press;
            `disabled:group-*` never triggers because a disabled button takes none of those
            states, so a dead button stays its resting ground. */}
        <span
          aria-hidden
          className="absolute inset-0 -z-10 origin-left scale-x-0 bg-brand-soft transition-transform duration-300 ease-out group-hover:scale-x-100 group-focus-visible:scale-x-100 group-active:scale-x-100 motion-reduce:transition-none motion-reduce:duration-0"
        >
          <span
            className="absolute inset-0 opacity-70"
            style={{ backgroundImage: DOT_TEXTURE, backgroundSize: "10px 10px" }}
          />
        </span>
        {/* The label sits above the panel and flips to the dark ink-green the light panel
            can carry at AA. `relative` lifts it out of the isolated `-z-10` layer. */}
        <span className="relative transition-colors duration-200 group-hover:text-brand-deep group-focus-visible:text-brand-deep group-active:text-brand-deep motion-reduce:transition-none">
          {children}
        </span>
      </button>
    );
  },
);
