"use client";

import Link from "next/link";
import { useState } from "react";

import { formatDateRange, formatMonth } from "@/components/arc/ist-dates";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { Skeleton, ToggleSwitch, formatCount, formatINR, formatIST } from "@/components/ui";
import {
  useActivitySummary,
  useCallGroups,
  type AnalyticsRange,
  type CallGroup,
  type CallGroupBy,
  type SummaryBucket,
  type SummaryRow,
} from "@/lib/api/analytics";
import { useClientSession } from "@/lib/api/session";
import { outcomeLabel } from "@/lib/callReview";

const BUCKETS: { value: SummaryBucket; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

const GROUPS: { value: CallGroupBy; label: string }[] = [
  { value: "caller", label: "Caller" },
  { value: "outcome", label: "Outcome" },
  { value: "agent", label: "Agent" },
];

type RankedGroup = CallGroup & { rank: number };

/** Rows a grouped table shows; its counts still cover every call. */
const GROUP_LIMIT = 25;

function rowLabel(row: SummaryRow, bucket: SummaryBucket): string {
  // A month cut short by the range names its days, so a part-month never reads as whole.
  if (bucket === "month" && row.from_date.endsWith("-01")) {
    const next = new Date(`${row.to_date}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    if (next.getUTCDate() === 1) return formatMonth(row.from_date);
  }
  return formatDateRange(row.from_date, row.to_date);
}

/**
 * THE PERIOD AS A TABLE: calls, answered, new leads and what left the wallet, per IST day,
 * Monday-first week or month (`/v1/analytics/summary`). The same numbers Pip quotes when
 * asked "how did last week go", so the two never disagree.
 */
export function PeriodTable({ range }: { range: AnalyticsRange }) {
  const session = useClientSession();
  const slug = session.orgSlug;
  const [bucket, setBucket] = useState<SummaryBucket>("week");
  const summary = useActivitySummary(session, { ...range, bucket });
  const data = summary.data;
  const showSpend = data !== undefined && data.spend_withheld === null;

  const columns: DataColumn<SummaryRow>[] = [
    { id: "period", header: bucket === "day" ? "Day" : bucket === "week" ? "Week" : "Month", cell: (row) => rowLabel(row, bucket) },
    { id: "calls", header: "Calls", align: "right", cell: (row) => formatCount(row.calls), sort: { value: (row) => row.calls, kind: "number" } },
    { id: "answered", header: "Answered", align: "right", cell: (row) => formatCount(row.answered), sort: { value: (row) => row.answered, kind: "number" } },
    { id: "leads", header: "New leads", align: "right", cell: (row) => formatCount(row.leads), sort: { value: (row) => row.leads, kind: "number" } },
    ...(showSpend
      ? [
          {
            id: "spent",
            header: "Spent",
            align: "right" as const,
            cell: (row: SummaryRow) => formatINR(row.spent_inr),
            sort: { value: (row: SummaryRow) => row.spent_inr, kind: "decimal" as const },
          },
        ]
      : []),
  ];

  return (
    <Section
      title="Day by day, week by week"
      description="India time. Weeks start on Monday."
      action={
        <SegmentedControl
          label="Group by"
          value={bucket}
          onValueChange={(next) => setBucket(next === "day" ? "day" : next === "month" ? "month" : "week")}
          options={BUCKETS}
        />
      }
    >
      {summary.error && !data ? (
        <EmptyState
          variant="error"
          message="We could not load these figures."
          error={summary.error}
          onRetry={() => void summary.refetch()}
        />
      ) : !data ? (
        <Skeleton rows={4} label="Loading the figures" />
      ) : data.calls === 0 && data.leads === 0 && data.spent_inr === null ? (
        <EmptyState message="No calls or new leads in this period." />
      ) : (
        <div className="space-y-3">
          <p className="text-meta text-ink-muted">
            {formatCount(data.calls)} calls, {formatCount(data.answered)} answered,{" "}
            {formatCount(data.leads)} new leads
            {data.spent_inr !== null ? `, ${formatINR(data.spent_inr)} spent` : ""}.
          </p>
          <DataTable
            rows={[...data.rows].reverse()}
            columns={columns}
            getRowId={(row) => row.from_date}
            label={`Calls, answered calls and new leads by ${bucket}, newest first`}
          />
          {data.spend_withheld === "no_billing_access" ? (
            <p className="text-meta text-ink-muted">Spend is shown to people who can see billing.</p>
          ) : data.spend_withheld === "one_agent" ? (
            <p className="text-meta text-ink-muted">
              Spend is for the whole account. See it on{" "}
              <Link href={`/c/${slug}/billing?tab=usage`} className="underline underline-offset-2">
                Usage
              </Link>
              .
            </p>
          ) : null}
        </div>
      )}
    </Section>
  );
}

function groupName(group: CallGroup, by: CallGroupBy): string {
  if (by === "outcome") return outcomeLabel(group.key) ?? "Not recorded";
  if (by === "agent") return group.label ?? "An agent since removed";
  const who = group.label ?? "No lead yet";
  return group.number_tail ? `${who} · ends ${group.number_tail}` : who;
}

/**
 * WHO CALLED, HOW CALLS ENDED, WHICH AGENT TOOK THEM: every call in the period counted per
 * group by the server (`/v1/analytics/call-groups`), never from the page of calls a list
 * happens to hold. Test calls are left out: they are the owner ringing their own agent.
 */
export function CallGroupsTable({ range }: { range: AnalyticsRange }) {
  const session = useClientSession();
  const slug = session.orgSlug;
  const [by, setBy] = useState<CallGroupBy>("caller");
  const [repeatOnly, setRepeatOnly] = useState(true);
  const minCalls = by === "caller" && repeatOnly ? 2 : 1;
  const groups = useCallGroups(session, {
    ...range,
    testCalls: false,
    by,
    minCalls,
    limit: GROUP_LIMIT,
  });
  const data = groups.data;

  const columns: DataColumn<RankedGroup>[] = [
    {
      id: "name",
      header: by === "caller" ? "Caller" : by === "outcome" ? "Outcome" : "Agent",
      cell: (group) =>
        by === "caller" && group.lead_id ? (
          <Link href={`/c/${slug}/leads/${group.lead_id}`} className="underline-offset-2 hover:underline [overflow-wrap:anywhere]">
            {groupName(group, by)}
          </Link>
        ) : (
          <span className="[overflow-wrap:anywhere]">{groupName(group, by)}</span>
        ),
    },
    { id: "calls", header: "Calls", align: "right", cell: (group) => formatCount(group.calls), sort: { value: (g) => g.calls, kind: "number", first: "desc" } },
    { id: "answered", header: "Answered", align: "right", cell: (group) => formatCount(group.answered), sort: { value: (g) => g.answered, kind: "number", first: "desc" } },
    { id: "latest", header: "Latest call", cell: (group) => formatIST(group.latest_at), sort: { value: (g) => g.latest_at, kind: "time", first: "desc" }, hideBelow: "sm" },
    ...(by !== "outcome"
      ? [{ id: "ended", header: "Last ended", cell: (group: CallGroup) => outcomeLabel(group.latest_outcome) ?? "—" }]
      : []),
  ];

  const headline = !data
    ? null
    : by === "caller"
      ? `${formatCount(data.calls)} calls. ${formatCount(data.repeat_groups)} ${data.repeat_groups === 1 ? "caller" : "callers"} called more than once.`
      : `${formatCount(data.calls)} calls across ${formatCount(data.groups_total)} ${by === "outcome" ? "outcomes" : "agents"}.`;

  return (
    <Section
      title="Who called, and how it went"
      description="Counted over every call in the period, not counting your own test calls."
      action={
        <SegmentedControl
          label="Count by"
          value={by}
          onValueChange={(next) => setBy(next === "outcome" ? "outcome" : next === "agent" ? "agent" : "caller")}
          options={GROUPS}
        />
      }
    >
      <div className="space-y-3">
        {by === "caller" ? (
          <ToggleSwitch label="Only people who called more than once" checked={repeatOnly} onChange={setRepeatOnly} />
        ) : null}
        {groups.error && !data ? (
          <EmptyState
            variant="error"
            message="We could not count these calls."
            error={groups.error}
            onRetry={() => void groups.refetch()}
          />
        ) : !data ? (
          <Skeleton rows={4} label="Counting calls" />
        ) : (
          <>
            <p className="text-meta text-ink-muted" aria-live="polite">
              {headline}
            </p>
            {data.groups.length === 0 ? (
              <EmptyState
                message={
                  data.calls === 0
                    ? "No calls in this period."
                    : "Nobody called more than once in this period."
                }
              />
            ) : (
              <DataTable
                rows={data.groups.map((group, rank) => ({ ...group, rank }))}
                columns={columns}
                getRowId={(group) => group.lead_id ?? (group.key === "number" ? `number:${group.rank}` : `${by}:${group.key}`)}
                label={`Calls by ${by}, most calls first`}
                partialNote={
                  data.groups.length < (by === "caller" && repeatOnly ? data.repeat_groups : data.groups_total)
                    ? `Showing the ${formatCount(data.groups.length)} with the most calls.`
                    : undefined
                }
              />
            )}
          </>
        )}
      </div>
    </Section>
  );
}
