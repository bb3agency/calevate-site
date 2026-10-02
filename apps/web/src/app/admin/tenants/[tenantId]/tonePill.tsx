import type { ReactNode } from "react";

import { NOTICE_TONES, type NoticeTone } from "@/components/ui";

/**
 * A state pill for a compliance sub-page header: one short fact, in the notice tones.
 *
 * The tones are `NOTICE_TONES` rather than a palette of its own, so a pill and the notice
 * box beneath it that explains the same state are the same colour in both themes.
 */
export function TonePill({ tone, children }: { tone: NoticeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${NOTICE_TONES[tone]}`}
    >
      {children}
    </span>
  );
}
