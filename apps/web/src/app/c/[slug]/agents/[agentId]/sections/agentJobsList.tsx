"use client";

/**
 * ITS JOBS, ON "WHAT IT SAYS" — one row per campaign and Inbound line in this agent's voice
 * (`GET /v1/agents/{id}/jobs`), each with its state, the first thing it says there, and the
 * way to where those words are changed.
 *
 * The rows link to the job's own page rather than editing in place: a campaign's or a line's
 * script has one editor, on its page (D-997), and a second one here would be two places for
 * one script. The campaign link asks for its Script tab (`?tab=script`, PLAN.md §3); until
 * the campaign page has that tab the address opens its default view, which is the same page.
 *
 * The first thing it says comes from the job's own script: a line's from the account's line
 * list (one read for every row), a campaign's from its workspace read, the same cached query
 * the campaign page opens with. A campaign's calls open on `opening_line`
 * (`campaigns/scenarioModel.openingOf`, a campaign runs as outbound).
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { ChevronRight, Phone, PhoneIncoming } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { Section } from "@/components/console/section";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton } from "@/components/ui";
import { useAgentJobs, type AgentJob } from "@/lib/api/agentJobs";
import type { Agent } from "@/lib/api/agents";
import { useCampaignWorkspace } from "@/lib/api/campaignWorkspace";
import { useWriteAccess } from "@/lib/api/hooks";
import { useCreateInboundLine, useInboundLines, type InboundLine } from "@/lib/api/inboundLines";
import { useClientRealm } from "@/lib/api/session";

import { CampaignStatusPill } from "../../../campaigns/campaignStatus";
import { AGENT_PARAM } from "../../../campaigns/NewCampaignScreen";
import { LineStatusPill } from "../../../inbound/lineStatus";

/** Where a job's words are changed. */
export function jobScriptPath(slug: string, job: Pick<AgentJob, "id" | "kind">): string {
  return job.kind === "inbound_line"
    ? `/c/${slug}/inbound/${job.id}`
    : `/c/${slug}/campaigns/${job.id}?tab=script`;
}

export function AgentJobsList({ agent, slug }: { agent: Agent; slug: string }) {
  const { session } = useClientRealm();
  const jobs = useAgentJobs(session, agent.id);
  const hasLine = jobs.isSuccess && jobs.data.jobs.some((job) => job.kind === "inbound_line");
  // One read for every line row; not asked for when the agent answers no line.
  const lines = useInboundLines(session, hasLine);

  return (
    <Section headingLevel={3} title="Its jobs" description="What it says on each.">
      {jobs.isPending ? (
        <Skeleton rows={2} label="Finding its campaigns and Inbound lines" />
      ) : jobs.isError ? (
        <ProblemNotice error={jobs.error} onRetry={() => void jobs.refetch()} />
      ) : (
        <div className="space-y-4">
          {jobs.data.jobs.length === 0 ? (
            <p className="text-body text-ink-muted">No job yet. It says nothing until it has one.</p>
          ) : (
            <ul aria-label="Its jobs" className="divide-y divide-line border-y border-line">
              {jobs.data.jobs.map((job) => (
                <li key={`${job.kind}:${job.id}`}>
                  {job.kind === "inbound_line" ? (
                    <LineRow job={job} slug={slug} lines={lines} />
                  ) : (
                    <CampaignRow job={job} slug={slug} />
                  )}
                </li>
              ))}
            </ul>
          )}
          <NewJob agent={agent} slug={slug} another={jobs.data.jobs.length > 0} />
        </div>
      )}
    </Section>
  );
}

function CampaignRow({ job, slug }: { job: AgentJob; slug: string }) {
  const { session } = useClientRealm();
  const workspace = useCampaignWorkspace(session, job.id);
  const opening = workspace.data?.script?.opening_line.trim() ?? "";
  return (
    <JobRow
      job={job}
      slug={slug}
      kind="Calls people"
      state={<CampaignStatusPill status={job.status} />}
      opening={workspace.isPending ? null : opening}
      failed={workspace.isError}
    />
  );
}

