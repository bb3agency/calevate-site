"use client";

import { InfoTip } from "@/components/console/infoTip";
import { Section, TEXT_ACTION } from "@/components/console/section";
import { Fact, ProblemNotice, Skeleton } from "@/components/ui";
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
      <Section title="Business profile">
        <Skeleton rows={3} />
      </Section>
    );
  }
  if (profile.isError) {
    return (
      <Section title="Business profile">
        <ProblemNotice error={profile.error} onRetry={() => void profile.refetch()} />
      </Section>
    );
  }
  const data = profile.data;
  const done = data.setup.steps.filter((step) => step.state !== "todo").length;
  return (
    <Section
      title="Business profile"
      action={
        slug ? (
          <a href={viewAsHref(slug, "/settings/business")} className={TEXT_ACTION}>
            Edit as client
          </a>
        ) : undefined
      }
    >
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-y border-line py-4 sm:grid-cols-3">
        <Fact label="Setup">{`${done} of ${data.setup.steps.length} steps answered or skipped`}</Fact>
        <Fact label="Ready for calls">
          {data.blockers.length === 0 ? "Yes" : data.blockers.map((b) => b.message).join(" ")}
        </Fact>
        <Fact label="Opening hours">{`${data.hours.length} of 7 days answered`}</Fact>
        <Fact label="Addresses">{String(data.branches.length)}</Fact>
        <Fact label="Services">{String(data.services.length)}</Fact>
        <Fact label="People who take calls">{String(data.contacts.length)}</Fact>
        <Fact label="Legal name (verification)">{data.legal_name ?? "Not verified"}</Fact>
        {data.merge_notes.length > 0 && (
          <Fact label="Merged from several agents">
            {`${data.merge_notes.length} difference${data.merge_notes.length === 1 ? "" : "s"}`}
            <InfoTip label="merged answers">
              <p>
                When the per-agent answers moved into this profile, agents disagreed. The oldest
                agent&apos;s answer was kept; the others are recorded.
              </p>
            </InfoTip>
          </Fact>
        )}
      </dl>
    </Section>
  );
}
