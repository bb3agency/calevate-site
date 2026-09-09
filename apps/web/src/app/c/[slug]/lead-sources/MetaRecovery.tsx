"use client";

import { RotateCcw } from "lucide-react";

import {
  NOTICE_TONES,
  ProblemNotice,
  SECONDARY_BUTTON_SM,
  Skeleton,
  formatCount,
} from "@/components/ui";
import { useIngestActivity, useMetaRedrive } from "@/lib/api/leadSources";

/**
 * The other half of the re-drive: an affordance for it.
 *
 * A route with no button is the half-wired feature `tests/crm_egress_known_gaps_test.py`
 * refused to accept, and the reason that gap stayed open through a whole slice. What a
 * client needs before pressing anything is the COUNT — how many of their leads are
 * sitting unread — and that comes from the activity view's server-derived `recoverable`
 * flag rather than from this file re-deciding what a recoverable reason is.
 *
 * §52, and the loading state is the one that matters here: "0 leads waiting" printed
 * while the activity query is still in flight tells someone their leads are fine when we
 * have not looked yet. So loading is a skeleton, a failed read is a refusal with a retry,
 * and a zero is only ever printed against an answer we actually received.
 */
export function MetaRecovery({
  sourceId,
  activity,
  redrive,
  canWrite,
}: {
  sourceId: string;
  activity: ReturnType<typeof useIngestActivity>;
  redrive: ReturnType<typeof useMetaRedrive>;
  canWrite: boolean;
}) {
  // Nothing to say until a source is picked: the count and the button are both about ONE
  // lead source, and a total across an account would offer to recover leads belonging to
  // a Page the person is not looking at.
  if (!sourceId) return null;

  const waiting = activity.data?.items.filter(
    (item) => item.lead_source_id === sourceId && item.recoverable,
  );
  const result = redrive.data;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <p className="text-sm font-medium text-ink">Leads we recorded but could not read</p>
      <p className="mt-1 text-sm text-ink-muted">
        If a lead arrived before your Page access token was in place, we kept it against
        its Meta lead ID but could not fetch what the person typed. Meta stops resending
        after about a day and a half; this fetches them now. Each one goes through the
        same checks a live lead does — including whether you may call them.
      </p>

      {activity.error != null ? (
        <div className="mt-3">
          <ProblemNotice error={activity.error} onRetry={() => activity.refetch()} />
        </div>
      ) : activity.isLoading || !waiting ? (
        <div className="mt-3">
          <Skeleton rows={1} />
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            disabled={!canWrite || redrive.isPending || waiting.length === 0}
            onClick={() => redrive.mutate(sourceId)}
            className={SECONDARY_BUTTON_SM}
          >
            <RotateCcw className="h-4 w-4" />
            {redrive.isPending ? "Recovering…" : "Recover unread leads"}
          </button>
          <span className="text-xs text-ink-faint">
            {waiting.length === 0
              ? "Nothing is waiting for this source."
              : `${formatCount(waiting.length)} ${waiting.length === 1 ? "lead is" : "leads are"} waiting.`}
          </span>
        </div>
      )}

      {redrive.error != null && (
        <div className="mt-3">
          <ProblemNotice error={redrive.error} />
        </div>
      )}
      {result && (
        <div className={`mt-3 rounded-lg border p-3 text-sm ${NOTICE_TONES.ok}`}>
          <p className="font-medium">
            {formatCount(result.accepted)} of {formatCount(result.candidates)} recovered.
          </p>
          <p className="mt-1">
            {/* Every non-accepted bucket is named, because a run that recovered 2 of 5 and
                said only "2 recovered" is the shape that makes someone press again and
                again. `deferred` is the one with an action attached, so it says so. */}
            {result.refused > 0 &&
              `${formatCount(result.refused)} could not be used — see the reason on each row below. `}
            {result.duplicate > 0 &&
              `${formatCount(result.duplicate)} had already landed. `}
            {result.deferred > 0
              ? `${formatCount(result.deferred)} could not be fetched just now — Meta was unreachable, and they are still waiting, so try again shortly.`
              : "Anything recovered appears in your leads, and was called only if your rules allowed it."}
          </p>
        </div>
      )}
    </div>
  );
}
