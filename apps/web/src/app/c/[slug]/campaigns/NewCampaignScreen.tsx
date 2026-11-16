"use client";

/**
 * `/c/{slug}/campaigns/new`: makes a draft at once and opens it (founder, 15 Nov 2026: empty
 * sections on a separate New page "don't make sense"). The draft page is the one place a
 * campaign is set up, so every section (main task, materials, script, agent, test call,
 * people, the compliance checks, other settings) has its controls from the first moment.
 *
 * The draft starts with the agent `?agent=` names, else the first agent, as Service calls held to the account's
 * call lines, named "New campaign, <date>"; all of it changes on the draft page. A draft left
 * unused can be deleted from the campaigns list.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { PageHeader } from "@/components/console/pageHeader";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents } from "@/lib/api/agents";
import { useMyCallLines } from "@/lib/api/callLines";
import { useCreateCampaign } from "@/lib/api/campaigns";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";

import { TrialLockNotice } from "../TrialLockNotice";
import { NoAgentYet } from "./NewCampaignSteps";
import { clampConcurrency, concurrencyCap, nameFromGoal } from "./campaignForm";

/** What a new draft asks for before the account's lines hold it. */
const DEFAULT_CONCURRENCY = 3;

/** The query parameter naming the agent a new campaign starts with. */
export const AGENT_PARAM = "agent";

export function NewCampaignScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const router = useRouter();
  const queryClient = useQueryClient();
  const agents = useAgents(session);
  const callLines = useMyCallLines(session);
  const create = useCreateCampaign(session);
  useActionFeedback(create, { errorDisplay: "inline" });
  const write = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  const started = useRef(false);

  // `?agent=` names the agent to start with (a new agent's "Give it a job"); else the first.
  const wanted = useSearchParams().get(AGENT_PARAM);
  const assignable = (agents.data ?? []).filter(isAssignable);
  const agent = assignable.find((one) => one.id === wanted) ?? assignable[0];
  const canStart = Boolean(agent) && write.allowed && !callLines.isLoading;

  const start = () => {
    if (!agent || started.current) return;
    started.current = true;
    create.mutate(
      {
        agent_id: agent.id,
        name: nameFromGoal("New campaign"),
        classification: "service",
        concurrency: clampConcurrency(DEFAULT_CONCURRENCY, concurrencyCap(callLines.data?.call_lines)),
      },
      {
        onSuccess: (made) => {
          void queryClient.invalidateQueries({ queryKey: ["campaigns", session.orgSlug] });
          router.replace(href(`/c/${slug}/campaigns/${made.id}`));
        },
        onError: () => {
          started.current = false;
        },
      },
    );
  };

  // Once, as soon as an agent and the account's call lines are known.
  useEffect(() => {
    if (canStart) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canStart]);

  return (
    <div className="max-w-6xl space-y-5 pb-12">
      <PageHeader back={{ href: href(`/c/${slug}/campaigns`), label: "All campaigns" }} title="New campaign" />
      <TrialLockNotice lock="campaigns" />
      <RestrictionNote reason={write.reason} />
      {agents.error ? (
        <ProblemNotice error={agents.error} onRetry={() => agents.refetch()} />
      ) : agents.data && !agent ? (
        <NoAgentYet />
      ) : create.error ? (
        <ProblemNotice error={create.error} onRetry={start} />
      ) : write.allowed ? (
        <Skeleton rows={4} label="Setting up your campaign" />
      ) : null}
    </div>
  );
}
