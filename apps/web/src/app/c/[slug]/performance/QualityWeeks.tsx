"use client";

import Link from "next/link";
import { ArrowRight, Download } from "lucide-react";

import { formatDateRange } from "@/components/arc/ist-dates";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { SECONDARY_BUTTON_SM, Skeleton, formatCount } from "@/components/ui";
import { useQualityWeeks, type QualityWeek } from "@/lib/api/analytics";
import { useClientRealm } from "@/lib/api/session";
import { saveCsv, tableCsv } from "@/lib/csvDownload";

export const QUALITY_COPY = {
  title: "How calls went, week by week",
  info:
    "Every answered call is read once after it ends. Goal reached counts calls with a clear yes or no. Your own test calls are left out. India time, weeks start on Monday.",
  loading: "Reading the weeks",
  error: "We could not load how your calls went.",
  empty: "No answered calls have been read yet.",
  download: "Download",
  questions: "Questions to answer",
} as const;

const HEADERS = ["Week", "Calls read", "Goal reached", "Could not answer", "With a mistake"] as const;

function goalWords(week: QualityWeek): string {
  if (week.judged === 0) return "—";
  return `${formatCount(week.goal_reached)} of ${formatCount(week.judged)} (${Math.round((week.goal_reached * 100) / week.judged)}%)`;
}

function cells(week: QualityWeek): string[] {
  return [
    formatDateRange(week.from_date, week.to_date),
    String(week.calls_read),
    goalWords(week),
    String(week.calls_not_known),
    String(week.calls_with_mistakes),
  ];
}

/**
 * The per-call scorecard as a weekly average (W8.5): included with every plan, from the
 * same after-call read the call page shows. "Could not answer" leads to each agent's
 * Questions to answer, where the owner teaches the missing answer.
 */
export function QualityWeeks() {
  const { session, href } = useClientRealm();
  const quality = useQualityWeeks(session);
  const data = quality.data;
  const weeks = data ? [...data.weeks].reverse() : [];

  const columns: DataColumn<QualityWeek>[] = [
    { id: "week", header: HEADERS[0], cell: (w) => formatDateRange(w.from_date, w.to_date) },
    { id: "read", header: HEADERS[1], align: "right", cell: (w) => formatCount(w.calls_read) },
    { id: "goal", header: HEADERS[2], align: "right", cell: goalWords },
    { id: "unknown", header: HEADERS[3], align: "right", cell: (w) => formatCount(w.calls_not_known) },
    { id: "mistakes", header: HEADERS[4], align: "right", cell: (w) => formatCount(w.calls_with_mistakes), hideBelow: "sm" },
  ];

  return (
    <Section
      title={QUALITY_COPY.title}
      info={QUALITY_COPY.info}
      action={
        data && weeks.some((w) => w.calls_read > 0) ? (
          <button
            type="button"
            className={SECONDARY_BUTTON_SM}
            onClick={() => saveCsv(tableCsv(HEADERS, weeks.map(cells)), "call-quality-weeks")}
          >
            <Download aria-hidden className="h-3.5 w-3.5" />
            {QUALITY_COPY.download}
          </button>
        ) : undefined
      }
    >
      {quality.error && !data ? (
        <EmptyState variant="error" message={QUALITY_COPY.error} error={quality.error} onRetry={() => void quality.refetch()} />
      ) : !data ? (
        <Skeleton rows={3} label={QUALITY_COPY.loading} />
      ) : !weeks.some((w) => w.calls_read > 0) ? (
        <EmptyState message={QUALITY_COPY.empty} />
      ) : (
        <div className="space-y-3">
          <DataTable
            rows={weeks}
            columns={columns}
            getRowId={(w) => w.from_date}
            label="Answered calls read, goal reached, questions not known and mistakes per week, newest first"
          />
          {data.gap_agents.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-meta text-ink-muted">{QUALITY_COPY.questions}:</span>
              {data.gap_agents.map((agent) => (
                <Link
                  key={agent.agent_id}
                  href={href(`/c/${session.orgSlug}/agents/${agent.agent_id}?section=training`)}
                  className={SECONDARY_BUTTON_SM}
                >
                  <span className="max-w-48 truncate">{agent.name}</span> ({formatCount(agent.open_questions)})
                  <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}
