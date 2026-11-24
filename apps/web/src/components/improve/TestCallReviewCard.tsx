"use client";

/**
 * YOUR LATEST TEST CALL (founder, 24 Nov 2026): after the owner's test call, its review here,
 * from the same checks every call gets (`call_mistakes`, `calls.step_progress`) as the call
 * page shows them: the steps it reached and the mistakes found, with a link to the call.
 */

import Link from "next/link";

import { StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatIST } from "@/components/ui";
import { STEP_STATE } from "@/app/c/[slug]/calls/[callId]/CallStepsCard";
import { callMistakeFix } from "@/lib/api/callMistakes";
import { useCall } from "@/lib/api/hooks";
import { useHolderTestCalls, type Holder } from "@/lib/api/improve";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard } from "./ImproveCard";

export const TEST_REVIEW_TITLE = "Your latest test call";

/** Still on the line, or its checks not yet run. */
const STILL_ON = new Set(["queued", "ringing", "in_progress"]);

export function TestCallReviewCard({ slug, holder }: { slug: string; holder: Holder }) {
  const { session } = useClientRealm();
  const calls = useHolderTestCalls(session, holder);
  const latest = calls.data?.[0];
  return (
    <ImproveCard title={TEST_REVIEW_TITLE} hint="What the checks found on it.">
      {calls.isLoading ? (
        <Skeleton rows={2} label="Loading your test calls" />
      ) : !calls.data ? (
        <ProblemNotice error={calls.error} onRetry={() => void calls.refetch()} />
      ) : !latest ? (
        <p className="text-meta text-ink-muted">No test call yet. Call yourself to hear it first.</p>
      ) : STILL_ON.has(latest.status) ? (
        <p role="status" className="text-meta text-ink-muted">
          The call is still on. Its review shows here once it ends.
        </p>
      ) : (
        <Review slug={slug} callId={latest.call_id} placedAt={latest.placed_at} />
      )}
    </ImproveCard>
  );
}

function Review({ slug, callId, placedAt }: { slug: string; callId: string; placedAt: string }) {
  const { session, href } = useClientRealm();
  const call = useCall(session, callId);
  if (call.isLoading) return <Skeleton rows={2} label="Loading the test call's review" />;
  if (!call.data) return <ProblemNotice error={call.error} onRetry={() => void call.refetch()} />;
  const { steps, mistakes } = call.data;
  return (
    <div className="space-y-3">
      <p className="text-meta text-ink-muted">{formatIST(placedAt)}</p>
      {steps.length === 0 && mistakes.length === 0 ? (
        <p className="text-meta text-ink-muted">Not checked yet. Its review shows here soon.</p>
      ) : (
        <>
          {steps.length > 0 && (
            <ol className="space-y-1" aria-label="Steps on the test call">
              {steps.map((s) => {
                const shown = STEP_STATE[s.state];
                return (
                  <li key={s.step} className="flex items-center justify-between gap-3 text-meta">
                    <span className="min-w-0 text-ink [overflow-wrap:anywhere]">
                      <span className="text-ink-muted tabular-nums">{s.step}.</span> {s.name}
                    </span>
                    <StatusPill tone={shown.tone}>{shown.word}</StatusPill>
                  </li>
                );
              })}
            </ol>
          )}
          {mistakes.length === 0 ? (
            <p className="text-meta text-ink">No mistakes found.</p>
          ) : (
            <ul className="space-y-1" aria-label="Mistakes on the test call">
              {mistakes.map((m) => {
                const fix = callMistakeFix(m.fix);
                return (
                  <li key={`${m.kind}-${m.turn_idx}`} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-meta">
                    <span className="min-w-0 text-ink [overflow-wrap:anywhere]">{m.label}</span>
                    <StatusPill tone={fix.tone}>{fix.words}</StatusPill>
                  </li>
                );
              })}
            </ul>
          )}
        </>
      )}
      <Link href={href(`/c/${slug}/calls/${callId}`)} className={TEXT_ACTION}>
        Open the test call
      </Link>
    </div>
  );
}
