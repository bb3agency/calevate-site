"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  DEFAULT_WINDOW_DAYS,
  FIRST_SOUND_NOTE,
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
 * agent's first sound, as the voice platform measured it on each call, across every client.
 * A filler line is a first sound, so these are not times to the answer (D-901). `ops:manage` gates the read; the gate is `!refused` so an operator is not locked
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
            {
              key: "measures",
              label: "What every wait measures",
              value: FIRST_SOUND_NOTE,
            },
            {
              key: "targets",
              label: "Targets for the wait to the agent's first sound (typical / slow)",
              value: `${formatMs(data.typical_target_ms)} / ${formatMs(data.slow_target_ms)}`,
            },
            {
              key: "calls",
              label: "Calls measured / finished",
              value: `${data.overall.calls_measured} / ${data.overall.calls}`,
            },
            {
              key: "typical",
              label: "Typical wait to first sound (median of each call's median)",
              value: formatMs(data.overall.reply_typical_ms),
            },
            {
              key: "typical_no_filler",
              label: "Typical wait to first sound, calls with no filler line found",
              value: `${formatMs(data.overall.reply_typical_no_filler_ms)} (${data.overall.calls_with_filler} of ${data.overall.calls_measured} measured calls had one)`,
            },
            {
              key: "slow",
              label: "Slow wait to first sound (90th percentile of each call's p90)",
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
            How long callers waited for the agent&rsquo;s first sound, as the voice platform
            measured it on each call. A filler line counts, so this is not the time to the
            answer.{" "}
            <InfoTip label="What these figures are">
              <p>{FIRST_SOUND_NOTE}</p>
              <p>
                The platform sends each call&rsquo;s typical (median), slow (90th percentile)
                and longest wait once the call ends. It does not report the time to the
                answer&rsquo;s first word. &ldquo;No filler found&rdquo; leaves out calls whose
                transcript shows a reply opening with a filler line; a filler the transcript
                does not show cannot be left out.
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