function LineRow({
  job,
  slug,
  lines,
}: {
  job: AgentJob;
  slug: string;
  lines: ReturnType<typeof useInboundLines>;
}) {
  const line: InboundLine | undefined = lines.data?.find((one) => one.id === job.id);
  const opening = line?.script?.opening_line.trim() ?? "";
  return (
    <JobRow
      job={job}
      slug={slug}
      kind="Answers calls"
      state={line ? <LineStatusPill line={line} /> : null}
      opening={lines.isPending ? null : opening}
      failed={lines.isError}
    />
  );
}

/**
 * One job. `opening` is null while its read is on the way; an empty string is a job whose
 * script has no first words yet, which is said as such rather than left blank.
 */
function JobRow({
  job,
  slug,
  kind,
  state,
  opening,
  failed,
}: {
  job: AgentJob;
  slug: string;
  kind: string;
  state: ReactNode;
  opening: string | null;
  failed: boolean;
}) {
  const { href } = useClientRealm();
  const Icon = job.kind === "inbound_line" ? PhoneIncoming : Phone;
  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Icon aria-hidden className="h-4 w-4 shrink-0 text-ink-muted" />
          <p className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{job.name}</p>
          <span className="text-meta text-ink-muted">{kind}</span>
          {state}
        </div>
        {failed ? (
          <p className="text-meta text-ink-muted">Couldn&apos;t read its first words.</p>
        ) : opening === null ? (
          <Skeleton rows={1} label="Reading its first words" />
        ) : opening ? (
          <p className="max-w-prose text-body text-ink-muted [overflow-wrap:anywhere]">
            <span className="text-ink">First thing it says: </span>
            &ldquo;{opening}&rdquo;
          </p>
        ) : (
          <p className="text-meta text-ink-muted">No first words written yet.</p>
        )}
      </div>
      <Link href={href(jobScriptPath(slug, job))} className={`${SECONDARY_BUTTON_SM} shrink-0 self-start`}>
        Change what it says
        <ChevronRight aria-hidden className="h-4 w-4" />
      </Link>
    </div>
  );
}

/**
 * Give it a job: calling people is a new campaign that starts with this agent (the new
 * campaign screen's `?agent=`), answering calls is a new Inbound line in its voice, made
 * here and opened. Each is offered only where the agent's direction allows it.
 */
function NewJob({ agent, slug, another }: { agent: Agent; slug: string; another: boolean }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const create = useCreateInboundLine(session);
  const feedback = useActionFeedback(create, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "org:manage", "give this agent a job");
  const calls = agent.direction !== "inbound";
  const answers = agent.direction !== "outbound";
  return (
    <div className="space-y-2">
      <p className="text-meta font-medium text-ink">{another ? "Give it another job" : "Give it a job"}</p>
      <div className="flex flex-wrap gap-2">
        {calls && (
          <Link
            href={href(`/c/${slug}/campaigns/new?${AGENT_PARAM}=${encodeURIComponent(agent.id)}`)}
            className={SECONDARY_BUTTON_SM}
          >
            <Phone aria-hidden className="h-4 w-4" />
            Call people
          </Link>
        )}
        {answers && (
          <ActionButton
            variant="secondary-sm"
            status={feedback.status}
            pendingLabel="Making the line…"
            disabled={!write.allowed || create.isPending}
            title={write.reason ?? undefined}
            onClick={() =>
              create.mutate(
                { agent_id: agent.id },
                { onSuccess: (line) => router.push(href(`/c/${slug}/inbound/${line.id}`)) },
              )
            }
          >
            <PhoneIncoming aria-hidden className="h-4 w-4" />
            Answer calls
          </ActionButton>
        )}
      </div>
      {create.error != null && <ProblemNotice error={create.error} />}
    </div>
  );
}
