"use client";

import Link from "next/link";
import type { UseQueryResult } from "@tanstack/react-query";

import { StatsBand } from "@/components/arc/stats-band";
import { Section } from "@/components/console/section";
import { PRIMARY_BUTTON, ProblemNotice, SECONDARY_BUTTON, Skeleton, formatCount } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { Stats } from "@/lib/api/analytics";
import type { CampaignSummary } from "@/lib/api/campaigns";
import type { Dashboard } from "@/lib/api/client";
import { activeTrial, walletState, type Wallet } from "@/lib/api/wallet";
import { canDialOut, isAnsweringNow, isDeleted } from "@/lib/agentState";

import { statItems } from "./analyticsFigures";
import { trialUrgency, trialView } from "./TrialBanner";

/** May this reader use the action? `useWriteAccess(...).allowed`, read by the screen. */
export interface RecapAccess {
  addCredit: boolean;
  createAgent: boolean;
  runCampaigns: boolean;
}

export interface RecapAction {
  key: "credit" | "create-agent" | "open-agents" | "campaign" | "calls";
  label: string;
  href: string;
  /** Filled. Only an action something calls for, or the week's calls; never more than one. */
  primary: boolean;
}

/**
 * THE DASHBOARD'S ONE BLOCK OF FIGURES, AND WHAT TO DO NEXT.
 *
 * Four figures for the last 7 days, each against the 7 days before (`/v1/analytics/stats`),
 * then at most three actions. Hot leads are not here: "What needs you today" says them with
 * their action. Whether each agent is on is said once, by "Your agents".
 *
 * The first action is the one this account most needs now (`recapActions`), filled; the
 * rest are secondary. It is the page's one filled button, so it is where the eye lands
 * after the figures. A quiet week that needs nothing gets no filled button at all. An
 * action the reader's role cannot perform is not offered.
 */
export function WeekRecap({
  data,
  stats,
  agents,
  wallet,
  campaigns,
  access,
  href,
}: {
  data: Dashboard;
  stats: UseQueryResult<Stats>;
  agents: Agent[] | undefined;
  wallet: Wallet | undefined;
  campaigns: CampaignSummary[] | undefined;
  access: RecapAccess;
  href: (path: string) => string;
}) {
  const current = agents?.filter((agent) => !isDeleted(agent));
  const actions = recapActions({ data, agents: current, wallet, campaigns, access }).map((action) => ({
    ...action,
    href: href(action.href),
  }));

  return (
    <Section title="This week">
      <div className="space-y-6">
        {data.calls_7d > 0 ? (
          <WeekFigures data={data} stats={stats} />
        ) : (
          <QuietWeek data={data} noAgent={current?.length === 0} />
        )}
        {actions.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {actions.map((action) => (
              <Link key={action.key} href={action.href} className={action.primary ? PRIMARY_BUTTON : SECONDARY_BUTTON}>
                {action.label}
              </Link>
            ))}
          </div>
        ) : null}
      </div>
    </Section>
  );
}

const WEEK_KEYS = ["calls", "answer_rate_pct", "leads", "avg_duration_s"] as const;

function WeekFigures({ data, stats }: { data: Dashboard; stats: UseQueryResult<Stats> }) {
  if (stats.error) {
    return <ProblemNotice error={stats.error} onRetry={() => void stats.refetch()} />;
  }
  if (!stats.data) return <Skeleton rows={2} label="Loading this week's figures" />;
  return (
    <StatsBand
      label="The last 7 days"
      items={statItems(stats.data, [...WEEK_KEYS], {
        context: "vs the previous 7 days",
        trends: { calls: data.daily_7d.map((day) => day.total) },
      })}
    />
  );
}

/** No calls: one sentence instead of a row of zeroes, and new leads only if there were some. */
function QuietWeek({ data, noAgent }: { data: Dashboard; noAgent: boolean }) {
  return (
    <p className="max-w-prose text-body text-ink-muted [text-wrap:pretty]">
      No calls in the last 7 days.
      {data.calls_prev_7d > 0
        ? ` The week before had ${formatCount(data.calls_prev_7d)} ${data.calls_prev_7d === 1 ? "call" : "calls"}.`
        : ""}
      {data.leads_new_7d > 0
        ? ` ${formatCount(data.leads_new_7d)} new ${data.leads_new_7d === 1 ? "lead" : "leads"} came in.`
        : ""}
      {noAgent ? " You have no agent yet, so nobody is answering or making calls." : ""}
    </p>
  );
}

