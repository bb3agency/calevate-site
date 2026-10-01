"use client";

// Adapted from interior.dev (github.com/ddoemonn/interior @3148000), MIT License,
// Copyright (c) 2026 ozzy. Full notice: ./LICENSE.
//
// Changes from upstream: an icon-only variant for dense rows and headers; the accessible
// name names WHAT is copied ("Copy phone number") rather than a bare "Copy", which in a
// list of rows is a dozen identical names; the polite live region sits beside the button
// instead of inside it, where announcements are unreliable once `aria-label` overrides
// the button's name; press feedback is the repo's `press` utility; repo tokens.

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

const EASE = [0.23, 1, 0.32, 1] as const;
const FADE = { duration: 0.16, ease: EASE } as const;
const DRAW = { duration: 0.26, ease: EASE } as const;
const INSTANT = { duration: 0 } as const;

export type CopyStatus = "idle" | "copied" | "error";

function writeFallback(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.top = "0";
  area.style.left = "0";
  area.style.opacity = "0";
  document.body.appendChild(area);
  const selection = document.getSelection();
  const previous = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
  area.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  if (selection && previous) {
    selection.removeAllRanges();
    selection.addRange(previous);
  }
  return ok;
}

/**
 * The one clipboard path in the console. `navigator.clipboard` first; the deprecated
 * `execCommand` route only where the async API is missing or refused (an insecure
 * origin, or an older WebView).
 */
export function useCopyToClipboard({ timeout = 2000 }: { timeout?: number } = {}) {
  const [status, setStatus] = useState<CopyStatus>("idle");
  const [ticket, setTicket] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const copy = useCallback(async (text: string) => {
    if (!text) return false;
    let ok = false;
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        ok = true;
      } else {
        ok = writeFallback(text);
      }
    } catch {
      try {
        ok = writeFallback(text);
      } catch {
        ok = false;
      }
    }
    if (!mounted.current) return ok;
    setStatus(ok ? "copied" : "error");
    setTicket((t) => t + 1);
    return ok;
  }, []);

  useEffect(() => {
    if (ticket === 0 || status === "idle") return;
    const id = setTimeout(() => setStatus("idle"), timeout);
    return () => clearTimeout(id);
  }, [ticket, status, timeout]);

  return { copy, status };
}

export type CopyButtonProps = {
  value: string;
  /** Names the thing: "Copy phone number". Also the visible text in the `text` variant. */
  label: string;
  copiedLabel?: string;
  errorLabel?: string;
  variant?: "icon" | "text";
  disabled?: boolean;
  className?: string;
};

export function CopyButton({
  value,
  label,
  copiedLabel = "Copied",
  errorLabel = "Could not copy",
  variant = "icon",
  disabled = false,
  className = "",
}: CopyButtonProps) {
  const { copy, status } = useCopyToClipboard();
  const reduced = useReducedMotion();
  const fade = reduced ? INSTANT : FADE;
  const draw = reduced ? INSTANT : DRAW;
  const icon = (shown: CopyStatus) => ({
    initial: false as const,
    animate: { opacity: status === shown ? 1 : 0, scale: status === shown ? 1 : 0.8 },
    transition: fade,
  });

  const glyph = (
    <span className="grid size-[14px] shrink-0" aria-hidden="true">
      <motion.svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" className="col-start-1 row-start-1 size-[14px]" {...icon("idle")}>
        <path d="M9.6 5.1V3.7A1.7 1.7 0 0 0 7.9 2H3.7A1.7 1.7 0 0 0 2 3.7v4.2a1.7 1.7 0 0 0 1.7 1.7h1.4" />
        <rect x="5.1" y="5.1" width="6.9" height="6.9" rx="1.7" />
      </motion.svg>
      <motion.svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className="col-start-1 row-start-1 size-[14px] text-brand-strong" {...icon("copied")}>
        <motion.path d="M2.9 7.4 5.6 10.1 11.1 4" initial={false} animate={{ pathLength: status === "copied" ? 1 : 0 }} transition={draw} />
      </motion.svg>
      <motion.svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" className="col-start-1 row-start-1 size-[14px] text-danger" {...icon("error")}>
        <path d="M3.6 3.6 10.4 10.4" />
        <path d="M10.4 3.6 3.6 10.4" />
      </motion.svg>
    </span>
  );

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        aria-label={label}
        title={variant === "icon" ? label : undefined}
        onClick={() => void copy(value)}
        style={{ touchAction: "manipulation" }}
        className={
          variant === "icon"
            ? `press inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-faint hover:bg-ink/[0.06] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:h-11 touch:w-11 ${className}`
            : `press inline-flex h-8 items-center gap-2 rounded-md border border-line bg-surface px-3 text-[13px] font-medium text-ink-muted hover:bg-ink/[0.04] hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-50 touch:min-h-11 ${className}`
        }
      >
        {glyph}
        {variant === "text" && (
          <span aria-hidden="true">
            {status === "copied" ? copiedLabel : status === "error" ? errorLabel : label}
          </span>
        )}
      </button>
      <span aria-live="polite" className="sr-only">
        {status === "copied" ? copiedLabel : status === "error" ? errorLabel : ""}
      </span>
    </>
  );
}
