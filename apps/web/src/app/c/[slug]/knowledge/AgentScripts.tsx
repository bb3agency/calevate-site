"use client";

import Link from "next/link";

import { ProblemNotice, Skeleton } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";

import { Group } from "./KnowledgeGroup";

/**
 * WHAT ONE AGENT KNOWS THAT THE OTHERS DO NOT: its own script (its job, its steps, what it
 * says), and, when it remembers callers, what each caller said before. Everything else on
 * this page is shared by every agent (D-689), so these are named here and opened on the
 * agent's own page rather than copied in. Archived agents take no calls and are left out.
 */
export function AgentScripts({ query }: { query: string }) {
  const session = useClientSession();
  const { href } = useClientRealm();
  const agents = useAgents(session);
  const q = query.trim().toLocaleLowerCase();

  if (agents.isLoading) return <Skeleton rows={2} label="Loading your agents" />;
  if (agents.error || !agents.data) {
    return (
      <ProblemNotice
        error={agents.error ?? new Error("We could not load your agents.")}
        onRetry={() => void agents.refetch()}
      />
    );
  }
  const current = agents.data.filter((a) => a.status !== "archived");
  const shown = current.filter((a) => !q || a.name.toLocaleLowerCase().includes(q));
  if (current.length === 0) return null;

  return (
    <Group
      title="Each agent's own script"
      count={current.length}
      hidden={q !== "" && shown.length === 0}
      info={<p>Only that agent uses its script. Everything above is shared.</p>}
    >
      <ul className="divide-y divide-line border-y border-line" aria-label="Agents">
        {shown.map((agent) => (
          <li key={agent.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink [overflow-wrap:anywhere]">{agent.name}</p>
              <p className="text-meta text-ink-muted">
                {agent.caller_memory_enabled && !agent.caller_memory_paused
                  ? "Its script. Also remembers each caller."
                  : "Its job and what it says."}
              </p>
            </div>
            <Link
              href={href(`/c/${session.orgSlug}/agents/${agent.id}?section=script`)}
              className="text-meta text-ink underline underline-offset-2 touch:inline-flex touch:min-h-11 touch:items-center"
            >
              Open its script
            </Link>
          </li>
        ))}
      </ul>
    </Group>
  );
}
