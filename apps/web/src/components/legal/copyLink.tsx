"use client";

import { Check, Link as LinkIcon } from "lucide-react";
import { useEffect, useState } from "react";

type Outcome = "idle" | "copied" | "failed";

/**
 * Copies a link to one clause. Clauses get cited ("Privacy §7.2") in emails and tickets,
 * and the anchor is otherwise only reachable by finding it in the contents.
 *
 * The address bar is updated whether or not the clipboard write succeeds: the Clipboard
 * API refuses outside a secure context or without permission, and in that case the link
 * is still one copy away rather than lost. The outcome is announced in words through a
 * status region, because an icon swap is invisible to a screen reader.
 */
export function CopyLinkButton({ id, heading }: { id: string; heading: string }) {
  const [outcome, setOutcome] = useState<Outcome>("idle");

  useEffect(() => {
    if (outcome === "idle") return;
    const timer = window.setTimeout(() => setOutcome("idle"), 1800);
    return () => window.clearTimeout(timer);
  }, [outcome]);

  async function copy() {
    const url = `${window.location.origin}${window.location.pathname}#${id}`;
    window.history.replaceState(null, "", `#${id}`);
    try {
      await navigator.clipboard.writeText(url);
      setOutcome("copied");
    } catch {
      setOutcome("failed");
    }
  }

  const copied = outcome === "copied";
  return (
    <>
      <button
        type="button"
        onClick={copy}
        aria-label={`Copy link to ${heading}`}
        className="press relative mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-faint hover:bg-brand-soft/60 hover:text-brand-strong focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-strong group-hover/heading:opacity-100 touch:h-11 touch:w-11 [@media(hover:hover)]:opacity-0 print:hidden"
      >
        <LinkIcon
          aria-hidden
          className={`absolute h-4 w-4 transition-[opacity,scale] duration-(--duration-fast) ease-out ${
            copied ? "scale-50 opacity-0" : "scale-100 opacity-100"
          }`}
        />
        <Check
          aria-hidden
          className={`absolute h-4 w-4 text-brand-strong transition-[opacity,scale] duration-(--duration-fast) ease-out ${
            copied ? "scale-100 opacity-100" : "scale-50 opacity-0"
          }`}
        />
      </button>
      <span role="status" className="sr-only">
        {outcome === "copied"
          ? "Link copied"
          : outcome === "failed"
            ? "Could not copy. The link is now in the address bar."
            : ""}
      </span>
    </>
  );
}
