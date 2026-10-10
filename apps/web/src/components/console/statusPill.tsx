import type { ReactNode } from "react";

import type { NoticeTone } from "@/components/ui";

const PILL_TONES: Record<NoticeTone, string> = {
  ok: "bg-brand-soft text-brand-deep dark:bg-brand-strong/20 dark:text-brand-bright",
  warn: "bg-warn-soft text-warn",
  stop: "bg-danger-soft text-danger",
  neutral: "bg-ink/[0.06] text-ink-muted",
};

/**
 * A short state beside a name, in both consoles: "Active", "Held", "Not connected".
 * Sentence case, a soft fill and no border, so a row of them reads as text with a tint
 * rather than a row of buttons. Colour is never the only signal: the word is the state.
 * Show one only when it says something; a healthy row carries none.
 */
export function StatusPill({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: NoticeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${PILL_TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
