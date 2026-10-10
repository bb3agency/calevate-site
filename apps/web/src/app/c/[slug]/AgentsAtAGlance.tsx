"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";

import { Section, TEXT_ACTION } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { ProblemNotice, Skeleton, formatCount, formatIST } from "@/components/ui";
import type { useAgentStats, useAgents, Agent } from "@/lib/api/agents";
import { DIRECTION_COPY, STATUS_COPY, isAnsweringNow, isDeleted } from "@/lib/agentState";
import { lookup } from "@/lib/lookup";

/**
 * EACH AGENT, ONE LINE: is it working, what does it do, how much has it done.
 *
 * A divided list rather than a card per agent: the agents are peers read top to bottom,
 * and what should catch the eye is an agent that is switched on but NOT working, so that
 * is the one warning-toned pill (visual-hierarchy: colour for status, not decoration).
 * The count is the agent's whole history (`/v1/agents/stats` is lifetime by design), so it
 * is labelled "calls so far" rather than passed off as this week's.
 */
export function AgentsAtAGlance({
  agents,
  stats,
  href,
}: {
  agents: ReturnType<typeof useAgents>;
  stats: ReturnType<typeof useAgentStats>;
  href: (path: string) => string;
}) {
  const action = (
    <Link href={href("/agents/new")} className={TEXT_ACTION}>
      Add an agent
    </Link>
  );
  if (agents.isLoading) {
    return (
      <Section title="Your agents" action={action}>
        <Skeleton rows={2} label="Loading your agents" />
      </Section>
    );
  }
  if (agents.error || !agents.data) {
    return (
      <Section title="Your agents" action={action}>
        <ProblemNotice
          error={agents.error ?? new Error("Your agents did not load.")}
          onRetry={() => void agents.refetch()}
        />
      </Section>
    );
  }
  const current = agents.data.filter((agent) => !isDeleted(agent));
  // The setup checklist owns the "make your first agent" moment; an empty list here
  // would say the same thing a second time.
  if (current.length === 0) return null;

  return (
    <Section title="Your agents" action={action}>
      <ul className="divide-y divide-line border-y border-line">
        {current.map((agent) => (
          <AgentLine
            key={agent.id}
            agent={agent}
            stat={stats.data?.find((row) => row.agent_id === agent.id)}
            href={href(`/agents/${agent.id}`)}
          />
        ))}
      </ul>
    </Section>
  );
}

function AgentLine({
  agent,
  stat,
  href,
}: {
  agent: Agent;
  stat: { calls_total: number; last_call_at: string | null } | undefined;
  href: string;
}) {
  const working = isAnsweringNow(agent);
  const state = working
    ? null
    : agent.status === "live"
      ? "Not on the phone yet"
      : (lookup(STATUS_COPY, agent.status)?.label ?? agent.status);
  const role = lookup(DIRECTION_COPY, agent.direction)?.label ?? agent.direction;
  return (
    <li className="relative flex items-center gap-4 py-3.5 transition-colors duration-(--duration-fast) has-[a:hover]:bg-ink/[0.03]">
      <div className="min-w-0 flex-1">
        <Link
          href={href}
          className="block truncate rounded-sm text-body font-medium text-ink after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand"
        >
          {agent.name}
        </Link>
        <p className="truncate text-meta text-ink-muted">
          {role}
          {stat?.last_call_at ? ` · last call ${formatIST(stat.last_call_at)}` : ""}
          {stat ? <span className="sm:hidden"> · {formatCount(stat.calls_total)} calls so far</span> : null}
        </p>
      </div>
      {stat ? (
        <p className="hidden shrink-0 text-right sm:block">
          <span className="block text-body font-semibold tabular-nums text-ink">{formatCount(stat.calls_total)}</span>
          <span className="block text-meta text-ink-muted">calls so far</span>
        </p>
      ) : null}
      {state ? (
        <StatusPill tone={agent.status === "paused" || agent.status === "draft" ? "neutral" : "warn"}>{state}</StatusPill>
      ) : (
        <StatusPill tone="ok">Working</StatusPill>
      )}
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-ink-faint" />
    </li>
  );
}
