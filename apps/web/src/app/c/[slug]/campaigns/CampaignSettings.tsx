"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Pencil } from "lucide-react";

import { TEXT_ACTION } from "@/components/console/section";
import { formatPhone } from "@/components/ui";
import { useMyCallLines } from "@/lib/api/callLines";
import type { CampaignProgress } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { describeRetry } from "./NewCampaignSteps";
import { atOnceNote, callingHoursText } from "./campaignProgress";

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
            label="Calls at the same time"
            value={`Up to ${progress.effective_concurrency}`}
            hint={<AtOnceHint progress={progress} />}
          />
          <Fact label="No answer, busy or voicemail" value={describeRetry(progress.retry_policy)} />
          <Fact label="Do-not-call list" value="Numbers on it are always skipped" />
        </Group>
      </div>
    </section>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="@container min-w-0 rounded-card border border-line px-4 py-1">
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
  const { session } = useClientRealm();
  const lines = useMyCallLines(session);
  // Said once the lines have answered (or failed), so the cause does not change under the reader.
  if (lines.isLoading) return null;
  return <span className={className}>{atOnceNote(progress, lines.data?.call_lines)}</span>;
}
