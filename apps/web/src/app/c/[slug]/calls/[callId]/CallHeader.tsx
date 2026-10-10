"use client";

import { formatDuration, formatIST, formatPhone } from "@/components/ui";
import { CopyButton } from "@/components/interior/copy-button";
import { LiveDot } from "@/components/console/liveCalls";
import type { CallDetail } from "@/lib/api/client";
import { callTitle } from "@/lib/callReview";

import { TestCallTag, isLive } from "../callColumns";

/**
 * WHO AND WHEN — the call's identity, and nothing else.
 *
 * The title is the lead's name when the call has one and the number otherwise. The
 * number is printed in full (D-436) and is TEXT, never an `href` (hard rule 6). How the
 * call ended is the verdict below, not a chip up here: one statement of the outcome on
 * the screen, in one place.
 */
export function CallHeader({ detail }: { detail: CallDetail }) {
  const named = Boolean(detail.lead_name?.trim());
  const facts = [
    detail.direction === "outbound" ? "Outgoing" : "Incoming",
    formatIST(detail.started_at),
    detail.duration_s == null ? null : formatDuration(detail.duration_s),
    detail.agent_name ?? null,
  ].filter((fact): fact is string => Boolean(fact));
  return (
    <header>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {isLive(detail) && <LiveDot />}
        <p className={`min-w-0 break-words text-title text-ink ${named ? "" : "tabular-nums"}`}>
          {callTitle(detail)}
        </p>
        {!named && detail.caller_e164 && <CopyButton value={detail.caller_e164} label="Copy phone number" />}
        {detail.test_call && <TestCallTag />}
      </div>
      {named && detail.caller_e164 && (
        <p className="mt-1 flex items-center gap-1 text-meta tabular-nums text-ink-muted">
          {formatPhone(detail.caller_e164)}
          <CopyButton value={detail.caller_e164} label="Copy phone number" />
        </p>
      )}
      {/* One line of text, so it wraps between words rather than leaving a separator at
          the start of a line. */}
      <p className="mt-0.5 text-meta tabular-nums text-ink-muted">{facts.join(" · ")}</p>
    </header>
  );
}
