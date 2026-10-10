"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldAlert } from "lucide-react";

import {
  FIELD,
  FIELD_HINT,
  FIELD_LABEL,
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatWholeCount,
} from "@/components/ui";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { useAdminAccess } from "@/app/admin/access";
import { Term } from "@/lib/glossary";
import { useTenant } from "@/lib/api/admin";
import {
  needsPreferenceScrub,
  scrubBlocker,
  useRecordPreferenceScrub,
  useTenantCampaigns,
  useTenantLaunchCheck,
} from "@/lib/api/preferenceScrub";
import type { CampaignSummary } from "@/lib/api/campaigns";

import { ScrubForm } from "./ScrubForm";
import { ScrubResult } from "./ScrubResult";

/**
 * THE NATIONAL DND SCRUB — the only thing that unblocks promotional dialling.
 *
 * `national_dnd_blocker` refuses every promotional campaign until a run is on file
 * (`national_dnd_scrub_missing`) and again once it has aged out
 * (`national_dnd_scrub_expired`), at launch and on every dispatch tick. The only writer of
 * `preference_scrub_runs` is the admin route this screen calls.
 *
 * THE EXPIRY IS THE THING MOST EASILY GOT WRONG, so it is said three ways: a scrub is good
 * until 23:59:59 IST on the day the provider ran it, the campaign keeps dialling past
 * midnight, and `is_current` is the SERVER's verdict — never `expires_at > now` computed
 * here, because only the server may say whether a late-recorded run satisfies the gate.
 */
export function ScrubScreen({ tenantId }: { tenantId: string }) {
  const tenant = useTenant(tenantId).data;
  const slug = tenant?.slug ?? "";
  const campaigns = useTenantCampaigns(slug);
  // `null` until the operator chooses; with exactly one campaign to scrub there is nothing
  // to choose between, so that one is preselected.
  const [chosenId, setChosenId] = useState<string | null>(null);

  // The tenant layout resolves this before mounting the page.
  if (!tenant) return null;

  const scrubbable = (campaigns.data ?? []).filter(needsPreferenceScrub);
  const campaignId = chosenId ?? (scrubbable.length === 1 ? scrubbable[0].id : "");
  const selected = scrubbable.find((campaign) => campaign.id === campaignId) ?? null;

  return (
    <div className="max-w-3xl space-y-10">
      <PageHeader
        title="National DND scrub"
        description={
          <>
            Record a provider&apos;s <Term id="dnd" /> scrub of one promotional campaign. It
            opens that campaign&apos;s launch gate until midnight IST.{" "}
            <InfoTip label="what this is not">
              <p>
                It is not the platform-wide do-not-call list (that one is on{" "}
                <Link href="/admin/ops/dnc" className="font-medium underline">
                  ops, under do-not-call
                </Link>
                ) and it is not the client&apos;s own suppression list.
              </p>
              <p>
                It is a per-campaign scrub run by a provider against the national register,
                recorded against the campaign it was run for. Only promotional campaigns are
                scoped by the register; transactional and service traffic is not, and no
                scrub is offered for them.
              </p>
            </InfoTip>
          </>
        }
      />

      {campaigns.error && (
        <ProblemNotice error={campaigns.error} onRetry={() => campaigns.refetch()} />
      )}

      {campaigns.isLoading ? (
        <Skeleton rows={4} />
      ) : !campaigns.data ? (
        /* Withheld, not empty: "no campaign needs a scrub" is also a real state, and an
           operator who reads it over a failed read believes there is nothing to unblock. */
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot list this client's campaigns"
        >
          <p className="mt-1 text-meta opacity-90">
            We could not read them, which is not the same as there being none. Retry the read
            above; the picker comes back with it.
          </p>
        </NoticeBox>
      ) : scrubbable.length === 0 ? (
        <EmptyState
          message={
            <>
              <span className="block font-medium text-ink">No campaign here needs a scrub</span>
              <span className="mt-1 block">
                {campaigns.data.length === 0
                  ? "This client has not built a campaign yet. A promotional one will appear here the moment they do."
                  : "Every campaign on this account is transactional or service traffic, which the preference register does not scope — or has already finished dialling. Nothing is being held up."}
              </span>
            </>
          }
        />
      ) : (
        <>
          <div className="max-w-xl">
            <label htmlFor="scrub-campaign" className={FIELD_LABEL}>
              Promotional campaign
            </label>
            <select
              id="scrub-campaign"
              value={campaignId}
              onChange={(e) => setChosenId(e.target.value)}
              aria-describedby="scrub-campaign-hint"
              className={FIELD}
            >
              <option value="">— choose a campaign —</option>
              {scrubbable.map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name} · {campaign.status} ·{" "}
                  {formatWholeCount(String(campaign.contacts))} contacts
                </option>
              ))}
            </select>
            <span id="scrub-campaign-hint" className={FIELD_HINT}>
              A scrub is recorded against ONE campaign&apos;s list — the list the provider saw.
            </span>
          </div>
          {/* Keyed by campaign: switching campaigns must not carry a half-typed reference
              or a previous result into another campaign's record. */}
          {selected && (
            <ScrubForCampaign key={selected.id} tenantId={tenantId} slug={slug} campaign={selected} />
          )}
        </>
      )}
    </div>
  );
}

