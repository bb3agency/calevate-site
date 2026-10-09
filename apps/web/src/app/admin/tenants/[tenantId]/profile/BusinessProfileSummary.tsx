"use client";

import { Card, ProblemNotice, Skeleton } from "@/components/ui";
import { SettingRow, SettingRows } from "@/components/console/settingRow";
import { useAdminBusinessProfile } from "@/lib/api/businessProfile";
import { viewAsHref } from "@/lib/api/session";

/**
 * The client's business profile, read-only, as the operator sees it (D-695). It is the
 * same profile every agent of the client reads; it is edited by the client, or by an
 * operator through view-as, where the same audit applies.
 */
export function BusinessProfileSummary({ tenantId, slug }: { tenantId: string; slug: string | null }) {
  const profile = useAdminBusinessProfile(tenantId);
  if (profile.isPending) {
    return (
      <Card title="Business profile" density="compact">
        <Skeleton rows={3} />
      </Card>
    );
  }
  if (profile.isError) {
    return (
      <Card title="Business profile" density="compact">
        <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />
      </Card>
    );
  }
  const data = profile.data;
  const done = data.setup.steps.filter((step) => step.state !== "todo").length;
  return (
    <Card
      title="Business profile"
      density="compact"
      action={
        slug ? (
          <a href={viewAsHref(slug, "/settings/business")} className="text-[13px] font-medium text-brand-strong hover:underline">
            Edit as client
          </a>
        ) : undefined
      }
    >
      <SettingRows>
        <SettingRow label="Setup" value={`${done} of ${data.setup.steps.length} steps answered or skipped`} />
        <SettingRow
          label="Ready for calls"
          value={data.blockers.length === 0 ? "Yes" : data.blockers.map((b) => b.message).join(" ")}
        />
        <SettingRow label="Opening hours" value={`${data.hours.length} of 7 days answered`} />
        <SettingRow label="Addresses" value={String(data.branches.length)} />
        <SettingRow label="Services" value={String(data.services.length)} />
        <SettingRow label="People who take calls" value={String(data.contacts.length)} />
        <SettingRow label="Legal name (verification)" value={data.legal_name ?? "Not verified"} />
        {data.merge_notes.length > 0 && (
          <SettingRow
            label="Merged from several agents"
            hint="When the per-agent answers moved into this profile, agents disagreed. The oldest agent's answer was kept; the others are recorded."
            value={`${data.merge_notes.length} difference${data.merge_notes.length === 1 ? "" : "s"}`}
          />
        )}
      </SettingRows>
    </Card>
  );
}
