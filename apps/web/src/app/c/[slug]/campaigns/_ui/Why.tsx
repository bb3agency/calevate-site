"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * "Why?" — the reason behind a short line, shown only when asked for.
 *
 * Campaign screens say each problem in one short line with the button that fixes it; the
 * longer reason a reader wants once is here. Spans only, so it can sit inside a checklist
 * row's detail line or a `<p>` without breaking the HTML. Never put the ONLY statement of
 * a compliance fact in here: the short line must already be true on its own.
 */
export function Why({ children, label = "Why?" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="inline">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((was) => !was)}
        className="press -mx-1 inline-flex min-h-8 items-center gap-0.5 rounded-md px-1 text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        {label}
        <ChevronDown
          aria-hidden
          className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open ? (
        <span id={id} className="mt-1 block max-w-prose text-meta text-ink-muted [text-wrap:pretty]">
          {children}
        </span>
      ) : null}
    </span>
  );
}
