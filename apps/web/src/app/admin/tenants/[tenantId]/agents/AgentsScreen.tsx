"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useTenant, useTenantAgents } from "@/lib/api/admin";
import { lookup } from "@/lib/lookup";

import { AGENT_STATUS_TONE, StatePill } from "../statePill";

const DIRECTION: Record<string, string> = {
  inbound: "Answers calls",
  outbound: "Makes calls",
  both: "Answers and makes calls",
};

/**
 * One client's agents, each a link to its own page (script, voice, call length, A/B test).
 *
 * Primary job: *find the agent to work on.* A row is one link (UX §4, one target per row);
 * there is no create action because agents are built from the client's intake, not here.
 *
 * A failed read and an empty roster are different answers: "this client has no agents" is
 * the more alarming of the two to be wrong about, so it is said only when the server said it.
 */
export function AgentsScreen({ tenantId }: { tenantId: string }) {
  const slug = useTenant(tenantId).data?.slug ?? "";
  const agents = useTenantAgents(slug);

  return (
    <div className="space-y-5">
      <PageHeader title="Agents" description="Open an agent to change its script, voice or limits." />
      {agents.error ? (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      ) : agents.isLoading || !agents.data ? (
        <Skeleton rows={3} />
      ) : agents.data.length === 0 ? (
        <EmptyState message="No agents yet. Nothing answers or dials for this client until one is built." />
      ) : (
        <ul className="divide-y divide-line rounded-card border border-line bg-surface">
          {agents.data.map((agent) => (
            <li key={agent.id}>
              <Link
                href={`/admin/tenants/${tenantId}/agents/${agent.id}/prompt`}
                className="group flex items-center gap-3 px-4 py-3 hover:bg-ink/[0.03] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-[15px] font-medium text-ink">{agent.name}</span>
                    <StatePill tone={lookup(AGENT_STATUS_TONE, agent.status) ?? "neutral"}>
                      {agent.status}
                    </StatePill>
                  </span>
                  <span className="mt-0.5 block text-[13px] text-ink-muted">
                    {lookup(DIRECTION, agent.direction) ?? agent.direction} · {agent.language_primary}
                    {" · "}
                    {agent.inbound_number_count === 1
                      ? "1 number"
                      : `${agent.inbound_number_count} numbers`}
                    {" · "}
                    {agent.llm_model_effective}
                  </span>
                </span>
                <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-faint group-hover:text-ink" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
