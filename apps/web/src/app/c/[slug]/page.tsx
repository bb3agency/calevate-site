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
import { useCalls, useDashboard, useUsage } from "@/lib/api/hooks";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

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
export default function DashboardPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const { session, href } = useClientRealm();
  const dashboard = useDashboard(session);
  const usage = useUsage(session);
  const recent = useCalls(session, { limit: 6 });

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
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Calls today"
          value={formatCount(data.calls_today)}
          icon={<PhoneCall className="h-5 w-5" />}
          hint={`${formatCount(data.calls_7d)} in the last 7 days`}
        />
        <StatTile
          label="Average call length"
          value={formatDuration(data.avg_duration_s)}
          icon={<Clock className="h-5 w-5" />}
          hint="Completed calls only"
        />
        <StatTile
          label="New leads (7 days)"
          value={formatCount(data.leads_new_7d)}
          icon={<Users className="h-5 w-5" />}
          hint={
            <Link href={href(`/c/${slug}/leads`)} className="underline hover:text-ink">
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

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card title="Calls each day" bodyClassName="p-6">
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
            <Card title="Spend this month" bodyClassName="p-5">
              <Skeleton rows={2} />
            </Card>
          ) : usage.error || !usage.data ? (
            /* `|| !usage.data` for the paused case: with no error to render, this tile
               used to fall through to `formatINR(undefined)` — a "—" that an owner
               cannot tell from "you have spent nothing this month". */
            <Card title="Spend this month" bodyClassName="p-5">
              <ProblemNotice
                error={usage.error ?? new Error("Your spend did not load.")}
                onRetry={() => void usage.refetch()}
              />
            </Card>
          ) : (
            <StatTile
              label="Spend this month"
              value={formatINR(usage.data.overage_cost_inr)}
              icon={<Sparkles className="h-5 w-5" />}
              hint={`${usage.data.minutes_used} min used of ${formatCount(usage.data.included_minutes)} included`}
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
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-soft text-brand">
                    {call.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <PhoneCall className="h-4 w-4" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    {/* MASKED, always. `caller_masked` is what the API sends and the
                        only thing this screen is allowed to render (hard rule 6) —
                        the mock printed full numbers here. */}
                    <span className="block truncate text-[13px] font-semibold text-ink">
                      {call.caller_masked ?? "Unknown number"}
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
  { key: "in_flight", label: "Still running", fill: "bg-slate-300 dark:bg-slate-600" },
] as const;

function DailyCalls({ days }: { days: Dashboard["daily_7d"] }) {
  if (!days.length) {
    return <EmptyState title="No call history yet" hint="Each day appears here as it happens." />;
  }
  const busiest = Math.max(...days.map((day) => day.total));
  return (
    <div>
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
          <div key={day.ist_date} className="flex h-full min-w-0 flex-1 flex-col items-center gap-2">
            <span className="text-[11px] font-semibold tabular-nums text-ink">{day.total}</span>
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
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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
    <Card title="How callers sounded" bodyClassName="p-5">
      {total === 0 ? (
        <p className="text-[13px] text-ink-muted">No scored calls in the last 7 days yet.</p>
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
              <span className="flex-1 text-[13px] capitalize text-ink-muted">{mood}</span>
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
