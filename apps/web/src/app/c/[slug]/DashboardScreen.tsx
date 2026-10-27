"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { ProblemNotice, Skeleton, formatCount, formatINR } from "@/components/ui";
import { Section } from "@/components/console/section";
import { Metric } from "@/components/console/metric";
import { useAgentStats, useAgents } from "@/lib/api/agents";
import { useAnalyticsStats } from "@/lib/api/analytics";
import { useAttention } from "@/lib/api/attention";
import { useBusinessProfile } from "@/lib/api/businessProfile";
import { useCampaignNumbers, useCampaigns } from "@/lib/api/campaigns";
import { useFirstRun } from "@/lib/api/firstRun";
import { useForwarding } from "@/lib/api/forwarding";
import { useLineIncidents } from "@/lib/api/healer";
import { useCalls, useDashboard, useUsage, useWriteAccess } from "@/lib/api/hooks";
import { useKnowledgeGaps } from "@/lib/api/knowledgeGaps";
import { useAccountReadiness } from "@/lib/api/readiness";
import { useClientRealm } from "@/lib/api/session";
import { activeTrial, trialEndsAt, useWallet } from "@/lib/api/wallet";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AgentsAtAGlance } from "./AgentsAtAGlance";
import { CallingCreditTile } from "./CallingCreditTile";
import { DailyCalls } from "./DailyCalls";
import { FirstAgentInvite } from "./FirstAgentInvite";
import { HeldNumberNotice } from "./HeldNumberNotice";
import { LatestCalls } from "./LatestCalls";
import { LineNotice } from "./LineNotice";
import { OutcomeSplit } from "./OutcomeSplit";
import { ReadinessPanel } from "./ReadinessPanel";
import { SentimentSplit } from "./SentimentSplit";
import { SetupChecklist } from "./SetupChecklist";
import { SpendThisMonth } from "./SpendThisMonth";
import { GoLiveInvite } from "./GoLiveInvite";
import { TrialCallPanel } from "./TrialCallPanel";
import { WhatNeedsYou } from "./WhatNeedsYou";
import { WeekRecap } from "./WeekRecap";
import { ExistingNumberPrompt } from "@/components/forwarding/ExistingNumberPrompt";

/**
 * The client's home screen.
 *
 * EVERY NUMBER ON THIS PAGE COMES FROM THE API OR IS NOT SHOWN. That is the rule the
 * design pass has to survive, and it is not a style preference: the mock this was
 * built from carried a hardcoded "3,482 successful calls", a "$0.042 cost per call",
 * a seven-day chart of invented bars and an activity feed of American phone numbers,
 * and the previous wiring fell back to `?? 5430` when the request failed — so a
 * client whose calls had STOPPED would have seen a healthy dashboard. A number that
 * is sometimes real and sometimes decorative is worse than a blank: it teaches the
 * owner to trust the screen, and then lies to them on the one day it matters.
 *
 * The tiles the design asked for that the API cannot answer are ABSENT rather than
 * approximated — cost per call, active campaigns, booked appointments, conversion
 * rate. Each is a real question and each needs an endpoint; `docs/BUILD-LOG.md` records
 * which. The week-on-week change under each figure is the server's (`/v1/analytics/stats`).
 */

