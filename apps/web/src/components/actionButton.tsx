"use client";

/**
 * A primary button that shows an inline spinner while an async action runs — adapted to
 * the Calevate green from the "liquid gradient" sample, with its `master.png` sheen dropped
 * (there is no such asset here, and a strict CSP would block one anyway).
 *
 * ## The label stays mounted; only the spinner comes and goes
 *
 * The sample swapped label ⇄ spinner, which changes the button's ACCESSIBLE NAME every time
 * it starts working — a screen reader would stop being able to name the control mid-action,
 * and a test that finds the button by its name would lose it. So the label is always in the
 * DOM (it fades to transparent under `loading`) and the button's name never changes; the
 * spinner is the only thing `AnimatePresence` mounts and unmounts, and it is `aria-hidden`
 * with `aria-busy` on the button carrying the state to assistive tech. This is the swap the
 * sample asked for, done without the name flicker.
 *
 * ## Reduced motion and the spinner
 *
 * The ring is a CSS `animate-spin` frozen by `motion-reduce:animate-none`, so a reader who
 * asked for no motion gets a static ring rather than nothing. The fade that mounts it is
 * given a zero duration under `useReducedMotion`, so its appearance is instant too.
 *
 * Keeps `forwardRef`, spreads `...props` (real submit/click button), allows a `className`
 * and a `style` override, and disables itself while loading so a double-press cannot fire
 * the action twice. `h-11` is the 44px touch target.
 */

import { forwardRef, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion, type HTMLMotionProps } from "motion/react";
import clsx from "clsx";

/** A rotating ring, sized to sit inside the button. Pure CSS so it needs no measurement. */
function Spinner() {
  return (
    <span
      aria-hidden
      className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white motion-reduce:animate-none"
    />
  );
}

type ActionButtonProps = Omit<HTMLMotionProps<"button">, "children"> & {
  /** While true, the label fades out, the spinner shows, and the button is unpressable. */
  loading?: boolean;
  /** Overridden from the motion type: a plain node, since we render it inside a `<span>`
   *  (motion's own `children` admits a `MotionValue`, which is not a valid `ReactNode` there). */
  children?: ReactNode;
};

export const ActionButton = forwardRef<HTMLButtonElement, ActionButtonProps>(
  function ActionButton(
    { loading = false, disabled, className, style, children, type = "button", ...props },
    ref,
  ) {
    const reduced = useReducedMotion();

    return (
      <motion.button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        // The press feedback the sample carried, minus the PNG overlay — skipped entirely
        // for a reduced-motion reader and for a button that cannot be pressed.
        whileTap={reduced || disabled || loading ? undefined : { scale: 0.98 }}
        className={clsx(
          "relative inline-flex h-11 items-center justify-center gap-2 overflow-hidden rounded-md px-4 text-sm font-semibold text-white shadow-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong focus-visible:ring-offset-2 focus-visible:ring-offset-app",
          "disabled:cursor-not-allowed disabled:opacity-60",
          className,
        )}
        // OUR green, top-to-bottom — the sample's blue liquid gradient restated as brand
        // tokens so a rebrand flows through globals.css, not this file. Spread last so a
        // caller can still override.
        style={{
          backgroundImage: "linear-gradient(180deg, var(--brand-strong) 0%, var(--brand-deep) 100%)",
          ...style,
        }}
        {...props}
      >
        <span
          className={clsx(
            "inline-flex items-center gap-2 transition-opacity",
            loading && "opacity-0",
          )}
        >
          {children}
        </span>
        <AnimatePresence initial={false}>
          {loading && (
            <motion.span
              key="spinner"
              aria-hidden
              className="absolute inset-0 grid place-items-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduced ? 0 : 0.15 }}
            >
              <Spinner />
            </motion.span>
          )}
        </AnimatePresence>
      </motion.button>
    );
  },
);
