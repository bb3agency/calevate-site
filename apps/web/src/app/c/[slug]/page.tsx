"use client";

import Link from "next/link";
import { use } from "react";
import {
  CheckCircle2,
  Clock,
  Flame,
  Moon,
  PhoneCall,
  Sparkles,
  Users,
} from "lucide-react";

import {
  Card,
  EmptyState,
  ProblemNotice,
  Skeleton,
  StatTile,
  StatusBadge,
  formatCount,
  formatDuration,
  formatINR,
  formatIST,
} from "@/components/ui";
import type { Dashboard } from "@/lib/api/client";
import { useAttention } from "@/lib/api/attention";
import { useCalls, useDashboard, useUsage } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";
import { lookup } from "@/lib/lookup";

import { KnowledgeGaps } from "./KnowledgeGaps";

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
export default function DashboardPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const usage = useUsage(session);
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
      {/* Only when something IS waiting: a zero here is noise and renders nothing. A
          FAILED read is NOT an all-clear, though — dropping the banner silently would
          offer the client neither the action nor a reason for its absence (BUILD-LOG
          §52), so the failure says what it could not read and offers the retry. */}
      {attention.isError ? (
        <p className="rounded-card border border-line bg-surface-muted px-4 py-3 text-sm text-ink-muted">
          We could not check whether anything needs your attention.{" "}
          <button
            type="button"
            onClick={() => void attention.refetch()}
            className="font-medium text-brand-strong underline"
          >
            Try again
          </button>
        </p>
      ) : (
        attention.data &&
        attention.data.total > 0 && (
          <Link
            href={href(`/c/${slug}/attention`)}
            className="flex items-center justify-between gap-3 rounded-card border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 hover:bg-amber-100 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200 dark:hover:bg-amber-900"
          >
            <span>
              <span className="font-semibold tabular-nums">
                {formatCount(attention.data.total)}
              </span>{" "}
              {attention.data.total === 1 ? "thing needs" : "things need"} your
              attention — things we stopped on purpose, each with the reason and
              the fix.
            </span>
            <span className="shrink-0 font-medium underline">
              Open the list
            </span>
          </Link>
        )
      )}

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
                  href={href(`/c/${slug}/usage`)}
                  className="underline hover:text-ink"
                >
                  {usage.data.minutes_used} min used of{" "}
                  {formatCount(usage.data.included_minutes)} included
                </Link>
              }
            />
          )}
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

      <Card
        title="Latest calls"
        action={
          <Link
            href={href(`/c/${slug}/calls`)}
            className="rounded-md border border-line px-3 py-1.5 text-xs font-semibold text-ink-muted hover:bg-black/5 dark:hover:bg-white/5"
          >
            View all
          </Link>
        }
        bodyClassName="p-2"
      >
        {recent.isLoading ? (
          <Skeleton rows={5} />
        ) : recent.error || !recent.data ? (
          /* `!recent.data?.length` used to decide this, and `?.` collapses the two
             answers §52 keeps apart: an empty list the server sent and no answer at all
             are both falsy, so a paused query printed "No calls yet" to a client whose
             phone had simply lost signal. The refusal arm now owns both non-answers. */
          <ProblemNotice
            error={recent.error ?? new Error("The latest calls did not load.")}
            onRetry={() => void recent.refetch()}
          />
        ) : !recent.data.length ? (
          <EmptyState
            title="No calls yet"
            hint="They appear here within a couple of minutes of the call ending."
          />
        ) : (
          <ul className="divide-y divide-line">
            {recent.data.map((call) => (
              <li key={call.id}>
                <Link
                  href={href(`/c/${slug}/calls/${call.id}`)}
                  className="flex items-center gap-4 rounded-lg px-4 py-3 hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand-strong">
                    {call.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <PhoneCall className="h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    {/* IN FULL (D-436) — the recent-calls rail is the fastest route
                        from "somebody rang" to ringing them back. */}
                    <span className="block truncate text-[13px] font-semibold text-ink">
                      {call.caller_e164 ?? "Unknown number"}
                    </span>
                    <span className="block truncate text-[12px] text-ink-muted">
                      {call.agent_name ?? "—"} · {call.direction}
                    </span>
                  </span>
                  <span className="hidden sm:block">
                    <StatusBadge value={call.status} kind="call" />
                  </span>
                  <span className="w-20 shrink-0 text-right">
                    <span className="block text-[11px] font-medium text-ink-muted">
                      {formatDuration(call.duration_s)}
                    </span>
                    <span className="block text-[11px] text-ink-faint">
                      {formatIST(call.started_at)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/**
 * The seven-day stacked column chart from the design, drawn from `daily_7d`.
 *
 * The four classes PARTITION `calls.status` — the API guarantees
 * `completed + no_answer + failed + in_flight === total` on every bucket — so the
 * stack always fills its column exactly and a reader can add the segments up. The
 * colours are the ones `StatusBadge` already paints for the same statuses, so a bar
 * and a badge on the same screen never disagree about what a call was.
 *
 * Heights are relative to the busiest day rather than to a fixed "1K" axis, which is
 * what the mock drew: a client doing 20 calls a week would have seen seven invisible
 * stubs under a scale nobody told them was arbitrary. The tallest column is full
 * height and every column is labelled with its own total, so the shape is readable
 * and the numbers are checkable without a tooltip.
 *
 * Zero-height columns still render their baseline: a day with no calls is a FACT
 * about that day, and the API zero-fills for the same reason.
 */
const DAY_CLASSES = [
  { key: "completed", label: "Completed", fill: "bg-brand" },
  { key: "no_answer", label: "No answer", fill: "bg-amber-400" },
  { key: "failed", label: "Failed", fill: "bg-rose-500" },
  {
    key: "in_flight",
    label: "Still running",
    fill: "bg-slate-300 dark:bg-slate-600",
  },
] as const;

function DailyCalls({ days }: { days: Dashboard["daily_7d"] }) {
  if (!days.length) {
    return (
      <EmptyState
        title="No call history yet"
        hint="Each day appears here as it happens."
      />
    );
  }
  const busiest = Math.max(...days.map((day) => day.total));
  return (
    <div>
      {/* The four-way split existed ONLY in the bars' `title` tooltips — mouse users
          got it, keyboard and screen-reader users got nothing (ux-audit D1). The
          rendered chart is aria-hidden and this table is its text alternative; the
          numbers are the same `daily_7d` rows, not a second computation. */}
      <table className="sr-only">
        <caption>Calls each day for the last 7 days, by outcome</caption>
        <thead>
          <tr>
            <th scope="col">Day</th>
            <th scope="col">Total</th>
            {DAY_CLASSES.map((cls) => (
              <th key={cls.key} scope="col">
                {cls.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.ist_date}>
              <th scope="row">{formatDayLabel(day.ist_date)}</th>
              <td>{day.total}</td>
              {DAY_CLASSES.map((cls) => (
                <td key={cls.key}>{day[cls.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div aria-hidden="true">
        <div className="mb-6 flex flex-wrap items-center gap-4 text-xs font-medium text-ink-muted">
          {DAY_CLASSES.map((cls) => (
            <span key={cls.key} className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${cls.fill}`} />
              {cls.label}
            </span>
          ))}
        </div>

        <div className="flex h-[240px] items-end justify-between gap-2">
          {days.map((day) => (
            <div
              key={day.ist_date}
              className="flex h-full min-w-0 flex-1 flex-col items-center gap-2"
            >
              <span className="text-[11px] font-semibold tabular-nums text-ink">
                {day.total}
              </span>
              <div
                className="flex w-full max-w-[44px] flex-col-reverse overflow-hidden rounded-t-md bg-black/[0.03] dark:bg-white/5"
                style={{
                  height: `${busiest > 0 ? Math.max(2, Math.round((day.total / busiest) * 100)) : 2}%`,
                }}
                title={`${day.ist_date}: ${day.total} calls`}
              >
                {DAY_CLASSES.map((cls) => (
                  <span
                    key={cls.key}
                    className={`w-full ${cls.fill}`}
                    style={{ flexGrow: day[cls.key], flexBasis: 0 }}
                  />
                ))}
              </div>
              <span className="w-full truncate text-center text-[11px] font-medium text-ink-muted">
                {formatDayLabel(day.ist_date)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * "13 Aug" from the API's `YYYY-MM-DD`, WITHOUT constructing a Date.
 *
 * `new Date("2026-08-13")` parses as midnight UTC and then renders in the browser's
 * zone, so a client in IST sees the previous day's label over the correct day's bar.
 * The string is already an IST calendar date — the server did that work — so the only
 * correct thing to do with it is read it.
 */
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function formatDayLabel(istDate: string): string {
  const [, month, day] = istDate.split("-");
  const index = Number(month) - 1;
  return `${Number(day)} ${MONTHS[index] ?? month}`;
}

const SENTIMENT_TONES: Record<string, string> = {
  positive: "bg-brand",
  neutral: "bg-slate-300 dark:bg-slate-600",
  negative: "bg-rose-500",
};

function SentimentSplit({ split }: { split: Record<string, number> }) {
  const rows = Object.entries(split);
  const total = rows.reduce((sum, [, count]) => sum + count, 0);
  return (
    <Card title="How callers sounded" bodyClassName="p-4 sm:p-5">
      {total === 0 ? (
        <p className="text-[13px] text-ink-muted">
          We haven&apos;t rated any calls in the last 7 days yet.
        </p>
      ) : (
        <div className="space-y-2">
          {rows.map(([mood, count]) => (
            <div key={mood} className="flex items-center gap-3">
              {/* `lookup`, not `SENTIMENT_TONES[mood]`: `mood` is a server-chosen
                  string, and a bare index reaches Object.prototype (src/lib/lookup.ts).
                  The type-aware guard in tests/wireLookupGuard.test.ts failed this line
                  as written, which is the guard doing its job on new code. */}
              <span
                className={`h-2 w-2 shrink-0 rounded-full ${lookup(SENTIMENT_TONES, mood) ?? "bg-slate-300"}`}
              />
              <span className="flex-1 text-[13px] capitalize text-ink-muted">
                {mood}
              </span>
              <span className="text-[13px] font-semibold tabular-nums text-ink">
                {formatCount(count)}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
