"use client";

import type { ReactNode } from "react";
import { CircleHelp } from "lucide-react";

import { Popover, type PopoverAlign } from "@/components/arc/popover";

/**
 * A worded "Why?" tap that opens the explanation behind a short line.
 *
 * `InfoTip` is the same toggletip behind a bare ⓘ. For the client screens rebuilt for
 * owners who read English as a second language, a word they can see beats an icon they
 * have to recognise, so this one carries its label ("Why?", "How this works"). Same
 * `Popover`, same rule as the ⓘ: never for a compliance sentence, an error or a refusal
 * (UX-DOCTRINE §3, §8.7). Only explanation a reader can do without goes behind it.
 */
export function WhyTip({
  label = "Why?",
  about,
  children,
  align = "start",
  className = "",
}: {
  /** The visible word on the button. */
  label?: string;
  /** What the explanation is about, for the panel's accessible name. */
  about: string;
  children: ReactNode;
  align?: PopoverAlign;
  className?: string;
}) {
  return (
    <Popover
      label={about}
      align={align}
      className="w-72"
      trigger={
        <button
          type="button"
          className={`press inline-flex min-h-11 items-center gap-1 rounded-md px-1.5 text-meta font-medium text-ink-muted hover:bg-ink/[0.05] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand data-[state=open]:bg-ink/[0.05] data-[state=open]:text-ink ${className}`}
        >
          <CircleHelp aria-hidden className="h-4 w-4 shrink-0" />
          {label}
        </button>
      }
    >
      <div className="space-y-2 text-[13px] text-ink-muted">{children}</div>
    </Popover>
  );
}
