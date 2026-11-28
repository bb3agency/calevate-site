"use client";

import { useActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { SegmentedControl } from "@/components/interior/segmented-control";
import {
  useDailySummary,
  useSetDailySummary,
  type DailySummarySetting,
  type DailySummarySlot,
} from "@/lib/api/proof";
import { useClientSession } from "@/lib/api/session";

/**
 * THE OWNER'S DAILY SUMMARY (D-944): one switch. Off until the owner turns it on. Each
 * evening (the day so far) or, if the owner picks it, each morning (the day before, D-1048)
 * it sends calls, leads, spend and waiting call-backs by email, and by
 * WhatsApp where the owner turned WhatsApp alerts on above. Only the owner may change it
 * (`org:manage`); everyone can see it.
 */
export function DailySummary() {
  const session = useClientSession();
  const state = useDailySummary(session);
  const save = useSetDailySummary(session);
  // The switch itself shows the new state; a refusal is drawn beside it.
  const saveFeedback = useActionFeedback(save, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "turn the daily summary on or off");

  return (
    <Section title="Daily summary" description="Your day on the phones, once a day.">
      <RestrictionNote reason={write.reason} />
      {state.error ? (
        <ProblemNotice error={state.error} onRetry={() => void state.refetch()} />
      ) : !state.data ? (
        <Skeleton rows={2} label="Checking your daily summary" />
      ) : (
        <div className="space-y-2 border-y border-line py-4">
          {save.error != null && <ProblemNotice error={save.error} />}
          <ToggleSwitch
            label="Send me a daily summary"
            hint={channels(state.data)}
            checked={state.data.enabled}
            disabled={!write.allowed || save.isPending}
            onChange={(next) => saveFeedback.run(next)}
          />
          {state.data.enabled ? (
            <SegmentedControl
              label="When the daily summary comes"
              options={SLOTS}
              value={state.data.slot}
              onValueChange={(slot) => saveFeedback.run({ enabled: true, slot: slot as DailySummarySlot })}
              className="ml-12"
            />
          ) : null}
        </div>
      )}
    </Section>
  );
}

const SLOTS = [
  { value: "evening", label: "Evening, 9 pm" },
  { value: "morning", label: "Morning, 8 am" },
];

function channels(data: DailySummarySetting): string {
  const email = data.email_addresses > 0 ? "By email" : "No email address on file";
  const when = data.slot === "morning" ? "around 8 am, for the day before" : "around 9 pm";
  return `${email}${data.whatsapp ? " and WhatsApp" : ""}, ${when}. Nothing on a quiet day.`;
}
