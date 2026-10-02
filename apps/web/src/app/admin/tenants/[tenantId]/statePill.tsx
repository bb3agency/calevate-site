import type { ReactNode } from "react";

import { NOTICE_TONES, type NoticeTone } from "@/components/ui";

/**
 * A one-word state beside a row's name: an agent's status, a flag's provenance, a pack that
 * went stale. The tones are the notice palette's, so a pill and the banner that explains it
 * are the same colour, and the word always carries the meaning (WCAG 1.4.1).
 */
export function StatePill({ tone = "neutral", children }: { tone?: NoticeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[12px] font-medium ${NOTICE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}

/** An agent's lifecycle status in the operator's palette: live is the healthy case. */
export const AGENT_STATUS_TONE: Record<string, NoticeTone> = {
  live: "ok",
  draft: "neutral",
  paused: "warn",
  archived: "neutral",
};
