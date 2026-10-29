"use client";

import { SECONDARY_BUTTON_SM, ProblemNotice } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { useWriteAccess } from "@/lib/api/hooks";
import { useDailySummary, useSetDailySummary } from "@/lib/api/proof";

/**
 * The daily summary, OFFERED (D-944): one line and one button on the home screen while the
 * owner has not turned it on. Off by default for every account, so nobody gets a message
 * they did not ask for; shown only to the owner, who may switch it, and gone once it is on.
 * Turning it off again is on Notification settings.
 */
export function DailySummaryOffer({ session }: { session: Session }) {
  const write = useWriteAccess(session, "org:manage", "turn the daily summary on");
  const state = useDailySummary(session, { enabled: write.allowed });
  const save = useSetDailySummary(session);
  if (!write.allowed) return null;
  if (state.isError) {
    return <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />;
  }
  // Still asking is not an answer, and an offer before it would be one to a switch already on.
  if (state.isPending || state.data.enabled) return null;
  return (
    <div className="space-y-2 border-y border-line py-4">
      <p className="text-body text-ink">Get a summary of each day, every evening.</p>
      {save.error != null && <ProblemNotice error={save.error} />}
      <button
        type="button"
        className={SECONDARY_BUTTON_SM}
        disabled={save.isPending}
        onClick={() => save.mutate(true)}
      >
        Send me a daily summary
      </button>
    </div>
  );
}
