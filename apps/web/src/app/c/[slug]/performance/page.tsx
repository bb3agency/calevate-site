"use client";

import { useState } from "react";
import { Clock, PhoneCall, PhoneIncoming, UserCheck } from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  ProblemNotice,
  RestrictionNote,
  ScrollRegion,
  Skeleton,
  StatTile,
  formatCount,
  formatDuration,
} from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { usePerformance, type Performance } from "@/lib/api/performance";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/**
 * How the phone agent is doing (SURFACES §2), in the console's design language.
 *
 * Restyled onto the `globals.css` tokens and the shared primitives — no `slate-*`, no
 * `bg-white`, no second segmented control where `FilterChip` already exists — WITHOUT
 * changing what it fetches or what any number means. What did change is what the screen
 * claims:
 *
 * - **It rendered its own `<h1>Performance</h1>`** while the shell prints the page title
 *   from the nav list (layout.tsx). Two headings saying the same word is the visible half
 *   of a drift: rename the nav entry and the screen keeps arguing with it.
 * - **`if (!perf.data) return null`** painted a blank screen with nothing on it — no
 *   skeleton, no notice, no explanation. Now: a skeleton while there is nothing yet, the
 *   refusal when the request failed, and the numbers only when the server sent them.
 * - **A failed REFETCH used to blank the screen too.** `usePerformance` keeps the
 *   previous period's data (`keepPreviousData`), and those numbers are real, so the
 *   notice renders ABOVE them rather than instead of them — the same shape the leads
 *   table settled on.
 * - **The period toggle and the period the numbers are FOR could disagree.** The chips
 *   say what was asked for the instant it is clicked; every caption says `data.days`,
 *   which is what the server actually measured, and the card says "Updating…" while the
 *   two differ. A "last 90 days" heading over 30 days of numbers is a lie a reader has
 *   no way to catch.
 *
 * The charts follow the dashboard's doctrine (`/c/[slug]/page.tsx`): heights are relative
 * to the busiest bucket rather than to an invented axis, every bar prints its own number
 * so the picture is checkable without a tooltip, and a silent bucket renders as a zero
 * rather than being dropped — the API guarantees all 24 IST hours for that reason.
 */

const DAY_OPTIONS = [7, 30, 90] as const;

