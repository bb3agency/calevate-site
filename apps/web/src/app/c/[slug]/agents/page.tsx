"use client";

import Link from "next/link";
import { use } from "react";
import { Plus } from "lucide-react";

import { PRIMARY_BUTTON, ProblemNotice, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/console/pageHeader";
import { AskAssistant } from "@/components/copilot/AskAssistant";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm, useClientSession } from "@/lib/api/session";
import { agentGroup } from "@/lib/agentState";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { HowChangesTakeEffect } from "./LaneGuide";
import { Archive, Roster } from "./Roster";
import { TrialLockNotice } from "../TrialLockNotice";

/**
 * Your agents — which ones are answering calls right now, one row each, and the way to make
 * a new one. Everything about ONE agent lives on its own screen (`./[agentId]`), so this
 * list renders from `GET /v1/agents` alone rather than one `/pending` read per agent.
 *
 * Loading, failure and "you have none" are three exclusive branches; "none" is said only
 * where the server said so, because a failed read is not evidence about an account.
 */
export default function AgentsPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const session = useClientSession();
  const { href } = useClientRealm();
  const agents = useAgents(session);
  const roster = agents.data ?? [];

  /* The counts, not the rows, from the same `agentGroup` predicate the list orders by, so
     the assistant and the screen cannot disagree. The archive is a second request inside
     `<Archive/>` and is deliberately absent. */
  useCopilotSurface({
    route: "/c/{slug}/agents",
    title: "Your agents",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: agents.data
          ? "the roster below has loaded"
          : agents.error
            ? "the roster failed to load, so no agent is listed"
            : "still loading",
      },
      ...(agents.data
        ? [
            {
              key: "agents_total",
              label: "Agents on the working roster",
              value: String(roster.length),
            },
            {
              key: "agents_working",
              label:
                "Agents working right now (on the calling system and switched on)",
              value: String(
                roster.filter((agent) => agentGroup(agent) === "active").length,
              ),
            },
            {
              key: "agents_not_working",
              label: "Agents not working (being built, or switched off)",
              value: String(
                roster.filter((agent) => agentGroup(agent) !== "active").length,
              ),
            },
            {
              key: "agent_directions",
              label: "How many answer, call out, or both",
              value: (["inbound", "outbound", "both"] as const)
                .map(
                  (direction) =>
                    `${direction}: ${roster.filter((agent) => agent.direction === direction).length}`,
                )
                .join(", "),
            },
          ]
        : []),
    ],
    apply: noFill,
  });

  const working = roster.filter((agent) => agentGroup(agent) === "active").length;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        description="Open one to change what it says, teach it, or switch it on and off."
        status={
          agents.data && roster.length > 0 ? (
            working === 0 ? (
              <span className="rounded-full border border-warn-line bg-warn-soft px-3 py-1 text-xs font-semibold text-ink">
                Nothing is answering your calls
              </span>
            ) : (
              <span className="text-sm text-ink-muted">
                {working} of {roster.length} answering calls
              </span>
            )
          ) : undefined
        }
        actions={
          <>
            <AskAssistant prompt="Look over my agents and tell me what to improve first." />
            <Link href={href(`/c/${slug}/agents/new`)} className={PRIMARY_BUTTON}>
              <Plus aria-hidden className="h-4 w-4" />
              New agent
            </Link>
          </>
        }
      />
      <TrialLockNotice lock="agents" />

      {agents.error && (
        <ProblemNotice error={agents.error} onRetry={() => void agents.refetch()} />
      )}

      {agents.isLoading ? (
        <Skeleton rows={4} />
      ) : agents.data ? (
        <Roster agents={agents.data} slug={slug} />
      ) : null}

      <Archive slug={slug} />

      {/* The precedence rule §2b asks to be STATED, once for the section: it is a property
          of the platform, not of an agent, so it renders only beside a non-empty list. */}
      {agents.data?.length ? <HowChangesTakeEffect session={session} /> : null}
    </div>
  );
}
