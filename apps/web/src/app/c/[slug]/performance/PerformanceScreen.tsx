"use client";

import { useState } from "react";
import { Clock, PhoneCall, PhoneIncoming, UserCheck } from "lucide-react";

import {
  Card,
  FilterChip,
  ProblemNotice,
  RestrictionNote,
  Skeleton,
  StatTile,
  formatCount,
  formatDuration,
} from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { usePerformance } from "@/lib/api/performance";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import {
  Funnel,
  HourHistogram,
  Outcomes,
  Updating,
  ratePct,
} from "./PerformanceCharts";

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

export function PerformanceScreen() {
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
