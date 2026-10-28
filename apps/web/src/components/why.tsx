"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

/**
 * The explanation behind a tap: the short line stays on screen and the sentence that argues
 * it opens under a worded "Why?" / "Details" / "How it works" (buttons, not paragraphs).
 * The ⓘ (`InfoTip`) and the labelled popover stay for a tip beside a control; this is for
 * a reason under a line.
 *
 * Block form is a native `<details>`: the text stays in the document while closed, so
 * find-in-page and a screen reader still reach a money or compliance qualification, and
 * nothing is positioned on a phone. `<details>` is not allowed inside a `<p>` or a
 * checklist row's detail line, so `inline` renders spans and a button instead, and its text
 * exists only while open.
 *
 * Never put the ONLY statement of a compliance fact in here: the short line must already be
 * true on its own.
 */
export function Why({
  label = "Why?",
  children,
  className = "",
  inline = false,
}: {
  label?: string;
  children: ReactNode;
  className?: string;
  inline?: boolean;
}) {
  if (inline) return <InlineWhy label={label} className={className}>{children}</InlineWhy>;
  return (
    <details className={`group/why ${className}`}>
      <summary className={`${TRIGGER} [&::-webkit-details-marker]:hidden`}>
        {label}
        <ChevronDown
          aria-hidden
          className={`${CHEVRON} [details[open]>summary>&]:rotate-180`}
        />
      </summary>
      <div className={`${BODY} space-y-1`}>{children}</div>
    </details>
  );
}

function InlineWhy({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className={`inline ${className}`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((was) => !was)}
        className={TRIGGER}
      >
        {label}
        <ChevronDown aria-hidden className={`${CHEVRON} ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <span id={id} className={`block ${BODY}`}>
          {children}
        </span>
      ) : null}
    </span>
  );
}

const TRIGGER =
  "press -mx-1 inline-flex min-h-8 cursor-pointer list-none items-center gap-0.5 rounded-md px-1 " +
  "text-meta font-medium text-ink-muted hover:text-ink focus-visible:outline-none " +
  "focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11";
const CHEVRON =
  "h-3.5 w-3.5 transition-transform duration-(--duration-fast) motion-reduce:transition-none";
const BODY = "mt-1 max-w-prose text-meta text-ink-muted [text-wrap:pretty]";