export default function PerformancePage() {
  const session = useClientSession();
  const [days, setDays] = useState<number>(30);
  const perf = usePerformance(session, days);
  const me = useMe(session);

  /**
   * `GET /v1/performance` requires `calls:read` (crm/routes.py), read off `/v1/me`
   * rather than from a role list this build would have to keep in step with the server.
   *
   * A session without it gets the sentence instead of a red alert: a 403 we can see
   * coming is not a fault, and rendering it as one teaches a client to report their own
   * permissions as bugs (the doctrine the leads Export button follows). While `/v1/me`
   * is in flight `me.data` is undefined and nothing is refused — a screen must not flash
   * an explanation it is about to withdraw. If `/v1/me` itself failed we do not know, so
   * the request goes out and the API's own answer is what renders.
   */
  /*
   * THE REPORT, DECLARED TO THE ASSISTANT (`lib/copilot/registry.ts`).
   *
   * THE PERIOD IS WRITABLE — "how did last quarter go" is a re-filter, and it is the only
   * control on the screen. Its options are `DAY_OPTIONS`, which is what the chips render
   * from, so the assistant cannot ask for a window this screen has no chip for.
   *
   * EVERY FIGURE IS THE SERVER'S, and `data.days` rather than `days` names the period the
   * numbers actually cover: the two differ for as long as a switch is in flight, which is
   * exactly when a reader — or an assistant quoting one — would be misled.
   *
   * `null` IS SENT AS "no calls to measure", never as 0. The server draws that
   * distinction on purpose (`PerformanceOut`), and collapsing it here would have the
   * assistant tell a brand-new client their agent is failing before it has rung once.
   */
  useCopilotSurface({
    route: "/c/{slug}/performance",
    title: "How your agent is doing",
    realm: "client",
    fields: [
      {
        id: "performance-days",
        label: "Period, in days",
        type: "select",
        value: String(days),
        options: DAY_OPTIONS.map((option) => ({ value: String(option), label: `${option} days` })),
      },
    ],
    facts: [
      {
        key: "state",
        label: "What is on screen",
        value:
          me.data !== undefined && !me.data.permissions.includes("calls:read")
            ? "a refusal — this session may not read call records, so no figure is shown"
            : perf.data
              ? "the figures below have loaded"
              : perf.error
                ? "the figures failed to load"
                : "still loading",
      },
      ...(perf.data
        ? [
            { key: "days_measured", label: "Days the figures actually cover", value: String(perf.data.days) },
            { key: "calls", label: "Calls in the period", value: String(perf.data.funnel.calls) },
            { key: "connected", label: "Of those, connected", value: String(perf.data.funnel.connected) },
            { key: "qualified", label: "Leads qualified (lead-level, not call-level)", value: String(perf.data.funnel.qualified) },
            {
              key: "connect_rate_pct",
              label: "Connect rate (%)",
              value: perf.data.connect_rate_pct === null ? "no calls to measure" : String(perf.data.connect_rate_pct),
            },
            {
              key: "qualify_rate_pct",
              label: "Qualify rate (%)",
              value: perf.data.qualify_rate_pct === null ? "no calls to measure" : String(perf.data.qualify_rate_pct),
            },
            {
              key: "avg_duration_s",
              label: "Average call length (seconds)",
              value: perf.data.avg_duration_s === null ? "no completed calls to measure" : String(perf.data.avg_duration_s),
            },
            { key: "inbound", label: "Inbound calls", value: String(perf.data.inbound) },
            { key: "outbound", label: "Outbound calls", value: String(perf.data.outbound) },
            {
              key: "outcomes",
              label: "How calls ended",
              value:
                Object.entries(perf.data.outcomes)
                  .map(([outcome, count]) => `${outcome}: ${count}`)
                  .join(", ") || "nothing recorded",
            },
            {
              key: "busiest_hour_ist",
              label: "Busiest hour, IST (24 buckets, index = hour)",
              // The empty-array case is handled BEFORE the spread rather than after it:
              // `Math.max()` of nothing is -Infinity, which `indexOf` then misses and
              // renders as "undefined call(s)". The endpoint documents 24 buckets always;
              // a declaration must not be the thing that crashes or lies if it sends none.
              value: (() => {
                const hours = perf.data.busiest_hours_ist;
                const busiest = hours.length === 0 ? 0 : Math.max(...hours);
                if (busiest === 0) return "no calls in any hour";
                return `${hours.indexOf(busiest)}:00 with ${busiest} call(s)`;
              })(),
            },
          ]
        : []),
    ],
    apply: (items) => {
      for (const item of items) {
        if (item.field_id !== "performance-days") continue;
        const wanted = DAY_OPTIONS.find((option) => String(option) === asText(item.value));
        if (wanted !== undefined) setDays(wanted);
      }
    },
  });

  const refused = me.data !== undefined && !me.data.permissions.includes("calls:read");
  if (refused) {
    return (
      <RestrictionNote reason="Call reports need permission to read call records, which this account does not have. Ask your account owner for access." />
    );
  }

  const data = perf.data;

  return (
    <div className="space-y-5 pb-12">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          {/* `data.days` — the period the SERVER measured, never the one the chip asked
              for. They differ for as long as a switch is in flight, and that is exactly
              when a reader would be misled. */}
          {data
            ? `How your phone agent did over the last ${data.days} days.`
            : "How your phone agent did."}
        </p>
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Time period">
          {DAY_OPTIONS.map((option) => (
            <FilterChip
              key={option}
              label={`${option} days`}
              active={days === option}
              onClick={() => setDays(option)}
            />
          ))}
        </div>
      </div>

      {perf.error && <ProblemNotice error={perf.error} onRetry={() => void perf.refetch()} />}

      {!data ? (
        /* Nothing to draw. A skeleton is not a number, and a failed first load has
           already said so in the notice above — neither branch is allowed to invent a
           figure to fill the space. */
        perf.error ? null : (
          <div className="space-y-5">
            <Skeleton rows={4} />
            <Skeleton rows={6} />
          </div>
        )
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {/* null vs 0% is a distinction the server makes ON PURPOSE (PerformanceOut):
                0% means calls happened and none turned into conversations — bad news
                worth showing — while null means there were no calls at all and there is
                nothing to grade. Collapsing both into "0%" tells a new client their
                agent is failing before it has rung once. */}
            <StatTile
              label="Calls answered"
              value={ratePct(data.connect_rate_pct) ?? "—"}
              icon={<PhoneCall className="h-5 w-5" />}
              hint={
                data.connect_rate_pct === null || data.connect_rate_pct === undefined
                  ? "No calls yet — nothing to measure"
                  : `${formatCount(data.funnel.connected)} of ${formatCount(data.funnel.calls)} reached a real conversation`
              }
            />
            <StatTile
              label="Turned into leads"
              value={ratePct(data.qualify_rate_pct) ?? "—"}
              icon={<UserCheck className="h-5 w-5" />}
              tone="strong"
              hint={
                data.qualify_rate_pct === null || data.qualify_rate_pct === undefined
                  ? "No answered calls yet — nothing to measure"
                  : "of answered calls became interested customers"
              }
            />
            <StatTile
              label="Average call length"
              value={formatDuration(data.avg_duration_s)}
              icon={<Clock className="h-5 w-5" />}
              hint="Completed calls only"
            />
            <StatTile
              label="Incoming / outgoing"
              value={`${formatCount(data.inbound)} / ${formatCount(data.outbound)}`}
              icon={<PhoneIncoming className="h-5 w-5" />}
              hint="Calls received vs calls made"
            />
          </div>

          <div className="grid gap-5 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <Card title="From calls to customers" action={<Updating busy={perf.isFetching} />}>
                <Funnel funnel={data.funnel} />
              </Card>
            </div>
            <div className="lg:col-span-5">
              <Card title="How calls ended" action={<Updating busy={perf.isFetching} />}>
                <Outcomes outcomes={data.outcomes} />
              </Card>
            </div>
          </div>

          <Card title="Busiest hours (IST)" action={<Updating busy={perf.isFetching} />}>
            <HourHistogram hours={data.busiest_hours_ist} calls={data.funnel.calls} />
          </Card>
        </>
      )}
    </div>
  );
}

