"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  DEFAULT_WINDOW_DAYS,
  WINDOW_CHOICES,
  formatMs,
  useReplyTimes,
  windowLabel,
} from "@/lib/api/replyTimes";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

import { ReplyTimesReport } from "./ReplyTimesReport";

/**
 * The console half of `GET /v1/ops/reply-times` (D-770): how long callers waited for the
 * agent to start answering, as the voice platform measured it on each call, across every
 * client. `ops:manage` gates the read; the gate is `!refused` so an operator is not locked
 * out while `/v1/admin/me` is still in flight (`access.ts`: the API is the enforcement).
 */
export function ReplyTimesScreen() {
  const [days, setDays] = useState(DEFAULT_WINDOW_DAYS);
  const access = useAdminAccess("ops:manage", "read the voice response-time report");
  const report = useReplyTimes(days, !access.refused);
  const data = report.data;

  useCopilotSurface({
    route: "/admin/ops/reply-times",
    title: "Voice response time",
    realm: "admin",
    saves: "view",
    fields: [
      {
        id: "reply-window-days",
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
      ? [{ key: "report", label: "The report", value: "withheld — this admin account may not read it" }]
      : data
        ? [
            { key: "window_days", label: "Window shown (days)", value: String(data.window_days) },
            { key: "target", label: "Reply time target", value: formatMs(data.target_ms) },
            {
              key: "calls",
              label: "Calls measured / finished",
              value: `${data.overall.calls_measured} / ${data.overall.calls}`,
            },
            {
              key: "typical",
              label: "Typical reply (median of each call's median)",
              value: formatMs(data.overall.reply_typical_ms),
            },
            {
              key: "slow",
              label: "Slow reply (90th percentile of each call's p90)",
              value: formatMs(data.overall.reply_slow_ms),
            },
            {
              key: "over",
              label: "Calls over target",
              value: String(data.overall.calls_over_target),
            },
            {
              key: "slow_reply_problems",
              label: "Calls with a reply over 5 seconds",
              value: String(data.overall.slow_reply_problems),
            },
            {
              key: "worst_clients",
              label: "Clients with the most calls over target",
              value:
                data.by_client
                  .filter((row) => row.calls_over_target > 0)
                  .slice(0, 5)
                  .map((row) => `${row.client_name}: ${row.calls_over_target}`)
                  .join("; ") || "none",
            },
            {
              key: "empty",
              label: "Why there are no figures",
              value: data.empty_reason ?? "there are figures",
            },
          ]
        : [
            {
              key: "report",
              label: "The report",
              value: report.error ? "could not be read" : "still loading",
            },
          ],
    apply: (items) => {
      const window = items.find((item) => item.field_id === "reply-window-days");
      if (window === undefined) return;
      const chosen = Number(asText(window.value));
      if (WINDOW_CHOICES.includes(chosen)) setDays(chosen);
    },
  });

  return (
    <div className="max-w-6xl space-y-10 pb-12">
      <PageHeader
        description={
          <>
            How long callers waited for the agent to start answering, as the voice platform
            measured it on each call.{" "}
            <InfoTip label="What these figures are">
              <p>
                A reply time runs from the moment the caller stops speaking to the first sound
                of the agent&rsquo;s answer. The platform sends each call&rsquo;s typical
                (median), slow (90th percentile) and slowest reply once the call ends.
              </p>
              <p>
                The model&rsquo;s first word is part of that wait, timed from the turn reaching
                the voice platform to the first word it can speak, not from when the caller
                stopped.
              </p>
              <p>
                Each call counts once, however long it was. Typical is the middle of the
                calls&rsquo; own typical replies; slow is the point nine calls in ten had their
                slow replies under.
              </p>
            </InfoTip>
          </>
        }
      />

      {access.refused ? (
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

          {!data ? (
            report.error ? null : <Skeleton rows={6} label="Loading the response-time report" />
          ) : (
            <ReplyTimesReport report={data} />
          )}
        </>
      )}
    </div>
  );
}
