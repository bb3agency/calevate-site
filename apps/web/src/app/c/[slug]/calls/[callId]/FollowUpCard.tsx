"use client";

import { PhoneForwarded, ShieldAlert } from "lucide-react";

import { Card, NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import type { useCallBack, useCallbackEligibility, useWriteAccess } from "@/lib/api/hooks";

/**
 * "Can this call be rung back, and may you do it?" — the one ACT this screen offers.
 *
 * Its own file because it is three answers in one slot: the server's eligibility verdict,
 * D-22's read-only refusal, and the compliance gate's 200-with-a-reason. Each has to reach
 * the person beside the button, and keeping them together is what stops the next edit
 * dropping one of them into a toast.
 */
export function FollowUpCard({
  eligibility,
  callback,
  write,
}: {
  eligibility: ReturnType<typeof useCallbackEligibility>;
  callback: ReturnType<typeof useCallBack>;
  write: ReturnType<typeof useWriteAccess>;
}) {
  return (
    <>
      {/* D-21 M2. Rendered whenever the API has an opinion — disabled WITH the reason
          rather than hidden, so "why can't I follow this up?" is answered on screen.
          The refusals are mostly protective (we have already followed up twice; the
          call is a fortnight old), and a client who cannot see them assumes a bug.

          The two branches below exist because the card was doing the thing it says it
          exists to prevent: `eligibility.data` is undefined while the read is in flight
          and again after it fails, so a 503 on `/callback-eligibility` deleted the whole
          card — no button, no reason, nothing to reload. §52: failure is a refusal, and
          nothing is not a refusal. */}
      {eligibility.isLoading && (
        <Card title="Follow up">
          <Skeleton rows={2} />
        </Card>
      )}
      {eligibility.error != null && (
        <Card title="Follow up">
          <ProblemNotice
            error={eligibility.error}
            onRetry={() => void eligibility.refetch()}
          />
          <p className="mt-3 text-sm text-ink-muted">
            We could not check whether this call can be followed up, so the button stays
            closed.
          </p>
        </Card>
      )}
      {eligibility.data && (
        <Card title="Follow up">
          {callback.data?.status === "queued" ? (
            <NoticeBox tone="ok" icon={<PhoneForwarded className="h-5 w-5" />}>
              Calling back now — follow-up #{callback.data.follow_up_number}. It will appear in
              your call log in a moment.
            </NoticeBox>
          ) : callback.data?.status === "blocked" ? (
            /* A refusal by the compliance gate comes back 200 with a reason, not as an
               error. Falling through to the enabled button rendered it as a no-op: the
               client presses "Call back", nothing visibly happens, and they press it
               again. The server has already recorded the answer against this call, so
               it says why instead of offering another attempt. */
            <NoticeBox tone="warn" icon={<ShieldAlert className="h-5 w-5" />}>
              {callback.data.blocked_reason ?? "This follow-up call was not allowed."}
              {callback.data.blocked_rule ? ` (${callback.data.blocked_rule})` : ""}
            </NoticeBox>
          ) : eligibility.data.eligible && write.allowed ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-muted">
                Our agent will call back and pick up where this conversation stopped.
              </p>
              <button
                type="button"
                disabled={callback.isPending}
                onClick={() => callback.mutate()}
                className="inline-flex items-center gap-2 rounded-md bg-brand-strong px-4 py-2 text-sm font-semibold text-white hover:bg-brand-deep disabled:cursor-not-allowed disabled:opacity-50"
              >
                <PhoneForwarded className="h-4 w-4" />
                {callback.isPending ? "Calling…" : "Call back with AI"}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Two different refusals, one presentation. The server's eligibility
                  reason ("we have already followed this up twice") and D-22's
                  read-only both end in the same dead button, and both belong NEXT to
                  it — the eligibility query exists so this button never answers with a
                  403, and the read-only sweep would have reintroduced exactly that. */}
              <p className="text-sm text-ink-muted">
                {eligibility.data.eligible
                  ? (write.reason ?? "Checking what you can do in this account…")
                  : eligibility.data.reason}
              </p>
              <button
                type="button"
                disabled
                className="inline-flex cursor-not-allowed items-center gap-2 rounded-md border border-line bg-surface px-4 py-2 text-sm font-semibold text-ink-faint"
              >
                <PhoneForwarded className="h-4 w-4" />
                Call back with AI
              </button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
