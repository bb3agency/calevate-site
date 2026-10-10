"use client";

import Link from "next/link";

import { StatusPill } from "@/components/admin/kit";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { NoticeBox, ProblemNotice, SECONDARY_BUTTON_SM, formatIST } from "@/components/ui";
import {
  BUSINESS_DETAILS_STATUS_COPY,
  useRefreshWorkspaceBusinessDetails,
  type TenantWorkspace,
} from "@/lib/api/engineWorkspaces";
import { lookup } from "@/lib/lookup";

/**
 * The number-rental approval on a deployment where each client has its own voice workspace
 * (D-693): the voice platform's answer to the business details we sent in the client's
 * name. It replaces the old "Carrier's decision" form there, because nobody types this
 * answer: the platform reports it (`GET /phone-numbers/business-details` in the client's
 * workspace, read by `campaigns/engine_business_details.refresh_business_details`). The
 * platform documents no webhook for it, so it is read every few minutes while an
 * application is being checked, daily otherwise, and on "Check again now".
 *
 * Read-only apart from that button. Sending the details is on the Numbers page beside the
 * purchase it unlocks.
 */
export function NumberApprovalPanel({
  tenantId,
  workspace,
  canWrite,
}: {
  tenantId: string;
  workspace: TenantWorkspace;
  canWrite: boolean;
}) {
  const refresh = useRefreshWorkspaceBusinessDetails(tenantId);
  const details = workspace.business_details;
  const status = details?.status ?? "none";

  return (
    <Section
      title="Approval for phone numbers"
      info={
        <p>
          India issues a number only to a business it has approved, in the business&apos;s own
          name. We send the client&apos;s verified details to their own voice workspace; the
          voice platform reports the answer here, usually within minutes.
        </p>
      }
    >
      <p className="-mt-1 text-body text-ink-muted">
        Until this says approved, no number can be rented for this client. Calls coming in on
        numbers they already hold are not affected.
      </p>
      <div className="mt-4 space-y-4">
        {workspace.status !== "active" ? (
          <p className="text-body text-ink-muted">
            The client&apos;s voice workspace is not set up yet, so nothing has been sent.
          </p>
        ) : (
          <SettingRows className="border-y border-line">
            <SettingRow
              label="Status"
              value={
                <span className="font-medium">
                  {lookup(BUSINESS_DETAILS_STATUS_COPY, status) ?? BUSINESS_DETAILS_STATUS_COPY.unknown}
                </span>
              }
            />
            <SettingRow label="Numbers can be rented" value={details?.can_rent ? "Yes" : "No"} />
            {details?.submitted_at && <SettingRow label="Last sent" value={formatIST(details.submitted_at)} />}
            <SettingRow
              label="Last checked"
              value={details?.checked_at ? formatIST(details.checked_at) : "Not read yet"}
            />
          </SettingRows>
        )}
        {details?.review_note && (
          <NoticeBox tone="warn" title="What to correct">
            <p className="mt-1">{details.review_note}</p>
          </NoticeBox>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            disabled={!canWrite || refresh.isPending || workspace.status !== "active"}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending ? "Checking…" : "Check again now"}
          </button>
          <Link href={`/admin/tenants/${tenantId}/numbers`} className={TEXT_ACTION}>
            Send the details or buy a number
          </Link>
        </div>
        <ProblemNotice error={refresh.error} />
      </div>
    </Section>
  );
}

/** The header's one-glance approval state. */
export function NumberApprovalPill({ workspace }: { workspace: TenantWorkspace }) {
  const details = workspace.business_details;
  if (details?.can_rent) return <StatusPill tone="ok">Numbers: approved</StatusPill>;
  const status = details?.status ?? "none";
  const tone = status === "rejected" || status === "suspended" || status === "expired" ? "warn" : "neutral";
  return (
    <StatusPill tone={tone}>
      Numbers: {(lookup(BUSINESS_DETAILS_STATUS_COPY, status) ?? "unknown").split(" —")[0]}
    </StatusPill>
  );
}
