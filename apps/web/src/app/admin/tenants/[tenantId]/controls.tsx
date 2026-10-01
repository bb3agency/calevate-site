"use client";

import Link from "next/link";

/**
 * The small controls this screen's panels share — the header's nav pills, the three
 * button weights its dense rows use, and the field class those rows' inputs take.
 *
 * They are HERE rather than in `components/ui.tsx` because they are this screen's own
 * density (`text-xs`, `py-1`), not the console's: promoting them would put a second
 * button scale in the shared catalogue beside `PRIMARY_BUTTON` and friends, which is the
 * two-ways-of-one-thing defect UX-DOCTRINE §7 is about. If a third screen needs this
 * scale, that is the moment to hoist it and move both callers.
 */

/** The screen-to-screen affordances in the header, in one shape rather than four. */
export function NavLink({
  href,
  icon,
  title,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      title={title}
      className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-black/5 dark:hover:bg-white/5 touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-brand press"
    >
      {icon}
      {children}
    </Link>
  );
}

// `enabled:hover` rather than `hover`, so a disabled button does not darken under the
// pointer and read as live. Each weight adds its own ring colour.
const BUTTON_BASE =
  "inline-flex items-center justify-center rounded-md px-2.5 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 press";

export function PrimaryButton({
  children,
  disabled,
  onClick,
  type = "button",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type === "submit" ? "submit" : "button"}
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} bg-brand-strong text-white enabled:hover:bg-brand-deep focus-visible:ring-brand`}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} border border-line bg-surface text-ink enabled:hover:bg-black/5 dark:enabled:hover:bg-white/5 focus-visible:ring-brand`}
    >
      {children}
    </button>
  );
}

export function DangerButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`${BUTTON_BASE} border border-rose-300 text-rose-700 enabled:hover:bg-rose-50 dark:border-rose-900 dark:text-rose-300 dark:enabled:hover:bg-rose-950 focus-visible:ring-rose-600`}
    >
      {children}
    </button>
  );
}

/*
 * `min-w-0` because every one of these sits in a `flex flex-wrap` row. A flex item
 * defaults to `min-width: auto` and so refuses to shrink below its own min-content, and a
 * `<select>` s min-content is its LONGEST OPTION — "Not started — no application filed"
 * here, which is wider than a 320px phone. Wrapping does not save it: once wrapped the
 * item is alone on its line and still will not shrink. Measured at 320px this row reached
 * x=395 in a 320px viewport, inside the shell s `overflow-hidden`, so the control was
 * clipped off-screen rather than scrollable.
 */
export const FIELD =
  "min-w-0 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-50 touch:min-h-11 transition-[border-color] duration-(--duration-fast) ease-out focus:border-brand aria-[invalid=true]:border-rose-500";
