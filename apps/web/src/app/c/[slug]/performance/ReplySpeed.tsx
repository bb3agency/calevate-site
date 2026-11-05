"use client";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Metric } from "@/components/console/metric";
import { Section } from "@/components/console/section";
import { ProblemNotice, Skeleton, formatCount, formatDuration } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import {
  ALL_LANGUAGES,
  percentText,
  secondsText,
  speedLanguageName,
  useReplySpeed,
  type WeekSpeed,
} from "@/lib/api/proof";

import { istDayLabel } from "../analyticsFigures";

const WEEKS = 4;


const COLUMNS: DataColumn<WeekSpeed>[] = [
  { id: "week", header: "Week of", cell: (row) => istDayLabel(row.week_start) },
  {
    id: "calls",
    header: "Calls",
    align: "right",
    cell: (row) => <span className="tabular-nums">{formatCount(row.calls)}</span>,
  },
  {
    id: "answered",
    header: "Answered",
    align: "right",
    cell: (row) => percentText(row.answered_share) ?? "None",
  },
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
    hideBelow: "sm",
    cell: (row) => secondsText(row.reply_slow_ms) ?? "Too few calls",
  },
  {
    id: "length",
    header: "Average call",
    align: "right",
    hideBelow: "md",
    cell: (row) => (row.average_call_s == null ? "None" : formatDuration(Math.round(row.average_call_s))),
  },
];

/**
 * HOW FAST YOUR AGENT ANSWERED THIS WEEK (D-944). The wait is from the caller finishing to
 * the first word of the answer, measured by the voice platform on each call; the server
 * takes the usual wait and the slow one (one wait in ten) per IST week. The current week is
 * the headline, the last four weeks the table, each language underneath. Test calls are left
 * out. A week the platform did not time says "Not measured", never 0.
 */
export function ReplySpeed({ session }: { session: Session }) {
  const speed = useReplySpeed(session, WEEKS);

  return (
    <Section
      title="How fast your agent answered"
      description="Last 4 weeks, not the dates above"
      info={
        <p>
          The last four weeks, whatever dates are chosen above. From the caller stopping to
          the agent&apos;s first word. Usual: a typical call.
          Slow: the slowest call in ten, once enough are timed. Test calls left out.
        </p>
      }
    >
      {speed.error ? (
        <ProblemNotice error={speed.error} onRetry={() => void speed.refetch()} />
      ) : !speed.data ? (
        <Skeleton rows={3} label="Loading how fast your agent answered" />
      ) : (
        <ReplySpeedBody weeks={speed.data.weeks} />
      )}
    </Section>
  );
}

function ReplySpeedBody({ weeks }: { weeks: WeekSpeed[] }) {
  const totals = weeks.filter((w) => w.language === ALL_LANGUAGES);
  const current = totals[totals.length - 1];
  if (!current || totals.every((w) => w.calls === 0)) {
    return <EmptyState message="No calls in the last four weeks." />;
  }
  const languages = weeks.filter(
    (w) => w.language !== ALL_LANGUAGES && w.week_start === current.week_start,
  );
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Metric
          label="Usual wait this week"
          value={secondsText(current.reply_typical_ms) ?? "Not measured"}
          hint={`${formatCount(current.calls_measured)} calls timed`}
        />
        <Metric
          label="Slow wait this week"
          value={secondsText(current.reply_slow_ms) ?? "Too few calls"}
          hint={current.reply_slow_ms == null ? undefined : "1 call in 10 waited longer"}
        />
        <Metric
          label="Answered"
          value={percentText(current.answered_share) ?? "None"}
          hint={`${formatCount(current.answered)} of ${formatCount(current.calls)} calls`}
        />
        <Metric
          label="Average call"
          value={current.average_call_s == null ? "None" : formatDuration(Math.round(current.average_call_s))}
        />
      </div>
      {languages.length > 1 && (
        <ul className="flex flex-wrap gap-x-6 gap-y-1 text-meta text-ink-muted">
          {languages.map((w) => (
            <li key={w.language}>
              {speedLanguageName(w.language)}: {secondsText(w.reply_typical_ms) ?? "not measured"}
            </li>
          ))}
        </ul>
      )}
      <DataTable
        label="How fast your agent answered, by week"
        columns={COLUMNS}
        rows={[...totals].reverse()}
        getRowId={(row) => row.week_start}
      />
    </div>
  );
}
