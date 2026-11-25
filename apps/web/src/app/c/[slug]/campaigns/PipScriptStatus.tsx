"use client";

/**
 * Pip's campaign script while it is written, and when it could not be (D-992).
 *
 * Writing: how long it has been, against how long it usually takes, and Stop. Failed: what
 * went wrong, picked by the server's `reason`, its own sentence beneath, and the one move
 * that helps, which is nearly always Try again (a failed draft is replaced by the next
 * request, so there is nothing to dismiss first). An allowance that is used up or paused
 * cannot be retried from here, so it points to the AI allowance page instead.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { NoticeBox, PRIMARY_BUTTON_SM, ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { ApiProblem } from "@/lib/api/client";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

/** What these read of a Pip draft: a campaign's script or the company training. */
type PipDraft = { status: string; requested_at: string; reason?: string | null; note?: string | null };

/** Reasons a retry cannot cure: the account's allowance, not Pip's answer. */
const ALLOWANCE_REASONS = new Set(["ai_quota_exceeded", "ai_quota_exhausted", "ai_paused_platform_wide"]);

const TITLES: Record<string, string> = {
  assist_answer_unusable: "Pip could not write a clean script",
  provider_unavailable: "Pip's AI did not answer",
  crashed: "Pip stopped before it finished",
  stale: "Pip stopped before it finished",
  ai_quota_exceeded: "Your AI allowance is used up",
  ai_quota_exhausted: "Your AI allowance is used up",
  ai_paused_platform_wide: "AI help is paused for now",
};

export function failedTitle(reason: string | null | undefined, what = "the script"): string {
  return lookup(TITLES, reason) ?? `Pip could not write ${what}`;
}

export function retryable(reason: string | null | undefined): boolean {
  return !reason || !ALLOWANCE_REASONS.has(reason);
}

/**
 * Generate refused before Pip started. An allowance that is used up or paused gets its own
 * title and the page that can change it, as a failed draft does; anything else is the
 * server's own words with Try again.
 */
export function PipAskRefused({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { session, href } = useClientRealm();
  if (error instanceof ApiProblem && ALLOWANCE_REASONS.has(error.code)) {
    return (
      <NoticeBox tone="warn" role="alert" title={failedTitle(error.code)}>
        <p className="mt-1 max-w-prose text-meta text-ink">Pip needs AI allowance to write the script.</p>
        <Link className={`${PRIMARY_BUTTON_SM} mt-3`} href={href(`/c/${session.orgSlug}/ai-assist`)}>
          See AI allowance
        </Link>
      </NoticeBox>
    );
  }
  return <ProblemNotice error={error} onRetry={onRetry} />;
}

/** "0:42": minutes and seconds since `since`, never negative. */
export function elapsed(since: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - new Date(since).getTime()) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function PipWriting({
  proposal,
  stopping,
  onStop,
  what = "the script",
}: {
  proposal: PipDraft;
  stopping: boolean;
  onStop: () => void;
  /** What Pip is writing, as the sentence names it. */
  what?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(tick);
  }, []);
  return (
    <div className="flex flex-wrap items-center gap-3 border-y border-line py-4">
      <span className="h-3 w-3 shrink-0 animate-pulse rounded-full bg-brand motion-reduce:animate-none" aria-hidden />
      <div className="min-w-0">
        <p role="status" className="text-body text-ink">
          Pip is writing {what}.
        </p>
        <p className="text-meta text-ink-muted">
          <span className="tabular-nums" aria-hidden>
            {elapsed(proposal.requested_at, now)}
          </span>{" "}
          · usually about a minute
        </p>
      </div>
      <button type="button" className={`${SECONDARY_BUTTON_SM} ml-auto`} disabled={stopping} onClick={onStop}>
        {stopping ? "Stopping…" : "Stop"}
      </button>
    </div>
  );
}

export function PipFailed({
  proposal,
  canWrite,
  retrying,
  dismissing,
  onRetry,
  onDismiss,
  what = "the script",
}: {
  proposal: PipDraft;
  what?: string;
  canWrite: boolean;
  retrying: boolean;
  dismissing: boolean;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const { session, href } = useClientRealm();
  const again = retryable(proposal.reason);
  return (
    <NoticeBox tone="warn" role="alert" title={failedTitle(proposal.reason, what)}>
      {proposal.note && <p className="mt-1 max-w-prose text-meta text-ink">{proposal.note}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {again ? (
          <button
            type="button"
            className={PRIMARY_BUTTON_SM}
            disabled={!canWrite || retrying || dismissing}
            onClick={onRetry}
          >
            {retrying ? "Starting…" : "Try again"}
          </button>
        ) : (
          <Link className={PRIMARY_BUTTON_SM} href={href(`/c/${session.orgSlug}/ai-assist`)}>
            See AI allowance
          </Link>
        )}
        <button
          type="button"
          className={SECONDARY_BUTTON_SM}
          disabled={!canWrite || retrying || dismissing}
          onClick={onDismiss}
        >
          {dismissing ? "Dismissing…" : "Dismiss"}
        </button>
      </div>
    </NoticeBox>
  );
}
