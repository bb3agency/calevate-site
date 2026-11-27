"use client";

/**
 * WHAT IT NOTES — what this agent's calls write down for a lead, and how its calls can end.
 *
 * Read-only on purpose. Since D-1028 the list of details belongs to each campaign and Inbound
 * line, and Lead details is the one screen that edits every job's list and the agent's call
 * outcomes (D-1029, D-836). Editing here as well would be a second editor for one list, the
 * drift D-1029 removed; so each job shows what it notes with a link to that job, and the tab
 * carries one link to Lead details.
 */

import Link from "next/link";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAgentJobs, type AgentJob } from "@/lib/api/agentJobs";
import type { Agent } from "@/lib/api/agents";
import { useCallOutcomes } from "@/lib/api/callOutcomes";
import { useJobNotes } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";
import { CopilotSurfaceScope } from "@/lib/copilot/registry";

import { LEAD_MOVE_WORDS } from "@/components/leadFields/CallOutcomesView";

const LEAD_DETAILS = (slug: string) => `/c/${slug}/settings/lead-details`;

export function NotesTab({ agent, slug }: { agent: Agent; slug: string }) {
  const { href } = useClientRealm();
  return (
    <CopilotSurfaceScope
      route="/c/{slug}/agents/{id}"
      title={`Agent: what it notes (${agent.name})`}
      realm="client"
      facts={[
        { key: "agent_id", label: "Agent id", value: agent.id },
        {
          key: "what_is_here",
          label: "What this tab holds",
          value:
            "the details each of its campaigns and Inbound lines writes down after a call, and how its calls can end; both are changed on Lead details",
        },
      ]}
    >
      <div className="space-y-12">
        <Section
          headingLevel={3}
          title="What each job writes down"
          description="Each campaign and Inbound line keeps its own list."
          action={
            <Link href={href(LEAD_DETAILS(slug))} className={TEXT_ACTION}>
              Change in Lead details
            </Link>
          }
        >
          <JobsNotes agent={agent} slug={slug} />
        </Section>
        <Section headingLevel={3} title="How its calls can end">
          <Outcomes agent={agent} />
        </Section>
      </div>
    </CopilotSurfaceScope>
  );
}

function JobsNotes({ agent, slug }: { agent: Agent; slug: string }) {
  const { session } = useClientRealm();
  const jobs = useAgentJobs(session, agent.id);
  if (jobs.isPending) return <Skeleton rows={3} label="Finding its campaigns and Inbound lines" />;
  if (jobs.isError) return <ProblemNotice error={jobs.error} onRetry={() => void jobs.refetch()} />;
  if (jobs.data.jobs.length === 0) {
    return <p className="text-body text-ink-muted">No job yet. A call notes only its basics.</p>;
  }
  return (
    <ul aria-label="What each job writes down" className="divide-y divide-line border-y border-line">
      {jobs.data.jobs.map((job) => (
        <li key={`${job.kind}:${job.id}`} className="py-4">
          <JobNotesRow job={job} slug={slug} />
        </li>
      ))}
    </ul>
  );
}

function JobNotesRow({ job, slug }: { job: AgentJob; slug: string }) {
  const { session, href } = useClientRealm();
  const kind = job.kind === "inbound_line" ? "line" : "campaign";
  const notes = useJobNotes(session, kind, job.id);
  const page = job.kind === "inbound_line" ? `/c/${slug}/inbound/${job.id}` : `/c/${slug}/campaigns/${job.id}`;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{job.name}</p>
        <Link href={href(page)} className={TEXT_ACTION}>
          {job.kind === "inbound_line" ? "Open line" : "Open campaign"}
        </Link>
      </div>
      {notes.isPending ? (
        <Skeleton rows={1} label="Reading what it notes" />
      ) : notes.isError ? (
        <ProblemNotice error={notes.error} onRetry={() => void notes.refetch()} />
      ) : (
        <FieldList
          labels={[...notes.data.core_fields, ...notes.data.fields].map((field) => field.label)}
        />
      )}
    </div>
  );
}

/** Labels as one wrapping run of plain text, not chips: they are facts, not controls. */
function FieldList({ labels }: { labels: string[] }) {
  if (labels.length === 0) return <p className="text-meta text-ink-muted">Nothing noted yet.</p>;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-body text-ink-muted">
      {labels.map((label, index) => (
        <li key={`${index}:${label}`}>{label}</li>
      ))}
    </ul>
  );
}

function Outcomes({ agent }: { agent: Agent }) {
  const { session } = useClientRealm();
  const outcomes = useCallOutcomes(session);
  if (outcomes.isPending) return <Skeleton rows={3} label="Reading how its calls can end" />;
  if (outcomes.isError) {
    return <ProblemNotice error={outcomes.error} onRetry={() => void outcomes.refetch()} />;
  }
  const own = outcomes.data.agents.find((one) => one.id === agent.id)?.outcomes ?? [];
  if (own.length === 0) {
    return <p className="text-body text-ink-muted">Only the outcomes every business shares.</p>;
  }
  return (
    <ul aria-label="How its calls can end" className="divide-y divide-line border-y border-line">
      {own.map((outcome) => (
        <li key={outcome.key} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-baseline sm:gap-6">
          <p className="text-body font-medium text-ink sm:w-48 sm:shrink-0">{outcome.label}</p>
          <p className="min-w-0 flex-1 text-body text-ink-muted">{outcome.meaning}</p>
          <p className="text-meta text-ink-muted">{LEAD_MOVE_WORDS[outcome.lead_status]}</p>
        </li>
      ))}
    </ul>
  );
}