export function DashboardScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const usage = useUsage(session);
  // A held number (D-860): calls to it have stopped and it is released on a date.
  const numbers = useCampaignNumbers(session);
  /*
   * THE BALANCE, on the screen a client opens first.
   *
   * The home screen showed what this month has COST and nothing about what is left to
   * spend, which was the right pair of facts while every account was invoiced against a
   * retainer and no balance could stop anything. Prepaid is now what an account gets
   * unless an operator deliberately puts it on a retainer, so the number that decides
   * whether the product works tomorrow was the one number missing from the daily entry
   * point — and the first a client learns of an empty wallet should not be a campaign
   * that did not go out.
   *
   * `wallet:read`, which every client role holds including `staff` (`core/rbac.py`), so
   * this tile does not fetch something half the team is refused. An INVOICED account
   * renders nothing at all rather than ₹0.00: it has no wallet, and a zero would be a
   * number about nothing.
   */
  const wallet = useWallet(session);
  const trial = activeTrial(wallet.data);
  const recent = useCalls(session, { limit: 6 });
  // The triage queue's size — same query key the header bell reads, so this costs no
  // extra request. The dashboard is the daily entry point and used to never link to
  // the one list with a time cost attached to ignoring it (ux-audit D2). Renders
  // nothing until the server answers, and nothing on zero — exactly as the bell does.
  const attention = useAttention(session);
  const agents = useAgents(session);
  const agentStats = useAgentStats(session);
  // Last 7 IST days against the 7 before, the server's default window.
  const stats = useAnalyticsStats(session);
  const readiness = useAccountReadiness(session);
  // "This week" offers only the actions this reader may take; the endpoints still refuse.
  const campaigns = useCampaigns(session);
  const creditAccess = useWriteAccess(session, "org:manage", "add credit");
  const agentAccess = useWriteAccess(session, "org:manage", "create an agent");
  // A NEW OWNER MEETS THEIR AGENT FIRST (D-855). The sign-in junction sends a due first run
  // there, but an owner can reach the dashboard without passing it (a bookmark, a link in an
  // email, the address typed), so the dashboard asks too. Only a run never started is sent
  // on: an owner who began it and came back here chose to, and the invitation below offers
  // it again; one who put it aside is no longer due.
  const router = useRouter();
  const firstRunAsked = agents.data?.length === 0 && agentAccess.allowed && !session.impersonateOrg;
  const firstRun = useFirstRun(session, firstRunAsked);
  const firstRunDue = firstRunAsked && firstRun.data?.due === true;
  const firstRunUnstarted = firstRunDue && firstRun.data?.jobs.length === 0;
  useEffect(() => {
    if (firstRunUnstarted) router.replace(href(`/c/${slug}/agents/first`));
  }, [firstRunUnstarted, router, href, slug]);
  const campaignAccess = useWriteAccess(session, "leads:dispatch", "start or run campaigns");
  /*
   * THE NOTICES' READS START WITH THE DASHBOARD'S, not after it. The line notice, the setup
   * checklist, the existing-number prompt and the unanswered-questions row each read their
   * own query, and each mounts only once the dashboard has answered; left to themselves,
   * their requests would leave a round trip late and each card would push the page down.
   * Calling the same hooks here (same keys, so no second request) starts them in parallel,
   * and the skeleton below waits for them, so the page arrives in one paint. A failed
   * notice read does not hold the page: only a read still in flight does.
   */
  const gaps = useKnowledgeGaps(session, { status: "open", limit: 20 });
  const notices = [useLineIncidents(session), useBusinessProfile(session), useForwarding(session), gaps];

  /*
   * THIS SCREEN, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * DECLARED BEFORE THE §52 BRANCHES BELOW, not inside the happy path: `useCopilotSurface`
   * is a hook, and the three early returns on this screen would make its call conditional.
   * The declaration therefore has to describe a screen that may still be loading, which is
   * what the `state` fact is for — an assistant told "your dashboard says 0 calls today"
   * while the request is still in flight has been handed the same lie the docstring above
   * refuses to render.
   *
   * NOTHING PERSONAL IS DECLARABLE HERE. Every tile on this screen is a count, a duration
   * or a rupee total; the only strings that could name a person are inside "Latest calls",
   * and this surface sends the LENGTH of that list rather than any row of it.
   */
  useCopilotSurface({
    route: "/c/{slug}",
    title: "Your dashboard",
    realm: "client",
    fields: [],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value: dashboard.data
          ? "the figures below have loaded"
          : dashboard.error
            ? "the dashboard failed to load, so no figure is on screen"
            : "still loading",
      },
      {
        /* THE TILE THE ASSISTANT WOULD OTHERWISE BE BLIND TO, and the one most likely to
           be asked about by somebody whose campaigns have stopped. Read off the same
           query the tile renders, so the two cannot disagree. */
        key: "calling_credit",
        label: "Calling credit on this account",
        value: wallet.data
          ? trial !== null && trial.test_calls_only
            ? `the account is on a free trial until ${trialEndsAt(trial)}: it can place test calls from the dashboard, and adding credit ends the trial and opens business verification, its own number and live calls`
            : trial !== null
            ? `${wallet.data.prepaid ? `${formatINR(wallet.data.balance_inr)} left; ` : ""}the account is on a free trial until ${trialEndsAt(trial)}, so calls are on us, nothing is taken from the credit, and an empty balance stops no calls`
            : wallet.data.prepaid
            ? `${formatINR(wallet.data.balance_inr)} left${
                wallet.data.outbound_stopped
                  ? " — outgoing calls have stopped and the agents are no longer answering incoming ones; adding credit starts both again straight away"
                  : wallet.data.is_low
                    ? " — running low"
                    : ""
              }`
            : "this account is invoiced on a retainer and has no credit balance"
          : wallet.error
            ? "the balance failed to load"
            : "still loading",
      },
      ...(dashboard.data
        ? [
            { key: "calls_today", label: "Calls today", value: String(dashboard.data.calls_today) },
            { key: "calls_7d", label: "Calls in the last 7 days", value: String(dashboard.data.calls_7d) },
            { key: "calls_prev_7d", label: "Calls in the 7 days before that", value: String(dashboard.data.calls_prev_7d) },
            {
              key: "avg_duration_s_7d",
              label: "Average completed call length, last 7 days (seconds)",
              value: dashboard.data.avg_duration_s_7d == null ? "not measurable yet" : String(dashboard.data.avg_duration_s_7d),
            },
            { key: "leads_new_7d", label: "New leads in the last 7 days", value: String(dashboard.data.leads_new_7d) },
            { key: "leads_new_prev_7d", label: "New leads in the 7 days before that", value: String(dashboard.data.leads_new_prev_7d) },
            { key: "hot_leads_open", label: "Hot leads waiting", value: String(dashboard.data.hot_leads_open) },
            {
              key: "after_hours_captured_7d",
              label: "Captured after hours, last 7 days",
              value: String(dashboard.data.after_hours_captured_7d),
            },
            {
              key: "after_hours_basis",
              label: "How after-hours is decided",
              value:
                dashboard.data.after_hours_basis === "business_hours"
                  ? "the recorded opening hours"
                  : "the 9am-9pm IST default, because no opening hours are recorded",
            },
            {
              key: "sentiment_split",
              label: "Sentiment split of scored calls",
              value:
                Object.entries(dashboard.data.sentiment_split ?? {})
                  .map(([mood, count]) => `${mood}: ${count}`)
                  .join(", ") || "no calls scored yet",
            },
          ]
        : []),
      ...(attention.data
        ? [
            {
              key: "attention_total",
              label: "Things waiting on the attention queue",
              value: String(attention.data.total),
            },
          ]
        : []),
      ...(usage.data
        ? [
            { key: "month_charges_inr", label: "Charges this month (INR)", value: usage.data.month_charges_inr },
            { key: "minutes_used", label: "Minutes used this month", value: usage.data.minutes_used },
            { key: "included_minutes", label: "Minutes included in the plan", value: String(usage.data.included_minutes) },
          ]
        : []),
      {
        key: "recent_calls_shown",
        label: "Rows in the Latest calls panel",
        value: recent.data ? String(recent.data.length) : "not loaded",
      },
    ],
    apply: noFill,
  });

  if (dashboard.isLoading || notices.some((notice) => notice.isLoading)) {
    return (
      <div className="space-y-6">
        <Skeleton rows={4} />
        <Skeleton rows={8} />
      </div>
    );
  }

  /*
   * A refusal we received, or an answer that never arrived — one branch, because to the
   * owner they are the same sentence and it is not "nothing happened today". `!data`
   * covers a query TanStack has PAUSED (offline): not loading, no error, no data.
   */
  if (dashboard.error || !dashboard.data) {
    return (
      <ProblemNotice
        error={dashboard.error ?? new Error("Your dashboard did not load.")}
        onRetry={() => void dashboard.refetch()}
      />
    );
  }

  const data = dashboard.data;

  return (
    <div className="space-y-10 pb-12">
      {/* What needs the owner first: notices, setup and the trial, each rendering nothing
          when there is nothing to say. */}
      <div className="space-y-4 empty:hidden">
        <LineNotice session={session} href={href(`/c/${slug}/settings/line-protection`)} />
        {numbers.isError ? (
          <p className="rounded-md bg-surface-muted px-4 py-3 text-body text-ink-muted">
            We could not check whether your phone numbers are answering.
          </p>
        ) : numbers.data ? (
          <HeldNumberNotice numbers={numbers.data} topUpHref={href(`/c/${slug}/billing?tab=credits`)} />
        ) : null}
        {agents.data?.length === 0 && agentAccess.allowed ? (
          <FirstAgentInvite href={(path) => href(`/c/${slug}${path}`)} started={firstRunDue && !firstRunUnstarted} />
        ) : null}
        <GoLiveInvite session={session} href={(path) => href(`/c/${slug}${path}`)} />
        {/* The business checklist waits while the first agent is still to meet: the owner's
            first job is the agent, and eight unticked rows under it read as homework. */}
        {firstRunDue ? null : <SetupChecklist />}
        <ExistingNumberPrompt session={session} href={href} />
        <TrialCallPanel slug={slug} trial={data.trial} />
      </div>

      {/* FIRST, WHAT TO ACT ON (founder, REDESIGN-2): the queue, hot leads, calls that
          did not connect, unanswered questions and credit — before any figure. Each fact
          on this page is said once: hot leads and the struggled count live here, the
          figures in "This week", each agent's state in "Your agents". */}
      <WhatNeedsYou
        data={data}
        attention={attention}
        wallet={wallet}
        gaps={gaps}
        href={(path) => href(`/c/${slug}${path}`)}
      />

      {/* The page's one block of figures, and what to do next. */}
      <WeekRecap
        data={data}
        stats={stats}
        agents={agents.data}
        wallet={wallet.data}
        campaigns={campaigns.data}
        access={{
          addCredit: creditAccess.allowed,
          createAgent: agentAccess.allowed,
          runCampaigns: campaignAccess.allowed,
        }}
        href={(path) => href(`/c/${slug}${path}`)}
      />

      <div className="grid grid-cols-1 items-start gap-10 page-lg:grid-cols-12 page-lg:gap-12">
        <div className="space-y-10 page-lg:col-span-8">
          <AgentsAtAGlance
            agents={agents}
            stats={agentStats}
            onTrial={data.trial?.on_trial === true}
            href={(path) => href(`/c/${slug}${path}`)}
          />
          <Section title="Calls each day">
            <DailyCalls days={data.daily_7d} />
          </Section>
          <OutcomeSplit split={data.outcome_split ?? {}} />
          <LatestCalls
            recent={recent}
            allHref={href(`/c/${slug}/calls`)}
            callHref={(id) => href(`/c/${slug}/calls/${id}`)}
          />
        </div>

        <div className="space-y-10 page-lg:col-span-4">
          <ReadinessPanel readiness={readiness} href={(path) => href(`/c/${slug}${path}`)} />
          {/* MONEY — what is left to spend, then what this month has cost. Each read has
              its own loading and failure arm (§52); a failed read is never a dash. */}
          <Section title="Credit and spend">
            <div className="divide-y divide-line border-y border-line">
              <CallingCreditTile wallet={wallet} href={href(`/c/${slug}/billing?tab=credits`)} />
              <SpendThisMonth usage={usage} href={href(`/c/${slug}/billing?tab=usage`)} />
              {/* WHICH definition produced the after-hours number, from the field the API
                  added for exactly this reason: a guess and a fact must not read the same. */}
              <Metric
                className="py-4"
                label="Captured after hours"
                value={formatCount(data.after_hours_captured_7d)}
                flashValue={String(data.after_hours_captured_7d)}
                hint={
                  data.after_hours_basis === "business_hours"
                    ? "Using your recorded opening hours"
                    : "Using 9am–9pm IST — add your opening hours for a real figure"
                }
              />
            </div>
          </Section>
          {/* `?? {}` is a PAYLOAD default, not an envelope one: `data` is narrowed above,
              and `sentiment_split` is optional on the wire because it has a server-side
              default. An absent split from a response that arrived means none scored. */}
          <Section title="How callers sounded">
            <SentimentSplit split={data.sentiment_split ?? {}} />
          </Section>
        </div>
      </div>
    </div>
  );
}
