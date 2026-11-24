"use client";

/**
 * SMARTER RETRIES (D-992 item 8): a person who did not pick up is rung next at a different
 * time of day, inside the allowed hours and this campaign's own, never sooner than the gap
 * the campaign waits (`campaigns/call_timing.spread_retry_at`). The switch is its own undo.
 * The do-not-call list is checked again before every retry, as before every call.
 */

import { useActionFeedback } from "@/components/arc/feedback";
import { ToggleSwitch } from "@/components/ui";
import { useRetrySpread, type CampaignInsights } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, MoveError } from "./ImproveCard";

type Retry = CampaignInsights["retry"];

/** 30 → "30 minutes", 120 → "2 hours", 1440 → "1 day". */
export function gapWords(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? "1 day" : `${minutes / 1440} days`;
  if (minutes % 60 === 0) return minutes === 60 ? "1 hour" : `${minutes / 60} hours`;
  return `${minutes} minutes`;
}

export function RetrySpreadCard({
  campaignId,
  data,
  canWrite,
}: {
  campaignId: string;
  data: Retry;
  canWrite: boolean;
}) {
  const { session } = useClientRealm();
  const spread = useRetrySpread(session, campaignId);
  useActionFeedback(spread, {
    errorDisplay: "inline",
    successToast: (_, on) => (on ? "Retries now ring at other times of day" : "Retries ring after the gap"),
  });
  const retries = data.max_attempts - 1;
  return (
    <ImproveCard
      title="Call back at a better time"
      hint="Who did not pick up is rung again at another time of day."
      info="Each retry waits at least the gap you chose, then moves to another part of the day, inside the allowed hours and this campaign's own. The do-not-call list is checked again before every retry."
    >
      {retries < 1 ? (
        <p className="text-meta text-ink-muted">
          This campaign tries each person once. Add tries in How it calls.
        </p>
      ) : (
        <p className="mb-2 text-meta text-ink">
          Up to {data.max_attempts} tries, at least {data.gaps_minutes.map(gapWords).join(", then ")} apart.
        </p>
      )}
      <ToggleSwitch
        label="Ring each retry at another time of day"
        hint={
          data.spread
            ? "On. Someone busy at 10am is tried after noon, or the next morning."
            : "Off. Each retry rings once the gap has passed."
        }
        checked={data.spread}
        disabled={!canWrite || spread.isPending || retries < 1}
        onChange={(on) => spread.mutate(on)}
      />
      <MoveError error={spread.error} fallback="That did not save" />
    </ImproveCard>
  );
}
