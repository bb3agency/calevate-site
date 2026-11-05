"use client";

import Link from "next/link";
import { useState } from "react";

import { formatDateRange, formatMonth } from "@/components/arc/ist-dates";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { Section } from "@/components/console/section";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ArrowRight } from "lucide-react";

import { SECONDARY_BUTTON_SM, Skeleton, ToggleSwitch, formatCount, formatINR, formatIST } from "@/components/ui";
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
import { OUTCOME_ORDER, callOutcome, endingLabel } from "@/lib/callReview";

import { PERFORMANCE_COPY as COPY } from "./copy";

const BUCKETS: { value: SummaryBucket; label: string }[] = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

const GROUPS: { value: CallGroupBy; label: string }[] = [
  { value: "caller", label: "Person" },
  { value: "outcome", label: "Outcome" },
  { value: "agent", label: "Agent" },
];

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
      title={COPY.periodTitle}
      description={COPY.periodNote}
      action={
        <SegmentedControl
          label={COPY.periodGroup}
          value={bucket}
          onValueChange={(next) => setBucket(next === "day" ? "day" : next === "month" ? "month" : "week")}
          options={BUCKETS}
        />
      }
    >
      {summary.error && !data ? (
        <EmptyState
          variant="error"
          message={COPY.periodError}
          error={summary.error}
          onRetry={() => void summary.refetch()}
        />
      ) : !data ? (
        <Skeleton rows={4} label={COPY.loadingFigures} />
      ) : data.calls === 0 && data.leads === 0 && data.spent_inr === null ? (
        <EmptyState message={COPY.periodEmpty} />
      ) : (
        <div className="space-y-3">
          <p className="text-meta text-ink-muted">
            {formatCount(data.calls)} {data.calls === 1 ? "call" : "calls"}, {formatCount(data.answered)} answered,{" "}
            {formatCount(data.leads)} {data.leads === 1 ? "new lead" : "new leads"}
            {data.spent_inr !== null ? `, ${formatINR(data.spent_inr)} spent` : ""}.
          </p>
          <DataTable
            rows={[...data.rows].reverse()}
            columns={columns}
            getRowId={(row) => row.from_date}
            label={`Calls, answered calls and new leads by ${bucket}, newest first`}
          />
          {data.spend_withheld === "no_billing_access" ? (
            <p className="text-meta text-ink-muted">{COPY.spendNoAccess}</p>
          ) : data.spend_withheld === "one_agent" ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <p className="text-meta text-ink-muted">{COPY.spendWholeAccount}</p>
              <Link href={`/c/${slug}/billing?tab=usage`} className={SECONDARY_BUTTON_SM}>
                {COPY.spendLink}
                <ArrowRight aria-hidden className="h-3.5 w-3.5" />
              </Link>
            </div>
          ) : null}
        </div>
      )}
    </Section>
  );
}

/**
 * A person by name when their lead or a campaign list names them, else by the last two
 * digits of their number. Neutral about direction: half these people were rung by a
 * campaign, so "caller" and "lead" would both misname them.
 */
function groupName(group: CallGroup, by: CallGroupBy): string {
  if (by === "outcome") return endingLabel(group.key);
  if (by === "agent") return group.label ?? "An agent since removed";
  const tail = group.number_tail;
  if (group.label) return tail ? `${group.label} · ends ${tail}` : group.label;
  return tail ? `Number ending ${tail}` : "Number not known";
}

/** How the latest call went, in the call log's words: a fact, else the business's own outcome. */
function latestCallWords(group: CallGroup): string {
  const tag = OUTCOME_ORDER.find((known) => known === group.latest_outcome) ?? null;
  return callOutcome({
    status: group.latest_status,
    outcome_tag: tag,
    business_outcome_label: group.latest_business_outcome_label,
    summary_state: "ready",
  }).words;
}

/** A person's row opens their lead, or their latest call when no lead was filed. */
function personHref(slug: string, group: CallGroup): string {
  return group.lead_id ? `/c/${slug}/leads/${group.lead_id}` : `/c/${slug}/calls/${group.latest_call_id}`;
}

/**
 * WHO WAS ON THE CALL, HOW CALLS ENDED, WHICH AGENT TOOK THEM: every call in the period counted per
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

  const columns: DataColumn<CallGroup>[] = [
    {
      id: "name",
      header: by === "caller" ? "Person" : by === "outcome" ? "Outcome" : "Agent",
      cell: (group) =>
        by === "caller" ? (
          <Link href={personHref(slug, group)} className="font-medium underline-offset-2 hover:underline [overflow-wrap:anywhere] after:absolute after:inset-0 focus-visible:outline-none focus-visible:after:rounded-md focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-brand">
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
      ? [{ id: "went", header: "How it went", cell: (group: CallGroup) => latestCallWords(group) }]
      : []),
  ];

  const headline = !data
    ? null
    : by === "caller"
      ? `${formatCount(data.calls)} ${data.calls === 1 ? "call" : "calls"}. ${formatCount(data.repeat_groups)} ${data.repeat_groups === 1 ? "person" : "people"} had more than one call.`
      : `${formatCount(data.calls)} ${data.calls === 1 ? "call" : "calls"} across ${formatCount(data.groups_total)} ${by === "outcome" ? "outcomes" : "agents"}.`;

  return (
    <Section
      title={COPY.groupsTitle}
      description={COPY.groupsNote}
      action={
        <SegmentedControl
          label={COPY.groupsCountBy}
          value={by}
          onValueChange={(next) => setBy(next === "outcome" ? "outcome" : next === "agent" ? "agent" : "caller")}
          options={GROUPS}
        />
      }
    >
      <div className="space-y-3">
        {by === "caller" ? (
          <ToggleSwitch label={COPY.repeatOnly} checked={repeatOnly} onChange={setRepeatOnly} />
        ) : null}
        {groups.error && !data ? (
          <EmptyState
            variant="error"
            message={COPY.groupsError}
            error={groups.error}
            onRetry={() => void groups.refetch()}
          />
        ) : !data ? (
          <Skeleton rows={4} label={COPY.groupsLoading} />
        ) : (
          <>
            <p className="text-meta text-ink-muted" aria-live="polite">
              {headline}
            </p>
            {data.groups.length === 0 ? (
              <EmptyState
                message={
                  data.calls === 0 ? COPY.groupsNone : COPY.groupsNoRepeat
                }
              />
            ) : (
              <DataTable
                rows={data.groups}
                columns={columns}
                getRowId={(group) => (by === "caller" ? (group.lead_id ?? group.latest_call_id) : `${by}:${group.key}`)}
                label={`Calls by ${by === "caller" ? "person" : by}, most calls first`}
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
