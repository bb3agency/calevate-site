"use client";

import { useAdminAccess } from "@/app/admin/access";
import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import {
  FIELD,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatINRExact,
  formatISTStamp,
} from "@/components/ui";
import {
  useAdminBusinessCopy,
  useAdminRefreshBusinessCopy,
  useAdminSetCapability,
  type AdminBusinessCopy,
  type Capabilities,
  type Capability,
} from "@/lib/api/businessCopy";
import { lookup } from "@/lib/lookup";

const TRIGGER: Record<string, string> = {
  signup: "account created",
  refresh: "the owner asked",
  scheduled: "scheduled check",
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
  const tenantWrite = useAdminAccess("admin:tenants", "correct what this business does");
  const setCapability = useAdminSetCapability(tenantId);

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
      {/* Every account is re-judged once when the copy prompt changes; until then no
          capability is judged, and the rows below would be six unexplained blanks. */}
      {!data.refreshing && !profileJudged(data) && (
        <NoticeBox
          tone="info"
          role="status"
          title="Still learning what this business does"
          action={
            access.allowed ? (
              <button
                type="button"
                className={TEXT_ACTION}
                disabled={refresh.isPending}
                onClick={() => refreshFeedback.run()}
              >
                Retry
              </button>
            ) : undefined
          }
        >
          Screens use neutral wording until it is worked out.
        </NoticeBox>
      )}
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
        <SettingRow label="Calls its callers" value={data.caller_noun ?? "Not judged yet"} />
        {CAPABILITY_ROWS.map(([key, label]) => (
          <SettingRow
            key={key}
            label={label}
            value={capabilityLine(data.capabilities?.[key])}
            hint={lookup(data.capability_overrides ?? {}, key) !== undefined ? "Set by us" : undefined}
            action={
              tenantWrite.allowed ? (
                <CapabilityChoice
                  label={label}
                  chosen={lookup(data.capability_overrides ?? {}, key)}
                  pending={setCapability.isPending}
                  onChoose={(applies) => setCapability.mutate({ key, applies })}
                />
              ) : null
            }
          />
        ))}
      </SettingRows>
      <ProblemNotice error={refresh.error} />
      <ProblemNotice error={setCapability.error} />
    </Section>
  );
}

/**
 * One capability's correction: the AI's judgement, or Yes / No decided by us (A7-08). Saved
 * at once and audited; a regeneration keeps it, and "AI's judgement" restores the AI's.
 */
function CapabilityChoice({
  label,
  chosen,
  pending,
  onChoose,
}: {
  label: string;
  chosen: boolean | undefined;
  pending: boolean;
  onChoose: (applies: boolean | null) => void;
}) {
  const value = chosen === undefined ? "ai" : chosen ? "yes" : "no";
  return (
    <select
      aria-label={`${label}: who decides`}
      className={`${FIELD} w-auto`}
      value={value}
      disabled={pending}
      onChange={(event) => {
        const next = event.target.value;
        onChoose(next === "ai" ? null : next === "yes");
      }}
    >
      <option value="ai">AI&apos;s judgement</option>
      <option value="yes">Yes</option>
      <option value="no">No</option>
    </select>
  );
}

/** The capability profile (D-827, prompt version 4): what the screens and the agents' plans
 * follow for this client, each correctable by an operator. */
const CAPABILITY_ROWS: readonly (readonly [keyof Capabilities, string])[] = [
  ["takes_bookings", "Takes bookings"],
  ["takes_orders", "Takes orders"],
  ["quotes_prices", "Tells callers prices"],
  ["has_premises", "Callers come to a place"],
  ["sells", "Sells to callers"],
  ["health_business", "Health business"],
];

/** Whether any capability has been judged (by the AI or by us). Exported for the test. */
export function profileJudged(data: AdminBusinessCopy): boolean {
  return CAPABILITY_ROWS.some(([key]) => {
    const judged = data.capabilities?.[key];
    return judged?.applies === true || judged?.applies === false;
  });
}

/** Exported for the test. */
export function capabilityLine(judged: Capability | null | undefined): string {
  // An API older than this screen sends no profile at all: that is "not judged", not a crash.
  if (judged?.applies === null || judged?.applies === undefined) return "Not judged yet";
  const verdict = judged.applies ? "Yes" : "No";
  return judged.reason ? `${verdict}: ${judged.reason}` : verdict;
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
  return `${formatINRExact(data.cost_inr)}, ${data.absorbed ? "paid by us" : "from the client's AI allowance"}${data.model ? ` on ${data.model}` : ""}`;
}
