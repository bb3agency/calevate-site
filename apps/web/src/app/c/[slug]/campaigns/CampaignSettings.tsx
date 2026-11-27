"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Pencil } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { FIELD, ProblemNotice, formatPhone } from "@/components/ui";
import { useMyCallLines, type MyCallLines } from "@/lib/api/callLines";
import { useUpdateCampaign, type CampaignProgress } from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { describeRetry } from "./NewCampaignSteps";
import { atOnceNote, atOnceValue, callingHoursText } from "./campaignProgress";

const KIND: Record<string, string> = { promotional: "Promotional", service: "Service" };

/**
 * WHAT THE CAMPAIGN DIALS UNDER, in two groups an owner checks separately: what the call
 * is (why, the goal, the kind of call, the agent) and how it dials (the number, the hours,
 * the pace, the retries, do-not-call). Labels sit over their values inside each group, so
 * the same block reads in a narrow column beside a draft's people and spread across the
 * width in a launched campaign's tab; a container query, not the viewport, decides when a
 * group's rows go label-beside-value, because the column it sits in is what is narrow.
 */
export function CampaignSettings({
  slug,
  campaignId,
  progress,
  layout = "wide",
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
  /** `aside`: one column beside the people. `wide`: the two groups side by side. */
  layout?: "aside" | "wide";
}) {
  const { href } = useClientRealm();
  const editable = progress.status === "draft";
  return (
    <section aria-labelledby={`settings-${campaignId}`} className="min-w-0">
      <div className="flex items-center justify-between gap-3">
        <h2 id={`settings-${campaignId}`} className="text-heading text-ink">
          How it calls
        </h2>
        {editable ? (
          <Link href={href(`/c/${slug}/campaigns/${campaignId}/edit`)} className={TEXT_ACTION}>
            <Pencil aria-hidden className="h-3.5 w-3.5" />
            Change
          </Link>
        ) : null}
      </div>
      <div className={`mt-4 grid grid-cols-1 items-start gap-4 ${layout === "wide" ? "md:grid-cols-2" : ""}`}>
        <Group title="The call">
          <Fact label="Why it calls" value={progress.purpose ?? "Not said"} />
          <Fact label="Goal" value={progress.goal ?? "Not said"} />
          <Fact label="Kind of call" value={lookup(KIND, progress.classification) ?? progress.classification} />
          <Fact label="Agent" value={progress.agent_name} />
        </Group>
        <Group title="Dialling">
          <Fact
            label="Calling from"
            value={progress.number_e164 ? formatPhone(progress.number_e164) : "The agent's own number"}
          />
          <Fact label="Calling hours" value={callingHoursText(progress)} />
          <Fact
            label="Calls at once"
            value={atOnceValue(progress)}
            hint={<AtOnceHint progress={progress} />}
          />
          <Fact label="No answer, busy or voicemail" value={describeRetry(progress.retry_policy)} />
          <Fact label="Do-not-call list" value="Numbers on it are always skipped" />
          <Fact label="Skip recent calls" value={<SkipRecent campaignId={campaignId} progress={progress} />} />
        </Group>
      </div>
    </section>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="@container min-w-0 border-t border-line">
      <h3 className="pt-3 text-meta font-semibold text-ink-muted">{title}</h3>
      <dl className="divide-y divide-line">{children}</dl>
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="py-3 @sm:grid @sm:grid-cols-[9.5rem_minmax(0,1fr)] @sm:gap-x-4">
      <dt className="text-meta text-ink-muted">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-body text-ink [overflow-wrap:anywhere] @sm:mt-0">
        {value}
        {hint}
      </dd>
    </div>
  );
}

/** The day counts offered; a saved value outside them (1 to 30 is allowed) is offered too. */
const SKIP_DAYS = [1, 3, 7, 14, 30];
/** Statuses that still call someone, so the skip can still change who is called. */
const SKIP_CHANGEABLE = new Set(["draft", "scheduled", "running", "paused"]);

