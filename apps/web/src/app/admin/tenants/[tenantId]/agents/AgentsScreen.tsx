"use client";

import { EmptySketch } from "@/components/console/emptySketch";
import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { EmptyState } from "@/components/console/emptyState";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, Skeleton } from "@/components/ui";
import { useTenant, useTenantAgents } from "@/lib/api/admin";
import { useAdminLlmDefaults } from "@/lib/api/llmDefaults";
import { lookup } from "@/lib/lookup";

import { HAIRLINE_LIST, StatusPill, sentenceCase } from "@/components/admin/kit";
import { AGENT_STATUS_TONE } from "../statePill";

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
  // The REAL model each agent runs. `/v1/agents` is the client realm's roster and carries
  // only tiers (D-680), so the operator's model column comes from the admin read.
  const models = useAdminLlmDefaults(tenantId);
  const modelOf = (agentId: string): string => {
    if (models.isError) return "model could not be read";
    if (models.data === undefined) return "reading model…";
    const row = models.data.agents.find((entry) => entry.agent_id === agentId);
    return row?.llm_model_effective ?? "model not reported";
  };

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader title="Agents" description="Open an agent to change its script, voice or limits." />
      {agents.error ? (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      ) : agents.isLoading || !agents.data ? (
        <Skeleton rows={3} />
      ) : agents.data.length === 0 ? (
        <EmptyState
          message="No agents yet. Nothing answers or dials for this client until one is built."
          illustration={
            <EmptySketch kind="actions" />
          }
        />
      ) : (
        <ul aria-label="Agents" className={HAIRLINE_LIST}>
          {agents.data.map((agent) => (
            <li key={agent.id}>
              <Link
                href={`/admin/tenants/${tenantId}/agents/${agent.id}/prompt`}
                className="group flex items-center gap-3 py-3 hover:bg-ink/[0.03] sm:px-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand touch:min-h-11"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-body font-medium text-ink">{agent.name}</span>
                    <StatusPill tone={lookup(AGENT_STATUS_TONE, agent.status) ?? "neutral"}>
                      {sentenceCase(agent.status)}
                    </StatusPill>
                  </span>
                  <span className="mt-0.5 block text-meta text-ink-muted">
                    {lookup(DIRECTION, agent.direction) ?? agent.direction} · {agent.language_primary}
                    {" · "}
                    {agent.inbound_number_count === 1
                      ? "1 number"
                      : `${agent.inbound_number_count} numbers`}
                    {" · "}
                    {modelOf(agent.id)}
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