/**
 * A whole-number percentage, or null when the server said there is nothing to measure.
 *
 * `=== null` alone would let an `undefined` — a field the response omitted — render as
 * "undefined%", which is the one output worse than a wrong number.
 */
function ratePct(value: number | null | undefined): string | null {
  return value === null || value === undefined ? null : `${value}%`;
}

/** Said, rather than left for the reader to notice numbers moving under them. */
function Updating({ busy }: { busy: boolean }) {
  if (!busy) return null;
  return <span className="text-[11px] font-medium text-ink-faint">Updating…</span>;
}

/**
 * Calls → answered → interested, as three bars against the top of the funnel.
 *
 * Widths are a share of `calls`, so the bars are read against each other rather than
 * against an axis nobody drew — and each prints its own count, so the shape can be
 * checked without hovering anything. A non-zero stage keeps a 2% floor: "3 of 900" must
 * still be visible, and a stage that exists must not render as one that does not.
 */
const FUNNEL_SHADES = ["bg-brand-strong", "bg-brand", "bg-brand-bright"] as const;

function Funnel({ funnel }: { funnel: Performance["funnel"] }) {
  if (funnel.calls === 0) {
    return (
      <EmptyState
        title="No calls in this period"
        hint="Once your agent starts taking or making calls, you will see them here."
      />
    );
  }
  const stages = [
    { label: "Calls", count: funnel.calls },
    { label: "Answered", count: funnel.connected },
    { label: "Interested", count: funnel.qualified },
  ];
  return (
    <div className="space-y-3">
      {stages.map((stage, index) => (
        <div key={stage.label} className="flex items-center gap-3">
          <div className="w-20 shrink-0 text-sm text-ink-muted">{stage.label}</div>
          <div className="h-6 flex-1 overflow-hidden rounded-md bg-black/[0.04] dark:bg-white/10">
            <div
              className={`h-full rounded-md ${FUNNEL_SHADES[index]}`}
              style={{
                width: `${stage.count > 0 ? Math.max((stage.count / funnel.calls) * 100, 2) : 0}%`,
              }}
              title={`${stage.label}: ${stage.count}`}
            />
          </div>
          <div className="w-14 shrink-0 text-right text-sm font-semibold tabular-nums text-ink">
            {formatCount(stage.count)}
          </div>
        </div>
      ))}
      <p className="text-xs text-ink-muted">
        Answered means the call reached a real conversation — not voicemail or a missed
        call. Interested counts customers, not calls: three calls to the same person count
        once.
      </p>
    </div>
  );
}

/**
 * Outcome → count, busiest first.
 *
 * The key is the agent's outcome tag where it set one and the call's own status where it
 * did not (`COALESCE(outcome_tag, status)` in crm/performance.py), which is why the
 * caption says so: a reader who thinks these are all tags will read "no_answer" as an
 * outcome someone chose.
 *
 * No `lookup()` needed — these keys are printed, never used to index a copy table, which
 * is the read `src/lib/lookup.ts` exists to make safe.
 */
