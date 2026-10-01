"use client";

import type { ReactNode } from "react";
import { Info } from "lucide-react";

import { Popover, type PopoverAlign } from "@/components/interior/popover";

/**
 * THE ⓘ — where help prose goes when the line it explains stays on screen.
 *
 * A click (or tap, or Enter) opens it and it stays open until dismissed, which is the
 * "toggletip" shape rather than a hover tooltip: a hover-only tip is unreachable on a
 * phone and by keyboard, and it is the reader on a phone this console is built for
 * (UX-DOCTRINE §8.6). Focus moves into the panel so a screen reader reads it; Escape or
 * a press outside closes it.
 *
 * Never for a compliance sentence, an error or a refusal: those stay visible
 * (UX-DOCTRINE §3, §8.7). This is for explanation a reader can do without.
 */
export function InfoTip({
  label,
  children,
  align = "center",
  className = "",
}: {
  /** What the tip is about — the button reads "About <label>". */
  label: string;
  children: ReactNode;
  align?: PopoverAlign;
  className?: string;
}) {
  return (
    <Popover
      label={label}
      align={align}
      className="w-72 max-w-[calc(100vw-1rem)]"
      renderTrigger={(props, open) => (
        <button
          type="button"
          {...props}
          aria-label={`About ${label}`}
          className={`press inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full align-middle text-ink-faint hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:h-11 touch:w-11 ${
            open ? "bg-ink/[0.06] text-ink" : ""
          } ${className}`}
        >
          <Info aria-hidden className="h-4 w-4" />
        </button>
      )}
    >
      <div className="space-y-2 text-[13px] text-ink-muted">{children}</div>
    </Popover>
  );
}
