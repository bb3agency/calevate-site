"use client";

import { Gauge, type ReadinessFix } from "@/components/arc/gauge";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton } from "@/components/ui";
import type { AccountReadiness } from "@/lib/api/readiness";
import type { UseQueryResult } from "@tanstack/react-query";

/**
 * How ready the account's agents are to take real calls (D-870): the mean of every working
 * agent's 0-100 score, and the fixes worth the most points across them.
 *
 * The score and the fixes are the server's. A fix's `href` is realm-relative
 * ("/agents/{id}?section=training"), so it goes through the screen's own `href`, which
 * keeps a view-as session across the click. With more than one agent a fix names the agent
 * it is for, matched on the agent id its link carries.
 */
export function ReadinessPanel({
  readiness,
  href,
}: {
  readiness: UseQueryResult<AccountReadiness>;
  href: (path: string) => string;
}) {
  const data = readiness.data;
  if (readiness.error) {
    return (
      <Section title="Ready for calls">
        <ProblemNotice error={readiness.error} onRetry={() => void readiness.refetch()} />
      </Section>
    );
  }
  if (!data) {
    return (
      <Section title="Ready for calls">
        <Skeleton rows={3} label="Loading how ready your agents are" />
      </Section>
    );
  }
  // No agent yet: the first-agent invitation above already says what to do.
  if (data.agents.length === 0) return null;

  const names = new Map(data.agents.map((agent) => [agent.agent_id, agent.agent_name]));
  const fixes: ReadinessFix[] = data.top_fixes.map((fix) => {
    const agentId = /^\/agents\/([^/?#]+)/.exec(fix.href)?.[1];
    const agentName = agentId === undefined ? undefined : names.get(agentId);
    return {
      id: `${fix.component}:${fix.href}`,
      label: fix.action,
      detail: data.agents.length > 1 && agentName ? agentName : undefined,
      points: fix.points,
      href: href(fix.href),
    };
  });

  return (
    <Section title="Ready for calls">
      <Gauge
        value={data.score}
        label={data.agents.length === 1 ? "Your agent's readiness" : "Your agents' readiness"}
        pendingText="We have not scored your agents yet."
        fixes={fixes}
        fixesTitle="Raise it next"
        allDoneText="Nothing left to fix. Your agents are ready."
        pointsLabel={(points) => `+${points}`}
        size={120}
      />
    </Section>
  );
}
