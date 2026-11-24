"use client";

import clsx from "clsx";
import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

/**
 * Pip's working view is one thread: every row hangs off a thin line on the left, with its
 * glyph on the line, so thinking, lookups, a script being written and the decision waiting
 * at the end read as one sequence rather than a stack of cards.
 *
 * The line is drawn by each row's `::before` down to the next row and hidden on the last,
 * so a list that grows mid-run never shows a dangling tail.
 */
export function TimelineList({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <ol aria-label={label} className={clsx("space-y-2", className)}>
      {children}
    </ol>
  );
}

export function TimelineRow({
  icon,
  children,
  arrived = false,
  as: Tag = "li",
}: {
  /** The row's glyph, 14px, already `aria-hidden`. */
  icon: ReactNode;
  children: ReactNode;
  /** Fade in once: the row arrived while the person watched (no movement under reduced motion). */
  arrived?: boolean;
  as?: "li" | "div";
}) {
  return (
    <Tag
      className={clsx(
        "relative min-w-0 pl-7",
        // A standalone row (`div`) closes a thread rather than continuing one: no line below it.
        Tag === "li" &&
          "before:absolute before:top-6 before:bottom-[-0.625rem] before:left-[0.6875rem] before:w-px before:bg-ink/15 last:before:hidden touch:before:top-[2.0625rem] touch:before:bottom-[-1.1875rem]",
        arrived && "live-enter",
      )}
    >
      {/* On a touch screen a row's head is 44px tall, so the glyph moves down to its middle. */}
      <span
        className={clsx(
          "absolute top-0.5 left-0 flex h-[1.375rem] w-[1.375rem] items-center justify-center rounded-full border border-line bg-surface text-ink-muted",
          Tag === "li" && "touch:top-[0.6875rem]",
        )}
      >
        {icon}
      </span>
      {children}
    </Tag>
  );
}

/**
 * A row's one-line head: what happened, how long it took, and a chevron when there is more
 * to read. Open state is the person's once they have touched it; until then it follows
 * `defaultOpen`, which is how a live lookup's results open as they arrive.
 */
export function RowHead({
  label,
  trailing,
  body,
  defaultOpen = false,
  title,
}: {
  label: ReactNode;
  /** Right-aligned and quiet: a duration. Not announced (`aria-hidden`), the label is. */
  trailing?: ReactNode;
  /** What opening the row shows; null for a row with nothing more to read. */
  body: ReactNode | null;
  defaultOpen?: boolean;
  title?: string;
}) {
  const [touched, setTouched] = useState<boolean | null>(null);
  const open = body !== null && (touched ?? defaultOpen);
  const bodyId = useId();
  const head = (
    <>
      <span className="min-w-0 flex-1 break-words">{label}</span>
      {trailing ? (
        <span aria-hidden className="shrink-0 tabular-nums text-ink-faint">
          {trailing}
        </span>
      ) : null}
    </>
  );
  return (
    <div className="text-meta" title={title}>
      {body === null ? (
        <div className="flex min-h-[1.625rem] items-center gap-2 text-ink touch:min-h-11">{head}</div>
      ) : (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setTouched(!open)}
          className="press flex min-h-[1.625rem] w-full items-center gap-2 rounded-sm text-left text-ink hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
        >
          {head}
          <ChevronRight
            aria-hidden
            className={clsx(
              "h-3.5 w-3.5 shrink-0 text-ink-faint motion-safe:transition-transform motion-safe:duration-(--duration-fast)",
              open && "rotate-90",
            )}
          />
        </button>
      )}
      {open ? (
        <div id={bodyId} className="mt-1 mb-1 text-ink-muted">
          {body}
        </div>
      ) : null}
    </div>
  );
}