/**
 * WHICH ACTIONS, AND WHICH ONE LEADS. Paths are realm-relative ("/billing?tab=credits").
 *
 * The lead is the first of these that holds, in order of what stops calls soonest:
 *
 * 1. Calls have stopped for want of credit: Add credit.
 * 2. No agent: Build your first agent.
 * 3. The trial needs acting on (last day, a tenth of its minutes left, or a test-calls
 *    trial that ended unpaid): Add credit.
 * 4. Agents, none switched on: Open agent / See agents.
 * 5. Credit is low: Add credit.
 * 6. A test-calls-only trial, where adding credit is what opens live calls: Add credit.
 * 7. An agent that can dial out and no campaign yet: Start a campaign.
 *
 * Only that one is filled; with none of them, See calls is, when there were calls, and a
 * quiet week that needs nothing has no filled button. The routine ones fill the remaining
 * places: See calls, campaigns, Add credit, Add an agent. Each appears once, three at
 * most. Credit is offered only to a prepaid account, campaigns never during a
 * test-calls-only trial (they cannot launch), and nothing the reader's role is refused.
 */
type Candidate = Omit<RecapAction, "primary">;

export function recapActions({
  data,
  agents,
  wallet,
  campaigns,
  access,
}: {
  data: Dashboard;
  agents: Agent[] | undefined;
  wallet: Wallet | undefined;
  campaigns: CampaignSummary[] | undefined;
  access: RecapAccess;
}): RecapAction[] {
  const state = wallet ? walletState(wallet) : null;
  const trial = activeTrial(wallet);
  const view = trialView(wallet);
  const testCallsOnly = view !== null && (view.kind === "ended" || view.testCallsOnly);

  const credit: Candidate | null =
    access.addCredit && wallet?.prepaid ? { key: "credit", label: "Add credit", href: "/billing?tab=credits" } : null;
  const noAgent = agents !== undefined && agents.length === 0;
  const create: Candidate | null = access.createAgent
    ? noAgent
      ? { key: "create-agent", label: "Meet your agent", href: "/agents/first" }
      : { key: "create-agent", label: "Add an agent", href: "/agents/new" }
    : null;
  const allOff = agents !== undefined && agents.length > 0 && !agents.some(isAnsweringNow);
  const openAgents: Candidate | null =
    agents && agents.length > 0
      ? {
          key: "open-agents",
          label: agents.length === 1 ? "Open agent" : "See agents",
          href: agents.length === 1 ? `/agents/${agents[0]!.id}` : "/agents",
        }
      : null;
  const canCampaign = access.runCampaigns && !testCallsOnly && (agents ?? []).some(canDialOut);
  const noCampaign = campaigns !== undefined && campaigns.length === 0;
  const campaign: Candidate | null = canCampaign
    ? { key: "campaign", label: noCampaign ? "Start a campaign" : "Open campaigns", href: "/campaigns" }
    : null;
  const calls: Candidate | null = data.calls_7d > 0 ? { key: "calls", label: "See calls", href: "/calls" } : null;

  const lead: (Candidate | null)[] = [
    state === "stopped" ? credit : null,
    noAgent ? create : null,
    trialUrgency(view) !== null ? credit : null,
    allOff ? openAgents : null,
    state === "low" ? credit : null,
    trial !== null && testCallsOnly ? credit : null,
    noCampaign ? campaign : null,
  ];
  const routine = [calls, campaign, credit, create];

  const first = lead.find((action) => action !== null) ?? calls;
  const seen = new Set<string>();
  const out: RecapAction[] = [];
  for (const action of [first, ...routine]) {
    if (action === null || seen.has(action.key)) continue;
    seen.add(action.key);
    out.push({ ...action, primary: action === first });
  }
  return out.slice(0, 3);
}
