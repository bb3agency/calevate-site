"use client";

import Link from "next/link";

import { Card, ProblemNotice, Skeleton, formatCount, formatDuration } from "@/components/ui";
import { Metric } from "@/components/console/metric";
import { useAttention } from "@/lib/api/attention";
import { useCalls, useDashboard, useUsage } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { activeTrial, trialEndsAt, useWallet } from "@/lib/api/wallet";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AttentionBanner } from "./AttentionBanner";
import { CallingCreditTile } from "./CallingCreditTile";
import { DailyCalls } from "./DailyCalls";
import { KnowledgeGaps } from "./KnowledgeGaps";
import { LatestCalls } from "./LatestCalls";
import { SentimentSplit } from "./SentimentSplit";
import { SpendThisMonth } from "./SpendThisMonth";

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
 * rate, and the "+18.4% vs last week" deltas under every figure. Each is a real
 * question and each needs an endpoint; `docs/BUILD-LOG.md` records which.
 */

export function DashboardScreen({ slug }: { slug: string }) {
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const usage = useUsage(session);
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
          ? trial !== null
            ? `${wallet.data.prepaid ? `${wallet.data.balance_inr} INR left; ` : ""}the account is on a free trial until ${trialEndsAt(trial)}, so calls are on us, nothing is taken from the credit, and an empty balance stops no calls`
            : wallet.data.prepaid
            ? `${wallet.data.balance_inr} INR left${
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
            {
              key: "avg_duration_s_7d",
              label: "Average completed call length, last 7 days (seconds)",
              value: dashboard.data.avg_duration_s_7d == null ? "not measurable yet" : String(dashboard.data.avg_duration_s_7d),
            },
            { key: "leads_new_7d", label: "New leads in the last 7 days", value: String(dashboard.data.leads_new_7d) },
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

  if (dashboard.isLoading) {
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
    <div className="space-y-4 pb-12 lg:space-y-5">
      <AttentionBanner attention={attention} href={href(`/c/${slug}/attention`)} />

      {/* THE DAY AT A GLANCE — four figures in one strip, each marking itself when a poll
          changes it. */}
      <section
        aria-label="Today at a glance"
        className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line shadow-card md:grid-cols-4"
      >
        <Metric
          className="bg-surface p-4 sm:p-5"
          label="Calls today"
          value={formatCount(data.calls_today)}
          flashValue={String(data.calls_today)}
          hint={`${formatCount(data.calls_7d)} in the last 7 days`}
        />
        {/* The window is part of the number: a seven-day average of COMPLETED calls
            (D-215), said in the hint so it is not read as an all-time figure. */}
        <Metric
          className="bg-surface p-4 sm:p-5"
          label="Average call length"
          value={formatDuration(data.avg_duration_s_7d)}
          flashValue={data.avg_duration_s_7d == null ? null : String(data.avg_duration_s_7d)}
          hint="Completed calls, last 7 days"
        />
        <Metric
          className="bg-surface p-4 sm:p-5"
          label="New leads (7 days)"
          value={formatCount(data.leads_new_7d)}
          flashValue={String(data.leads_new_7d)}
          hint={
            <Link href={href(`/c/${slug}/leads`)} className="underline decoration-ink/30 underline-offset-2 hover:text-ink">
              Open leads
            </Link>
          }
        />
        <Metric
          className="bg-surface p-4 sm:p-5"
          label="Hot leads waiting"
          value={formatCount(data.hot_leads_open)}
          flashValue={String(data.hot_leads_open)}
          hint="Interested and not yet won or lost"
        />
      </section>

      {/* An unanswered question recurs on every future call until it is taught, so it
          sits high, across ALL the org's agents. It renders its own empty state. */}
      <KnowledgeGaps />

      <div className="grid items-start gap-4 lg:grid-cols-12 lg:gap-5">
        <div className="space-y-4 lg:col-span-8 lg:space-y-5">
          <Card density="compact" title="Calls each day">
            <DailyCalls days={data.daily_7d} />
          </Card>
          <LatestCalls
            recent={recent}
            allHref={href(`/c/${slug}/calls`)}
            callHref={(id) => href(`/c/${slug}/calls/${id}`)}
          />
        </div>

        <div className="space-y-4 lg:col-span-4 lg:space-y-5">
          {/* MONEY — what is left to spend, then what this month has cost. Each read has
              its own loading and failure arm (§52); a failed read is never a dash. */}
          <section
            aria-label="Credit and spend"
            className="divide-y divide-line rounded-card border border-line bg-surface shadow-card"
          >
            <CallingCreditTile wallet={wallet} href={href(`/c/${slug}/billing?tab=credits`)} />
            <SpendThisMonth usage={usage} href={href(`/c/${slug}/billing?tab=usage`)} />
          </section>
          {/* WHICH definition produced the after-hours number, from the field the API
              added for exactly this reason: a guess and a fact must not read the same. */}
          <div className="rounded-card border border-line bg-surface p-4 shadow-card sm:p-5">
            <Metric
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
          {/* `?? {}` is a PAYLOAD default, not an envelope one: `data` is narrowed above,
              and `sentiment_split` is optional on the wire because it has a server-side
              default. An absent split from a response that arrived means none scored. */}
          <SentimentSplit split={data.sentiment_split ?? {}} />
        </div>
      </div>
    </div>
  );
}
