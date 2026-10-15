"use client";

import Link from "next/link";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { formatPhone } from "@/components/ui";
import type { CampaignProgress } from "@/lib/api/campaigns";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { describeRetry } from "./NewCampaignSteps";

const KIND: Record<string, string> = { promotional: "Promotional", service: "Service" };

/**
 * WHAT THE CAMPAIGN DIALS UNDER, as label–value rows (REDESIGN-2): the kind of call, the
 * agent, the number, the hours, the pace and the retries. They used to be one run-on line
 * under the name; read as rows they can be checked one at a time, and a draft offers Edit.
 * The pace says when the plan or the lines kept free for inbound callers allow fewer
 * calls at once than the campaign asked for (`effective_concurrency`).
 */
export function CampaignSettings({
  slug,
  campaignId,
  progress,
}: {
  slug: string;
  campaignId: string;
  progress: CampaignProgress;
}) {
  const { href } = useClientRealm();
  const hours = progress.calling_hours;
  const limited = progress.effective_concurrency < progress.concurrency;
  return (
    <Section
      className="max-w-2xl"
      title="How it calls"
      action={
        progress.status === "draft" ? (
          <Link href={href(`/c/${slug}/campaigns/${campaignId}/edit`)} className={TEXT_ACTION}>
            Change
          </Link>
        ) : undefined
      }
    >
      <SettingRows className="border-y border-line">
        <SettingRow label="Kind of call" value={lookup(KIND, progress.classification) ?? progress.classification} />
        <SettingRow label="Agent" value={progress.agent_name} />
        <SettingRow
          label="Calling from"
          value={progress.number_e164 ? formatPhone(progress.number_e164) : "The agent's own number"}
        />
        <SettingRow label="Calling hours" value={hours ? `${hours.start}–${hours.end} IST` : "9am–9pm IST"} />
        <SettingRow
          label="Calls at the same time"
          hint={
            limited
              ? `Set to ${progress.concurrency}; your plan and the lines kept free for people calling you allow ${progress.effective_concurrency}.`
              : undefined
          }
          value={`Up to ${progress.effective_concurrency}`}
        />
        <SettingRow label="No answer, busy or voicemail" value={describeRetry(progress.retry_policy)} />
        <SettingRow label="Do-not-call list" value="Numbers on it are always skipped" />
      </SettingRows>
    </Section>
  );
}