/** The gate's live state for this campaign, then the form that changes it. */
function ScrubForCampaign({
  tenantId,
  slug,
  campaign,
}: {
  tenantId: string;
  slug: string;
  campaign: CampaignSummary;
}) {
  const check = useTenantLaunchCheck(slug, campaign.id);
  const record = useRecordPreferenceScrub(tenantId, slug, campaign.id);
  const write = useAdminAccess("admin:tenants", "record a national DND scrub");
  const blocker = scrubBlocker(check.data);

  return (
    <div className="space-y-4">
      {check.error && <ProblemNotice error={check.error} onRetry={() => check.refetch()} />}
      {check.isLoading ? (
        <Skeleton rows={2} />
      ) : !check.data ? (
        <NoticeBox
          tone="warn"
          icon={<AlertTriangle className="h-5 w-5" />}
          title="Cannot read this campaign's launch gate"
        >
          <p className="mt-1 text-meta opacity-90">
            Recording a scrub still works, and is still the right thing to do if you are
            holding a provider&apos;s report — this panel simply cannot tell you whether the
            gate is currently open. Retry the read above.
          </p>
        </NoticeBox>
      ) : blocker ? (
        <NoticeBox
          tone="stop"
          icon={<ShieldAlert className="h-5 w-5" />}
          title={
            blocker.rule === "national_dnd_scrub_expired"
              ? "The scrub on file has expired — this campaign is held"
              : "No scrub on file — this campaign is held"
          }
        >
          {/* The SERVER's sentence, which names the remedy: the launch preview, the
              dispatch tick and this screen must say the same thing. */}
          <p className="mt-1 text-meta opacity-90">{blocker.reason}</p>
        </NoticeBox>
      ) : (
        <NoticeBox
          tone="ok"
          icon={<CheckCircle2 className="h-5 w-5" />}
          title="The preference-register gate is open for this campaign"
        >
          <p className="mt-1 text-meta opacity-90">
            A current scrub is on file. It stops being current at midnight IST, and the
            campaign keeps dialling past midnight — so a run recorded today does not cover
            tomorrow&apos;s dialling.{" "}
            {check.data.ready
              ? "Nothing else is holding this campaign either."
              : "Other launch blockers remain; they are on the client's own campaign screen."}
          </p>
        </NoticeBox>
      )}

      <ScrubForm campaign={campaign} record={record} write={write} />
      {/* Below the form, where the operator's eye is when the write lands. */}
      {record.error != null && <ProblemNotice error={record.error} />}
      {record.data && <ScrubResult result={record.data} />}
    </div>
  );
}
