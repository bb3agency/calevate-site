"use client";

import type { ReactNode } from "react";

import { formatDuration, formatIST, formatPhone } from "@/components/ui";
import { CopyButton } from "@/components/interior/copy-button";
import { LiveDot } from "@/components/console/liveCalls";
import type { CallDetail } from "@/lib/api/client";
import { callTitle } from "@/lib/callReview";

import { FollowUpMark, TestCallTag, isLive } from "../callColumns";

/**
 * WHO AND WHEN — the call's identity, and nothing else.
 *
 * The title is the lead's name when the call has one and the number otherwise. The
 * number is printed in full (D-436) and is TEXT, never an `href` (hard rule 6). How the
 * call ended is the verdict below, not a chip up here: one statement of the outcome on
 * the screen, in one place.
 */
export function CallHeader({ detail, actions }: { detail: CallDetail; actions?: ReactNode }) {
  const named = Boolean(detail.lead_name?.trim());
  const facts = [
    detail.direction === "outbound" ? "Outgoing" : "Incoming",
    formatIST(detail.started_at),
    detail.duration_s == null ? null : formatDuration(detail.duration_s),
    detail.agent_name ?? null,
  ].filter((fact): fact is string => Boolean(fact));
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0 flex-1 basis-64">
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
      {/* Chips rather than a dotted sentence: each fact wraps whole, and a phone scans
          them without parsing separators. */}
      <ul aria-label="About this call" className="mt-1.5 flex flex-wrap gap-1.5">
        {facts.map((fact) => (
          <li key={fact} className="rounded-md bg-surface-muted px-2 py-0.5 text-meta tabular-nums text-ink-muted">
            {fact}
          </li>
        ))}
      </ul>
      {/* A person's mark (D-869), apart from how the call ended. */}
      {detail.follow_up_state ? (
        <p className="mt-1">
          <FollowUpMark state={detail.follow_up_state} />
        </p>
      ) : null}
      {/* D-746: a forwarded call that showed your own number, and our forwarding test. */}
      {detail.caller_id_hidden && (
        <p className="mt-1 text-meta text-ink-muted">
          The network hid the caller&apos;s number, so your agent asked for one to call back on.
        </p>
      )}
      {detail.forwarding_test && (
        <p className="mt-1 text-meta text-ink-muted">This was a forwarding test call. It is not charged.</p>
      )}
      {/* D-855: a free-trial test call, rung to a number the owner typed. */}
      {detail.test_call && !detail.forwarding_test && (
        <p className="mt-1 text-meta text-ink-muted">
          A free-trial test call. Its minutes count towards your trial minutes.
        </p>
      )}
      {/* D-835: a whole-line forward put the caller through to a phone. */}
      {detail.forwarded_to_phone && (
        <p className="mt-1 text-meta text-ink-muted">
          This call was put through to your phone, so your agent did not take it. Forwarded calls are not
          recorded.
        </p>
      )}
      {/* D-842: a call that was waiting to be placed and never rang; the server's sentence. */}
      {detail.not_placed_reason && <p className="mt-1 text-meta text-ink-muted">{detail.not_placed_reason}</p>}
      </div>
      {actions ? <div className="max-w-full">{actions}</div> : null}
    </header>
  );
}
