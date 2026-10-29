"use client";

import { Section } from "@/components/console/section";
import { ProblemNotice, RestrictionNote, Skeleton, ToggleSwitch } from "@/components/ui";
import { useWriteAccess } from "@/lib/api/hooks";
import { useDailySummary, useSetDailySummary, type DailySummarySetting } from "@/lib/api/proof";
import { useClientSession } from "@/lib/api/session";

/**
 * THE OWNER'S DAILY SUMMARY (D-944): one switch. Off until the owner turns it on. Each
 * evening it sends the day's calls, leads, spend and waiting call-backs by email, and by
 * WhatsApp where the owner turned WhatsApp alerts on above. Only the owner may change it
 * (`org:manage`); everyone can see it.
 */
export function DailySummary() {
  const session = useClientSession();
  const state = useDailySummary(session);
  const save = useSetDailySummary(session);
  const write = useWriteAccess(session, "org:manage", "turn the daily summary on or off");

  return (
    <Section title="Daily summary" description="Your day on the phones, each evening.">
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
            onChange={(next) => save.mutate(next)}
          />
        </div>
      )}
    </Section>
  );
}

function channels(data: DailySummarySetting): string {
  const email = data.email_addresses > 0 ? "By email" : "No email address on file";
  return `${email}${data.whatsapp ? " and WhatsApp" : ""}, around 9 pm. Nothing on a quiet day.`;
}