function Outcomes({ outcomes }: { outcomes: Record<string, number> }) {
  const rows = Object.entries(outcomes).sort(([, a], [, b]) => b - a);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing to show yet"
        hint="Call results will appear here after your first calls."
      />
    );
  }
  const busiest = Math.max(...rows.map(([, count]) => count));
  return (
    <div className="space-y-2.5">
      {rows.map(([outcome, count]) => (
        <div key={outcome}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[13px] capitalize text-ink-muted">
              {outcome.replace(/_/g, " ")}
            </span>
            <span className="text-[13px] font-semibold tabular-nums text-ink">
              {formatCount(count)}
            </span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/[0.04] dark:bg-white/10">
            <div
              className="h-full rounded-full bg-brand"
              style={{ width: `${busiest > 0 ? Math.max((count / busiest) * 100, 2) : 0}%` }}
            />
          </div>
        </div>
      ))}
      <p className="pt-1 text-xs text-ink-muted">
        The tag your agent recorded, or how the call ended when it recorded none.
      </p>
    </div>
  );
}

/** "9 am", "12 midnight" — plain words beat "0900 IST" for this reader. */
function hourLabel(hour: number): string {
  if (hour === 0) return "12 midnight";
  if (hour === 12) return "12 noon";
  return hour < 12 ? `${hour} am` : `${hour - 12} pm`;
}

/** The axis form: "12a", "3p". */
function shortHourLabel(hour: number): string {
  if (hour === 0) return "12a";
  if (hour === 12) return "12p";
  return hour < 12 ? `${hour}a` : `${hour - 12}p`;
}

/**
 * 24 vertical bars, one per IST hour, each printing its own count.
 *
 * All 24 always render: the server guarantees 24 buckets and zero-fills the silent ones
 * (`PerformanceOut.busiest_hours_ist`), and a chart that omits them reads as data loss to
 * the one reader who would notice 3am missing. A zero hour keeps a baseline stub and
 * prints its 0 in the faint ink, so "nothing happened" and "nothing was measured" cannot
 * be confused.
 *
 * Heights are relative to the busiest hour, never to a fixed axis — a clinic doing 20
 * calls a week would otherwise see 24 invisible stubs under a scale nobody told them was
 * arbitrary. The axis labels sit INSIDE each bar's own column (every third hour), so they
 * are aligned by construction rather than by four equal-width cells that happen to line
 * up with a 24-bar row.
 *
 * `calls` is the funnel's total for the same period, and it is here to explain a gap the
 * chart would otherwise be blamed for: the API counts only calls that have a start time,
 * so a dial that never reached the network is in the funnel and not in these bars.
 */
function HourHistogram({ hours, calls }: { hours: number[]; calls: number }) {
  const busiest = Math.max(...hours, 0);
  const started = hours.reduce((sum, count) => sum + count, 0);
  return (
    <div>
      {/* Text alternative (ux-audit D1): the visual chart associates each count with its
          hour by position alone, which a screen reader cannot follow. Same
          `busiest_hours_ist` numbers, no second computation. */}
      <table className="sr-only">
        <caption>Calls by hour of day (IST)</caption>
        <thead>
          <tr>
            <th scope="col">Hour</th>
            <th scope="col">Calls</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((count, hour) => (
            <tr key={hour}>
              <th scope="row">{hourLabel(hour)}</th>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ScrollRegion label="Calls by hour of day">
        <div aria-hidden="true" className="flex min-w-[620px] items-end gap-1">
          {hours.map((count, hour) => (
            <div
              key={hour}
              className="flex min-w-0 flex-1 flex-col items-center gap-1.5"
              title={`${hourLabel(hour)}: ${count} ${count === 1 ? "call" : "calls"}`}
            >
              <span
                className={`text-[10px] tabular-nums ${
                  count > 0 ? "font-semibold text-ink" : "text-ink-faint"
                }`}
              >
                {count}
              </span>
              <div className="flex h-[120px] w-full items-end">
                <div
                  className={`w-full rounded-t-sm ${
                    count > 0 ? "bg-brand" : "bg-black/[0.06] dark:bg-white/10"
                  }`}
                  // Relative to the busiest hour; a silent hour keeps a 2px baseline so
                  // the axis stays legible on an all-zero day.
                  style={{
                    height: count > 0 ? `${Math.max((count / busiest) * 100, 4)}%` : "2px",
                  }}
                />
              </div>
              <span className="h-3 text-[10px] font-medium text-ink-faint">
                {hour % 3 === 0 ? shortHourLabel(hour) : ""}
              </span>
            </div>
          ))}
        </div>
      </ScrollRegion>
      <p className="mt-2 text-xs text-ink-muted">
        When your phone rings the most — useful for staffing the counter and picking the
        best time for outgoing calls. Each bar counts the calls that STARTED in that hour,
        Indian Standard Time.
        {started < calls && (
          <>
            {" "}
            {formatCount(started)} of {formatCount(calls)} calls in this period have a
            start time; the rest never reached the network, so they are not in this chart.
          </>
        )}
      </p>
    </div>
  );
}
