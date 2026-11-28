"use client";

import { useState } from "react";

import { Section } from "@/components/console/section";
import { DISCLOSURE_LIST, Disclosure, ProblemNotice, Skeleton } from "@/components/ui";
import { useCampaigns } from "@/lib/api/campaigns";
import { useInboundLines } from "@/lib/api/inboundLines";
import { useClientSession } from "@/lib/api/session";
import type { AlertJobKind } from "@/lib/api/teamAlerts";

import { JobAlertsBody } from "../../campaigns/JobAlerts";

/**
 * "TELL ME WHEN AN ANSWER IS X", FOR EVERY CAMPAIGN AND LINE IN ONE PLACE (D-1048, W5.3).
 * Each job's rule reads that job's own "What it notes" list (`JobAlertsBody`, the same form
 * its own page shows), so the choices are exact answers, never free text. Opening a row
 * loads its rule; a closed row costs nothing.
 */
export function JobAlertsList() {
  const session = useClientSession();
  const campaigns = useCampaigns(session);
  const lines = useInboundLines(session);
  const failed = campaigns.error ?? lines.error;
  const jobs: { kind: AlertJobKind; id: string; name: string }[] = [
    ...(lines.data ?? []).map((l) => ({ kind: "line" as const, id: l.id, name: l.name })),
    ...(campaigns.data ?? [])
      .filter((c) => c.archived_at == null)
      .map((c) => ({ kind: "campaign" as const, id: c.id, name: c.name })),
  ];

  return (
    <Section
      title="Alerts on answers"
      description="Hear about calls where a detail has the answer you pick."
      info={<p>Set per campaign or line, from the details it notes. The same choice is on its own page.</p>}
    >
      {failed != null ? (
        <ProblemNotice
          error={failed}
          onRetry={() => {
            void campaigns.refetch();
            void lines.refetch();
          }}
        />
      ) : !campaigns.data || !lines.data ? (
        <Skeleton rows={3} label="Loading campaigns and lines" />
      ) : jobs.length === 0 ? (
        <p className="text-body text-ink-muted">No campaigns or lines yet.</p>
      ) : (
        <div className={DISCLOSURE_LIST}>
          {jobs.map((job) => (
            <JobRow key={`${job.kind}:${job.id}`} kind={job.kind} id={job.id} name={job.name} />
          ))}
        </div>
      )}
    </Section>
  );
}

function JobRow({ kind, id, name }: { kind: AlertJobKind; id: string; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Disclosure
      variant="row"
      headingLevel={3}
      title={name}
      subtitle={kind === "line" ? "Inbound line" : "Campaign"}
      onToggle={setOpen}
    >
      {open ? <JobAlertsBody kind={kind} jobId={id} showWhoHears={false} /> : null}
    </Disclosure>
  );
}
