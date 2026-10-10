"use client";

import { Section } from "@/components/console/section";
import Link from "next/link";

import { NoticeBox, ProblemNotice, Skeleton } from "@/components/ui";
import { useWorkspacesSummary, type WorkspacesSummary } from "@/lib/api/engineWorkspaces";

import type { OpsAccess } from "./opsAccess";

/**
 * Every client's own ThinnestAI customer workspace against the plan (D-693).
 *
 * The plan caps how many customer workspaces exist, and a client signed up past the cap
 * gets no workspace — so no number — until the plan is upgraded and provisioning retried on
 * that client's page. Headroom of one or less is the warning to upgrade BEFORE the next
 * signup rather than after it. Renders nothing on an engine without per-client workspaces.
 */
export function WorkspacesSummaryPanel({ access }: { access: OpsAccess }) {
  const summary = useWorkspacesSummary(access.allowed);
  if (!access.allowed) return null;
  if (summary.isLoading) {
    return (
      <Section title="Client voice workspaces">
        <Skeleton rows={3} />
      </Section>
    );
  }
  if (summary.error || !summary.data) {
    return (
      <Section title="Client voice workspaces">
        <ProblemNotice error={summary.error} onRetry={() => void summary.refetch()} />
      </Section>
    );
  }
  if (!summary.data.available) return null;
  return <SummaryCard data={summary.data} />;
}

function SummaryCard({ data }: { data: WorkspacesSummary }) {
  const statuses = Object.entries(data.by_status);
  const tight = data.headroom !== null && data.headroom <= 1;
  return (
    <Section
      title="Client voice workspaces"
      info={
        <p>
          Each client&apos;s own ThinnestAI customer workspace, where its numbers are rented in its
          business name. The platform account&apos;s own business details are the panel below.
        </p>
      }
    >
      <dl className="grid gap-x-6 gap-y-2 text-body sm:grid-cols-[max-content_1fr]">
        <dt className="text-ink-muted">Provisioned</dt>
        <dd className="font-medium text-ink">
          {data.provisioned} of {data.tenants} clients
        </dd>
        <dt className="text-ink-muted">Not provisioned</dt>
        <dd className="text-ink">{data.not_provisioned}</dd>
        <dt className="text-ink-muted">Plan</dt>
        <dd className="text-ink">
          {data.plan ?? "Not known"}
          {data.plan_cap !== null ? ` — ${data.counted} of ${data.plan_cap} customers used` : ""}
        </dd>
        <dt className="text-ink-muted">Headroom</dt>
        <dd className="text-ink">{data.headroom === null ? "No cap known" : data.headroom}</dd>
        {statuses.length > 0 && (
          <>
            <dt className="text-ink-muted">By status</dt>
            <dd className="text-ink">
              {statuses.map(([status, count]) => `${status}: ${count}`).join(", ")}
            </dd>
          </>
        )}
      </dl>
      {tight && (
        <div className="mt-3">
          <NoticeBox tone="warn" title="The plan is nearly full">
            <p className="mt-1">
              {data.headroom === 0
                ? "No customer workspace is left on the plan: the next client gets none until the ThinnestAI plan is upgraded."
                : "One customer workspace is left on the plan. Upgrade the ThinnestAI plan before the next signups."}
            </p>
          </NoticeBox>
        </div>
      )}
      {data.failures.length > 0 && (
        <div className="mt-4">
          <h3 className="text-body font-semibold text-ink">Needs attention</h3>
          <ul className="mt-1 divide-y divide-line border-y border-line">
            {data.failures.map((failure) => (
              <li key={failure.tenant_id} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-body">
                <Link
                  href={`/admin/tenants/${failure.tenant_id}/numbers`}
                  className="font-medium text-ink underline"
                >
                  {failure.tenant_name}
                </Link>
                <span className="text-ink-muted">{failure.status}</span>
                {failure.last_error_code && (
                  <span className="ml-auto font-mono text-meta text-ink-muted">{failure.last_error_code}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  );
}
