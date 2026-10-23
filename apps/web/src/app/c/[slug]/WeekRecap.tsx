"use client";

import Link from "next/link";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { PRIMARY_BUTTON, SECONDARY_BUTTON, formatCount, formatDuration } from "@/components/ui";
import type { Agent } from "@/lib/api/agents";
import type { CampaignSummary } from "@/lib/api/campaigns";
import type { Dashboard } from "@/lib/api/client";
import { activeTrial, walletState, type Wallet } from "@/lib/api/wallet";
import { canDialOut, isAnsweringNow, isDeleted } from "@/lib/agentState";

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
 * The week's calls (with the week-on-week reading), connected and missed, then today's
 * calls, the week's new leads and the average call length, followed by at most three
 * actions. Hot leads are not here: "What needs you today" says them with their action.
 * Whether each agent is on is said once, by "Your agents" in the roster's own words.
 *
 * The first action is the one this account most needs now (`recapActions`), filled; the
 * rest are secondary. A quiet week that needs nothing gets no filled button at all. An
 * action the reader's role cannot perform is not offered.
 */
export function WeekRecap({
  data,
  agents,
  wallet,
  campaigns,
  access,
  href,
}: {
  data: Dashboard;
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
      <div className="space-y-5">
        {data.calls_7d > 0 ? <WeekFigures data={data} /> : <QuietWeek data={data} noAgent={current?.length === 0} />}
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

/** Two columns on a phone, three from `sm`, so six figures are three short rows, not a strip. */
const FIGURE_GRID = "grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3";

function WeekFigures({ data }: { data: Dashboard }) {
  const connected = data.calls_connected_7d;
  const notConnected = data.calls_not_connected_7d;
  const share = Math.round((connected / data.calls_7d) * 100);
  return (
    <div className={FIGURE_GRID}>
      <Metric
        label="Calls"
        value={formatCount(data.calls_7d)}
        flashValue={String(data.calls_7d)}
        hint={<Trend current={data.calls_7d} previous={data.calls_prev_7d} />}
      />
      <Metric
        label="Connected"
        value={formatCount(connected)}
        flashValue={String(connected)}
        hint={connected === data.calls_7d ? "Every one of them" : `${share}% of calls`}
      />
      <Metric
        label="Did not connect"
        value={formatCount(notConnected)}
        flashValue={String(notConnected)}
        tone={notConnected > 0 ? "warn" : "default"}
        hint={notConnected > 0 ? "No answer, busy or failed" : "None missed"}
      />
      <Metric
        label="Calls today"
        value={formatCount(data.calls_today)}
        flashValue={String(data.calls_today)}
        hint="Since midnight, India time"
      />
      <NewLeads data={data} />
      {/* A seven-day average of COMPLETED calls (D-215), said in the hint so it is not
          read as an all-time figure. */}
      <Metric
        label="Average call length"
        value={formatDuration(data.avg_duration_s_7d)}
        flashValue={data.avg_duration_s_7d == null ? null : String(data.avg_duration_s_7d)}
        hint="Completed calls"
      />
    </div>
  );
}

function NewLeads({ data }: { data: Dashboard }) {
  return (
    <Metric
      label="New leads"
      value={formatCount(data.leads_new_7d)}
      flashValue={String(data.leads_new_7d)}
      hint={<Trend current={data.leads_new_7d} previous={data.leads_new_prev_7d} />}
    />
  );
}

/**
 * The comparison with the week before, as an arrow and words. The arrow is neutral ink:
 * more calls is not good or bad in itself, and the words carry the reading (WCAG 1.4.1).
 */
function Trend({ current, previous }: { current: number; previous: number }) {
  if (previous === 0) return <>None the week before</>;
  const diff = current - previous;
  const Icon = diff > 0 ? ArrowUp : diff < 0 ? ArrowDown : Minus;
  const words =
    diff === 0
      ? "Same as the week before"
      : `${formatCount(Math.abs(diff))} ${diff > 0 ? "more" : "fewer"} than the week before`;
  return (
    <span className="inline-flex items-start gap-1">
      <Icon aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
      {words}
    </span>
  );
}

/** No calls: one sentence instead of a row of zeroes, and new leads only if there were some. */
function QuietWeek({ data, noAgent }: { data: Dashboard; noAgent: boolean }) {
  return (
    <>
      <p className="max-w-prose text-body text-ink-muted [text-wrap:pretty]">
        No calls in the last 7 days.
        {data.calls_prev_7d > 0
          ? ` The week before had ${formatCount(data.calls_prev_7d)} ${data.calls_prev_7d === 1 ? "call" : "calls"}.`
          : ""}
        {noAgent ? " You have no agent yet, so nobody is answering or making calls." : ""}
      </p>
      {data.leads_new_7d > 0 ? (
        <div className={FIGURE_GRID}>
          <NewLeads data={data} />
        </div>
      ) : null}
    </>
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
