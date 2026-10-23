"use client";

import { useAdminAccess } from "@/app/admin/access";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, Skeleton, formatINR, formatISTStamp } from "@/components/ui";
import {
  useAdminBusinessCopy,
  useAdminRefreshBusinessCopy,
  type AdminBusinessCopy,
} from "@/lib/api/businessCopy";
import { lookup } from "@/lib/lookup";

const TRIGGER: Record<string, string> = {
  signup: "account created",
  refresh: "the owner asked",
  scheduled: "15-day check",
  operator: "an operator asked",
};

/**
 * The client's AI-written examples (D-827), for an operator: when they were last written,
 * what that cost and who paid, why the last run wrote nothing if it did not, and a refresh
 * at our cost (`ops:manage`, audited), as "Suggest again" is for the business type.
 */
export function BusinessCopyPanel({ tenantId }: { tenantId: string }) {
  const copy = useAdminBusinessCopy(tenantId);
  const refresh = useAdminRefreshBusinessCopy(tenantId);
  const refreshFeedback = useActionFeedback(refresh, { errorDisplay: "inline" });
  const access = useAdminAccess("ops:manage", "write a client's examples again");

  if (copy.isError)
    return (
      <Section title="Business examples">
        <ProblemNotice error={copy.error} onRetry={() => void copy.refetch()} />
      </Section>
    );
  if (!copy.data)
    return (
      <Section title="Business examples">
        <Skeleton rows={2} label="Loading the business examples" />
      </Section>
    );
  const data = copy.data;
  return (
    <Section title="Business examples">
      <SettingRows>
        <SettingRow
          label="Last written"
          value={writtenLine(data)}
          action={
            access.allowed ? (
              <ActionButton
                variant="secondary-sm"
                status={refreshFeedback.status}
                pendingLabel="Asking…"
                successLabel="Asked"
                disabled={data.refreshing}
                onClick={() => refreshFeedback.run()}
              >
                {data.refreshing ? "Writing…" : "Write again at our cost"}
              </ActionButton>
            ) : null
          }
        />
        <SettingRow label="Cost of the copy in use" value={costLine(data)} />
        {data.stop_reason ? (
          <SettingRow label="Last run" value={data.stop_message ?? data.stop_reason} />
        ) : null}
      </SettingRows>
      <ProblemNotice error={refresh.error} />
    </Section>
  );
}

/** Exported for the test. */
export function writtenLine(data: AdminBusinessCopy): string {
  if (data.refreshing) return "Being written now";
  if (!data.generated_at) return "Not yet: the per-trade examples are shown";
  const why = lookup(TRIGGER, data.last_trigger);
  return `${formatISTStamp(data.generated_at)}${why ? ` (${why})` : ""}`;
}

/** Exported for the test. */
export function costLine(data: AdminBusinessCopy): string {
  if (!data.cost_inr) return "—";
  return `${formatINR(data.cost_inr)}, ${data.absorbed ? "paid by us" : "from the client's AI allowance"}${data.model ? ` on ${data.model}` : ""}`;
}
