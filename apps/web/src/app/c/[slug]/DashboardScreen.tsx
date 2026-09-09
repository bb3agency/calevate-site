"use client";

import Link from "next/link";
import {
  Clock,
  Flame,
  Moon,
  PhoneCall,
  Sparkles,
  Users,
} from "lucide-react";

import {
  Card,
  ProblemNotice,
  Skeleton,
  StatTile,
  formatCount,
  formatDuration,
  formatINR,
} from "@/components/ui";
import { useAttention } from "@/lib/api/attention";
import { useCalls, useDashboard, useUsage } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useWallet } from "@/lib/api/wallet";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AttentionBanner } from "./AttentionBanner";
import { CallingCreditTile } from "./CallingCreditTile";
import { DailyCalls } from "./DailyCalls";
import { KnowledgeGaps } from "./KnowledgeGaps";
import { LatestCalls } from "./LatestCalls";
import { SentimentSplit } from "./SentimentSplit";

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
          ? wallet.data.prepaid
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

  /**
   * A refusal we received, or an answer that never arrived — one branch, because to the
   * owner they are the same sentence and it is not "nothing happened today".
   *
   * `|| !dashboard.data` is the half this screen was missing. `isLoading` is
   * `isPending && isFetching` (query-core `queryObserver.js`), so it is FALSE for a query
   * TanStack has PAUSED rather than started — which is what it does the moment the
   * browser is offline (`fetchStatus: canFetch(networkMode) ? "fetching" : "paused"`).
   * A paused query has `isLoading === false`, `error === null` and `data === undefined`,
   * so both guards above fell through and every tile below rendered its absence marker
   * while "No call history yet" and "No calls yet" were printed as facts about this
   * business. Same spelling as `/c/<slug>/verification` and `/c/<slug>/campaign-review`,
   * which met this first.
   */
  if (dashboard.error || !dashboard.data) {
    return (
      <ProblemNotice
        error={dashboard.error ?? new Error("Your dashboard did not load.")}
        onRetry={() => void dashboard.refetch()}
      />
    );
  }

  // Narrowed by the guard above, so nothing below has to invent a day, a mood or a
  // count: every `?? []` this screen used to carry was standing in for an answer.
  const data = dashboard.data;

  return (
    <div className="space-y-6 pb-12">
      <AttentionBanner attention={attention} href={href(`/c/${slug}/attention`)} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Calls today"
          value={formatCount(data.calls_today)}
          icon={<PhoneCall className="h-5 w-5" />}
          hint={`${formatCount(data.calls_7d)} in the last 7 days`}
        />
        {/* THE WINDOW IS PART OF THE NUMBER. This hint read "Completed calls only" over
            an average of every call the account had EVER made — a different statistic
            from the seven-day ones on either side of it, rendered identically to them.
            The API bounded it to seven days and renamed the field to say so (D-215); the
            hint is the half a client actually reads. */}
        <StatTile
          label="Average call length"
          value={formatDuration(data.avg_duration_s_7d)}
          icon={<Clock className="h-5 w-5" />}
          hint="Completed calls, last 7 days"
        />
        <StatTile
          label="New leads (7 days)"
          value={formatCount(data.leads_new_7d)}
          icon={<Users className="h-5 w-5" />}
          hint={
            <Link
              href={href(`/c/${slug}/leads`)}
              className="underline hover:text-ink"
            >
              Open leads
            </Link>
          }
        />
        <StatTile
          label="Hot leads waiting"
          value={formatCount(data.hot_leads_open)}
          icon={<Flame className="h-5 w-5" />}
          tone="strong"
          hint="Interested and not yet won or lost"
        />
      </div>

      {/* URGENT insights, above the fold: an unanswered question recurs on every future
          call, so it sits at the top across ALL the org's agents rather than only on a
          per-agent page. The card renders its own empty state, so it is always mounted —
          nothing here decides whether there is anything to show. */}
      <KnowledgeGaps />

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card title="Calls each day">
            <DailyCalls days={data.daily_7d} />
          </Card>
        </div>

        <div className="flex flex-col gap-4 lg:col-span-4">
          <StatTile
            label="Captured after hours"
            value={formatCount(data.after_hours_captured_7d)}
            icon={<Moon className="h-5 w-5" />}
            hint={
              /* WHICH definition produced the number, straight from the field the API
                 added for exactly this reason. A tile that renders "14 captured after
                 hours" identically from a fact and from a 09:00–21:00 guess invites an
                 owner to trust a number we did not earn. */
              data.after_hours_basis === "business_hours"
                ? "Using your recorded opening hours"
                : "Using 9am–9pm IST — add your opening hours for a real figure"
            }
          />
          {/* The one tile on this screen fed by a SECOND query, and the one that had no
              ladder of its own. `formatINR(undefined)` is "—", which is honest for a
              moment and a lie forever: a failed `/v1/usage` left the money tile showing
              "—" with no skeleton, no notice and no way to retry, so an owner watching
              their spend saw a dash and had no idea whether it meant "nothing yet" or
              "we could not read it". Same three states as the dashboard query beside it,
              same spelling. */}
          {usage.isLoading ? (
            <Card title="Spend this month" bodyClassName="p-4 sm:p-5">
              <Skeleton rows={2} />
            </Card>
          ) : usage.error || !usage.data ? (
            /* `|| !usage.data` for the paused case: with no error to render, this tile
               used to fall through to `formatINR(undefined)` — a "—" that an owner
               cannot tell from "you have spent nothing this month". */
            <Card title="Spend this month" bodyClassName="p-4 sm:p-5">
              <ProblemNotice
                error={usage.error ?? new Error("Your spend did not load.")}
                onRetry={() => void usage.refetch()}
              />
            </Card>
          ) : (
            <StatTile
              label="Spend this month"
              /* THE WHOLE OF WHAT THIS MONTH HAS COST THEM, not one part of it. This tile
                 printed `overage_cost_inr` — the EXTRA minutes only — under a label that
                 says "spend", so it omitted the retainer, and after D-455 it also omitted
                 the model upgrade a client pays for on every minute their own choice runs.
                 An account inside its allowance on the dearer model therefore read ₹0.00
                 here and was invoiced an "AI model upgrade" line for the same month.

                 `month_charges_inr` is the same field `/usage` prints as "Total so far"
                 and the same expression the margin panel books as revenue, so the home
                 screen, the usage screen and the invoice cannot disagree about one month.
                 It is the SERVER's sum: nothing here adds rupees. */
              value={formatINR(usage.data.month_charges_inr)}
              icon={<Sparkles className="h-5 w-5" />}
              hint={
                <Link
                  href={href(`/c/${slug}/billing?tab=usage`)}
                  className="underline hover:text-ink"
                >
                  {usage.data.minutes_used} min used of{" "}
                  {formatCount(usage.data.included_minutes)} included
                </Link>
              }
            />
          )}
          {/* CALLING CREDIT — the same three states as the tile above it, spelled the
              same way (§52), plus a fourth this one has and that one does not: an
              invoiced account, which renders nothing rather than a balance it has no
              wallet to hold. */}
          <CallingCreditTile
            wallet={wallet}
            href={href(`/c/${slug}/billing?tab=credits`)}
          />

          {/* `?? {}` here is a PAYLOAD null, not an envelope one, and the difference is
              the whole of §52: `data` is narrowed, so the only `undefined` left is the
              one `DashboardOut.sentiment_split` carries because it has a server-side
              default and Pydantic therefore generates an OPTIONAL property (the
              optional-on-the-wire trap, `tenant_erasure_routes.TenantErasureScopeOut`).
              An absent split from a response that ARRIVED means no scored calls, which is
              exactly what `SentimentSplit` renders for an empty map. */}
          <SentimentSplit split={data.sentiment_split ?? {}} />
        </div>
      </div>

      <LatestCalls
        recent={recent}
        allHref={href(`/c/${slug}/calls`)}
        callHref={(id) => href(`/c/${slug}/calls/${id}`)}
      />
    </div>
  );
}
