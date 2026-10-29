"use client";

import { useState } from "react";

import { useAdminAccess } from "@/app/admin/access";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { PageHeader } from "@/components/console/pageHeader";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { NoticeBox, ProblemNotice, RestrictionNote, Skeleton, formatCount } from "@/components/ui";
import {
  ALL_LANGUAGES,
  percentText,
  secondsText,
  speedLanguageName,
  useFleetReplySpeed,
  type WeekSpeed,
} from "@/lib/api/proof";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

const WEEK_CHOICES = [4, 8, 12] as const;

function weekLabel(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (match === null) return date;
  const at = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return at.toLocaleDateString("en-IN", { timeZone: "UTC", day: "numeric", month: "short" });
}

const COLUMNS: DataColumn<WeekSpeed>[] = [
  { id: "week", header: "Week of", cell: (row) => weekLabel(row.week_start) },
  {
    id: "language",
    header: "Language",
    cell: (row) => (row.language === ALL_LANGUAGES ? "Every language" : speedLanguageName(row.language)),
  },
  { id: "calls", header: "Calls", align: "right", cell: (row) => formatCount(row.calls) },
  { id: "answered", header: "Answered", align: "right", cell: (row) => percentText(row.answered_share) ?? "None" },
  {
    id: "typical",
    header: "Usual wait",
    align: "right",
    cell: (row) => secondsText(row.reply_typical_ms) ?? "Not measured",
  },
  {
    id: "slow",
    header: "Slow wait",
    align: "right",
    cell: (row) => secondsText(row.reply_slow_ms) ?? "Too few calls",
  },
  {
    id: "length",
    header: "Average call",
    align: "right",
    hideBelow: "md",
    cell: (row) => (row.average_call_s == null ? "None" : `${Math.round(row.average_call_s)} s`),
  },
];

/**
 * REPLY SPEED BY LANGUAGE (D-944): every client's calls per IST week, split Telugu / Hindi /
 * English and the rest — the figures a public quality page would show. Nothing public shows
 * them: the page says whether `public_quality_page_enabled` is on, and it is off until the
 * founder decides. Test calls are left out. `ops:manage`, like Voice response time.
 */
export function ReplySpeedScreen() {
  const [weeks, setWeeks] = useState<number>(4);
  const access = useAdminAccess("ops:manage", "read the reply speed by language");
  const report = useFleetReplySpeed(weeks, !access.refused);
  const data = report.data;
  const rows = data ? [...data.weeks].reverse() : [];

  useCopilotSurface({
    route: "/admin/ops/reply-speed",
    title: "Reply speed by language",
    realm: "admin",
    saves: "view",
    fields: [
      {
        id: "reply-speed-weeks",
        label: "Weeks",
        type: "select",
        value: String(weeks),
        options: WEEK_CHOICES.map((choice) => ({ value: String(choice), label: `${choice} weeks` })),
      },
    ],
    facts: data
      ? [
          { key: "clients", label: "Clients with calls", value: String(data.clients) },
          { key: "public", label: "Public page switched on", value: data.public_page_enabled ? "yes" : "no" },
          {
            key: "this_week",
            label: "This week's usual wait per language",
            value:
              data.weeks
                .filter((w) => w.week_start === data.weeks[data.weeks.length - 1]?.week_start)
                .map((w) => `${w.language}: ${secondsText(w.reply_typical_ms) ?? "not measured"}`)
                .join("; ") || "no calls",
          },
        ]
      : [{ key: "report", label: "The report", value: report.error ? "could not be read" : "still loading" }],
    apply: (items) => {
      const chosen = Number(asText(items.find((item) => item.field_id === "reply-speed-weeks")?.value ?? ""));
      if ((WEEK_CHOICES as readonly number[]).includes(chosen)) setWeeks(chosen);
    },
  });

  return (
    <div className="max-w-6xl space-y-8 pb-12">
      <PageHeader description="Every client's calls per week and language: how fast the agent answered, and how many calls were answered." />
      {access.refused ? (
        <RestrictionNote reason={access.reason} />
      ) : (
        <>
          <SegmentedControl
            label="Weeks"
            value={String(weeks)}
            onValueChange={(value) => setWeeks(Number(value))}
            options={WEEK_CHOICES.map((choice) => ({ value: String(choice), label: `${choice} weeks` }))}
          />
          {report.error != null && <ProblemNotice error={report.error} onRetry={() => void report.refetch()} />}
          {!data ? (
            report.error ? null : <Skeleton rows={6} label="Loading reply speed by language" />
          ) : (
            <>
              <NoticeBox tone={data.public_page_enabled ? "warn" : "neutral"} title={data.public_page_enabled ? "Public page switched on" : "Not public"}>
                <p>
                  {data.public_page_enabled
                    ? "The console flag is on, but no public page is built yet."
                    : "Nothing public shows these figures. The console flag is off."}{" "}
                  {formatCount(data.clients)} clients had calls.
                  {data.complete ? "" : " Only the newest 100,000 calls were read."}
                </p>
              </NoticeBox>
              <DataTable
                label="Reply speed by week and language"
                columns={COLUMNS}
                rows={rows}
                getRowId={(row) => `${row.week_start}:${row.language}`}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