function skipChoices(current: number | null | undefined): number[] {
  return current != null && !SKIP_DAYS.includes(current)
    ? [...SKIP_DAYS, current].sort((a, b) => a - b)
    : SKIP_DAYS;
}

/**
 * "Skip people we called in the last N days" (D-1046): any campaign or call that reached the
 * person counts, this campaign's own tries do not. Saved on change; a running campaign uses
 * the new value from its next round of calls.
 */
function SkipRecent({ campaignId, progress }: { campaignId: string; progress: CampaignProgress }) {
  const { session } = useClientRealm();
  const update = useUpdateCampaign(session, campaignId);
  const write = useWriteAccess(session, "leads:dispatch", "change this campaign");
  const days = progress.skip_recent_days ?? null;
  const waiting = progress.recently_called_waiting;
  const changeable = SKIP_CHANGEABLE.has(progress.status) && progress.archived_at == null;
  return (
    <div>
      <select
        aria-label="Skip people called recently"
        className={`${FIELD} block`}
        value={days ?? "off"}
        disabled={!changeable || !write.allowed || update.isPending}
        onChange={(e) => update.mutate({ skip_recent_days: e.target.value === "off" ? null : Number(e.target.value) })}
      >
        <option value="off">Off: call everyone</option>
        {skipChoices(days).map((n) => (
          <option key={n} value={n}>
            {n === 1 ? "Called in the last day" : `Called in the last ${n} days`}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-meta text-ink-muted">
        {days == null
          ? "People other campaigns reached are called anyway."
          : waiting > 0
            ? `${waiting} waiting: called in the last ${days === 1 ? "day" : `${days} days`}.`
            : "Calls nobody answered don't count."}
      </span>
      {update.error != null && (
        <div className="mt-2">
          <ProblemNotice error={update.error} />
        </div>
      )}
    </div>
  );
}

/**
 * Why fewer calls run at once than the campaign asked for, under the figure. The account's
 * call lines are read only when the campaign is held below its own setting, so a campaign
 * that gets what it asked for costs no extra request.
 */
export function AtOnceHint({
  progress,
  className = "block text-meta text-ink-muted",
}: {
  progress: Pick<CampaignProgress, "concurrency" | "effective_concurrency">;
  className?: string;
}) {
  if (progress.effective_concurrency >= progress.concurrency) return null;
  return <HeldBelowSetting progress={progress} className={className} />;
}

function HeldBelowSetting({
  progress,
  className,
}: {
  progress: Pick<CampaignProgress, "concurrency" | "effective_concurrency">;
  className: string;
}) {
  const { session, href } = useClientRealm();
  const lines = useMyCallLines(session);
  // Said once the lines have answered (or failed), so the cause does not change under the reader.
  if (lines.isLoading) return null;
  const data = lines.data;
  const accountIsLimit = data !== undefined && data.call_lines === progress.effective_concurrency;
  return (
    <span className={className}>
      {atOnceNote(progress, data?.call_lines)}
      {accountIsLimit ? <MoreLines lines={data} phoneHref={href(`/c/${session.orgSlug}/phone-number`)} /> : null}
    </span>
  );
}

/**
 * How to get more, when the account's lines are what holds the campaign back. The number is
 * ours to raise, so a paying account asks on the Phone number screen (`AskForMoreLines`); a
 * trial has one line until it pays, and an account already at the most gets no offer.
 */
function MoreLines({ lines, phoneHref }: { lines: MyCallLines; phoneHref: string }) {
  if (lines.on_trial) return <> Trial: one line. More once you pay.</>;
  if (lines.call_lines >= lines.max_lines) return null;
  return (
    <>
      {" "}
      {/* Inline in the sentence, so not TEXT_ACTION's padded block; ink, not brand, since
          brand is kept for done and money. */}
      <Link
        href={phoneHref}
        className="rounded-sm font-medium text-ink underline decoration-ink-faint underline-offset-2 hover:decoration-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-action"
      >
        Ask for more lines
      </Link>
    </>
  );
}
