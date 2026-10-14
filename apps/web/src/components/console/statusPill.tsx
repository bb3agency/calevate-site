import type { ReactNode } from "react";

import type { NoticeTone } from "@/components/ui";

import { StatusPillShell } from "./statusPillShell";

/** The status dot per tone: chart fills, a mark beside words, so not held to 4.5:1. */
export const NOTICE_DOT: Record<NoticeTone, string> = {
  ok: "bg-brand",
  warn: "bg-chart-warn",
  stop: "bg-chart-danger",
  neutral: "bg-chart-neutral",
};

/** The word's ink per tone. Only a refusal is coloured; the dot carries every other tone. */
const WORD_TONES: Record<NoticeTone, string> = {
  ok: "text-ink",
  warn: "text-ink",
  stop: "text-danger",
  neutral: "text-ink-muted",
};

/**
 * THE ONE STATE MARK, in both consoles and the marketing mockups: "Live", "Paused",
 * "Not connected". A 6px tone dot and the word, with no fill, no border and no capsule (D-771).
 *
 * We do not use a tinted capsule because a row of them made every state equally loud, and a
 * capsule reads as a button. The founder rejected the look on the trial chip (14 Oct 2026).
 * Colour is never the only signal: the word is the state, and the dot is a mark beside it,
 * like `NOTICE_BAR`, so the dot is not held to a text contrast ratio.
 *
 * Use it for a STATE. A tag that is not a state ("Test call", "Google Sheet") is plain
 * `text-meta text-ink-muted` text. Show a state only when it says something.
 */
export function StatusPill({
  tone = "neutral",
  wrap = false,
  size = "meta",
  children,
  className = "",
}: {
  tone?: NoticeTone;
  /** Let a phrase wrap instead of overflowing a narrow row (a setting's state at 320px). */
  wrap?: boolean;
  /** `mini` is the marketing mockups' scaled-down console, nothing else. */
  size?: "meta" | "mini";
  children: ReactNode;
  className?: string;
}) {
  const word = typeof children === "string" || typeof children === "number" ? String(children) : "";
  return (
    <StatusPillShell
      tone={tone}
      state={`${tone}\u0000${word}`}
      className={`inline-flex items-center font-medium ${size === "mini" ? "gap-1 text-[11px] leading-4" : "gap-1.5 text-meta"} ${wrap ? "min-w-0 max-w-full [overflow-wrap:anywhere]" : "shrink-0 whitespace-nowrap"} ${WORD_TONES[tone]} ${className}`}
    >
      <span aria-hidden className={`size-1.5 shrink-0 rounded-full ${NOTICE_DOT[tone]}`} />
      {children}
    </StatusPillShell>
  );
}

/**
 * A status control in the top bar (live calls, credit, trial): text with a quiet hover
 * ground, with no border and no capsule, so it sits beside the bell as text rather than as a
 * row of buttons.
 */
export const BAR_STATUS =
  "press inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-2.5 text-meta font-medium hover:bg-ink/[0.04] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 touch:h-11";
