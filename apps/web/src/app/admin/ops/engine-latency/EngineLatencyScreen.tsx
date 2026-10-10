"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import {
  DEFAULT_WINDOW_DAYS,
  WINDOW_CHOICES,
  regionLabel,
  useEngineLatency,
} from "@/lib/api/engineLatency";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { LatencyReport } from "./LatencyReport";

/**
 * What the voice engine's own pipeline cost, by region — the console half of
 * `GET /v1/ops/engine-latency` (OPERATIONS §2 gate 4), so an operator mid-incident reads a
 * screen rather than hand-assembling a curl against production.
 *
 * Every percentile, count, target and verdict is the server's field; the composed totals
 * arrive already summed, so this bundle never adds two targets together. It is not
 * voice-to-voice latency: both ends of that interval are on the PSTN leg this stack is not
 * in (D-25/D-33), and gate 4's stopwatch is a human's.
 *
 * `ops:manage` gates the READ because the screen is one GET. The gate is `!refused`, not
 * `allowed`: `allowed` is false while `/v1/admin/me` is merely in flight or failed, and
 * gating on it would lock an operator out of an incident read the API would have served
 * (`access.ts`: navigation fails open, the API is the enforcement).
 */
export function EngineLatencyScreen() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  const access = useAdminAccess("ops:manage", "read the engine's latency report");
  const report = useEngineLatency(days, !access.refused);
  const data = report.data;

  /*
   * Aggregate over every call, grouped by region and never by client, so no row traces to
   * a tenant. The window is writable against the four declared options. Whether each leg's
   * UNIT is verified travels with the breach counts: an unverified figure that reaches a
   * model as a bare number becomes a fact somebody repeats (hard rule 11).
   */
  useCopilotSurface({
    route: "/admin/ops/engine-latency",
    title: "Engine latency",
    realm: "admin",
    fields: [
      {
        id: "latency-window-days",
        label: "Window (days)",
        type: "select",
        value: String(days),
        options: WINDOW_CHOICES.map((choice) => ({
          value: String(choice),
          label: `Last ${windowLabel(choice)}`,
        })),
      },
    ],
    facts: access.refused
      ? [
          {
            key: "report",
            label: "The latency report",
            value: "withheld — this admin account may not read it",
          },
        ]
      : data
        ? [
            { key: "window_days", label: "Window shown (days)", value: String(data.window_days) },
            {
              key: "complete",
              label: "Did every measured turn fit the window",
              value: data.complete ? "yes" : "no, the report is truncated",
            },
            {
              key: "groups",
              label: "Regions the engine ran calls in",
              value:
                data.groups.map((group) => regionLabel(group.region)).join(", ") ||
                "no calls measured in this window",
            },
            {
              key: "calls",
              label: "Calls measured",
              value: String(data.groups.reduce((total, group) => total + group.calls, 0)),
            },
            {
              key: "turns",
              label: "Turns measured",
              value: String(data.groups.reduce((total, group) => total + group.turns, 0)),
            },
            {
              key: "breaches",
              label: "Legs over budget, by region",
              value:
                data.groups
                  .flatMap((group) =>
                    group.legs
                      .filter((leg) => leg.budget_breached === true)
                      .map(
                        (leg) =>
                          `${regionLabel(group.region)} ${leg.leg}: ${leg.turns_over_budget} of ${leg.turns} turns over ${leg.budget_ms}ms`,
                      ),
                  )
                  .join("; ") || "none",
            },
            {
              key: "unverified_units",
              label: "Legs whose unit is NOT verified against the vendor's own docs",
              value:
                [
                  ...new Set(
                    data.groups.flatMap((group) =>
                      group.legs.filter((leg) => !leg.unit_verified).map((leg) => leg.leg),
                    ),
                  ),
                ]
                  .sort()
                  .join(", ") || "none — every leg's unit is verified",
            },
          ]
        : [
            {
              key: "report",
              label: "The latency report",
              value: report.error ? "could not be read" : "still loading",
            },
          ],
    apply: (items) => {
      const window = items.find((item) => item.field_id === "latency-window-days");
      if (window === undefined) return;
      const chosen = Number(asText(window.value));
      // A window the endpoint would refuse is worse than no change.
      if (WINDOW_CHOICES.includes(chosen)) setDays(chosen);
    },
  });

  return (
    <div className="max-w-4xl space-y-10 pb-12">
      <PageHeader
        description={
          <>
            The engine&rsquo;s own timings per reply stage — not what a caller hears end to
            end.{" "}
            <InfoTip label="What these timings are">
              <p>
                How long each stage of a reply takes — hearing the caller, thinking of an
                answer, starting to speak — measured on every reply and grouped by the region
                the engine ran the call in.
              </p>
              <p>
                What a caller actually hears on the phone from end to end is a stopwatch
                measurement nobody can take from here.
              </p>
            </InfoTip>
          </>
        }
      />

      {access.refused ? (
        // Instead of the report, never beside it: this is a permission working as designed,
        // and a window picker over a red box would describe an outage.
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <SegmentedControl
            label="Window"
            value={String(days)}
            onValueChange={(value) => setDays(Number(value))}
            options={WINDOW_CHOICES.map((choice) => ({
              value: String(choice),
              label: `Last ${windowLabel(choice)}`,
            }))}
          />

          {report.error != null && (
            <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />
          )}

          {/* §52: in flight gets a skeleton; failed is the refusal above and nothing else. */}
          {!data ? (
            report.error ? null : (
              <div>
                <Skeleton rows={6} label="Loading the engine's latency report" />
              </div>
            )
          ) : (
            <LatencyReport report={data} windowLabel={windowLabel(data.window_days)} />
          )}
        </>
      )}
    </div>
  );
}

/** "7 days", and "1 day" rather than "1 days" — one spelling for the control and the report. */
function windowLabel(days: number): string {
  return `${formatCount(days)} ${days === 1 ? "day" : "days"}`;
}
