"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, TriangleAlert } from "lucide-react";

import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { InfoTip } from "@/components/console/infoTip";
import { PageHeader } from "@/components/console/pageHeader";
import { RowMenu } from "@/components/console/rowMenu";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ADMIN_PAGE_WIDE, StatusPill } from "@/components/admin/kit";
import {
  NoticeBox,
  ProblemNotice,
  Skeleton,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useQaSamples, VERDICTS, type QaSample } from "@/lib/api/qaSamples";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { asText } from "@/lib/copilot/types";

/**
 * The QA sampling queue (SURFACES §1): about 5% of each client's calls per week, drawn by
 * `apps/api/quality/sampling.py` on the weekly tick in `apps/workers/qa_sampling.py`.
 *
 * A work queue, not a report:
 *
 * 1. The draw's evidence is on every row — the week, how many calls it held, how many were
 *    drawn and where this one ranked — so "we sample 5%" is checkable rather than a list
 *    somebody could have chosen by taste. The seed is on the review screen.
 * 2. Every row ends in the review: the row is one link into the call, and "Not yet
 *    reviewed" is the default view.
 * 3. Empty is the good state and says so. A failed or paused read is a third branch —
 *    "nobody is waiting" is a claim about the world, and a dead token is not evidence.
 *
 * The list carries ids, timings and tags only (hard rule 6): no phone number and no
 * transcript text. The conversation is on the detail screen, where reading it is audited.
 */
export function QaQueueScreen() {
  const [pending, setPending] = useState(true);
  const queue = useQaSamples(pending);
  const rows = queue.data;

  /*
   * The draw spans every client, so counts leave and names do not — no `tenant_name`,
   * `agent_name` or `call_id`. The filter is writable: a two-value toggle over a list the
   * person is already looking at.
   */
  useCopilotSurface({
    route: "/admin/qa-sampling",
    title: "Call quality sampling",
    realm: "admin",
    fields: [
      {
        id: "qa-filter-pending",
        label: "Which calls are listed",
        type: "select",
        value: pending ? "pending" : "all",
        options: [
          { value: "pending", label: "Not yet reviewed" },
          { value: "all", label: "Every sampled call" },
        ],
      },
    ],
    facts: rows
      ? [
          {
            key: "listed",
            label: pending ? "Calls waiting for review" : "Calls sampled",
            value: String(rows.length),
          },
          {
            key: "defects",
            label: "Listed calls marked as a defect",
            value: String(rows.filter((row) => row.verdict === "defect").length),
          },
          {
            key: "weeks",
            label: "Draw weeks represented in the list",
            value: String(new Set(rows.map((row) => row.week_start)).size),
          },
        ]
      : [
          {
            key: "queue",
            label: "The sampling queue",
            value: queue.error ? "could not be read" : "still loading",
          },
        ],
    apply: (items) => {
      const filter = items.find((item) => item.field_id === "qa-filter-pending");
      if (filter !== undefined) setPending(asText(filter.value) !== "all");
    },
  });

  return (
    <div className={ADMIN_PAGE_WIDE}>
      <PageHeader
        description={
          <>
            5% of each client&apos;s completed calls, drawn weekly by a published rule.{" "}
            <InfoTip label="How the draw works">
              <p>Newest week first, in the order the draw made.</p>
              <p>
                The draw can be checked and re-run: every call gets a fixed place from a seed
                that is printed on each review, so the same week always produces the same
                sample and nobody — including us — can quietly re-roll it. A call is never
                sampled twice.
              </p>
            </InfoTip>
          </>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          label="Which calls"
          value={pending ? "pending" : "all"}
          onValueChange={(value) => setPending(value === "pending")}
          options={[
            { value: "pending", label: "Not yet reviewed" },
            { value: "all", label: "Every sampled call" },
          ]}
        />
        {rows !== undefined && rows.length > 0 && <QueueSummary rows={rows} pending={pending} />}
      </div>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      <div>
        {queue.isLoading ? (
          <Skeleton rows={4} label="Loading the sampling queue" />
        ) : /* `!rows` as well as `error`: an offline browser PAUSES the query, which reports
               neither loading nor error with no data — and "every call reviewed" off a
               request nobody made is the sentence this branch exists to refuse. */
        queue.error || !rows ? (
          <div>
            <NoticeBox
              tone="warn"
              icon={<TriangleAlert aria-hidden className="h-5 w-5" />}
              title="The sampling queue could not be read"
            >
              <p className="mt-1">
                So we cannot say whether anything is waiting for review. This is not an empty
                queue.
              </p>
            </NoticeBox>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            message={pending ? "Every sampled call has been reviewed" : "Nothing sampled yet"}
          />
        ) : (
          <DataTable
            rows={rows}
            columns={COLUMNS}
            getRowId={sampleId}
            label="Calls drawn for the weekly QA spot-check"
          />
        )}
      </div>
    </div>
  );
}

function QueueSummary({ rows, pending }: { rows: QaSample[]; pending: boolean }) {
  const defects = rows.filter((row) => row.verdict === "defect").length;
  return (
    <p className="flex flex-wrap items-center gap-2 text-body">
      <span className="font-medium text-ink">
        {rows.length} {rows.length === 1 ? "call" : "calls"}
        {pending ? " waiting for review" : " sampled"}
      </span>
      {!pending && defects > 0 && (
        <StatusPill tone="stop">{defects} marked as a defect</StatusPill>
      )}
    </p>
  );
}

function sampleId(row: QaSample): string {
  return row.id;
}

function callLine(row: QaSample): string {
  return `${formatDuration(row.duration_s)} · ${row.direction} · ${row.agent_name}${
    row.outcome_tag ? ` · ${row.outcome_tag.replace(/_/g, " ")}` : ""
  }`;
}

function ReviewState({ row }: { row: QaSample }) {
  const verdict = row.verdict ? VERDICTS[row.verdict] : null;
  if (verdict) {
    return (
      <span>
        <span className="font-medium text-ink">{verdict.label}</span>
        <span className="block text-meta text-ink-muted">{formatIST(row.reviewed_at)}</span>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 font-medium text-brand-strong">
      Review this call
      <ArrowRight aria-hidden className="h-3.5 w-3.5" />
    </span>
  );
}

/*
 * One target per row (UX-DOCTRINE §4): the client's name is the link into the review,
 * stretched over the row. Opening the client is a secondary action in the row menu, which
 * sits above the stretched link. Below `sm` the dropped columns stack under the name.
 */
const COLUMNS: DataColumn<QaSample>[] = [
  {
    id: "client",
    header: "Client",
    cell: (row) => (
      <div className="min-w-0">
        <Link
          href={`/admin/qa-sampling/${row.id}`}
          className="rounded-sm font-medium text-ink after:absolute after:inset-0 after:content-[''] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {row.tenant_name}
          <span className="sr-only">, {row.verdict ? "open the review" : "review this call"}</span>
        </Link>
        <div className="text-meta text-ink-muted">/c/{row.tenant_slug}</div>
        <div className="mt-1.5 space-y-0.5 text-meta text-ink-muted sm:hidden">
          <p>
            {formatIST(row.started_at)} · {formatDuration(row.duration_s)} · {row.direction}
          </p>
          <p>
            Week of {row.week_start} · #{row.selection_rank} of {row.target}
          </p>
          <div className="pt-1 text-body">
            <ReviewState row={row} />
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "call",
    header: "Call",
    hideBelow: "sm",
    sort: { value: (row) => row.started_at, kind: "time", first: "desc" },
    cell: (row) => (
      <div>
        <div className="text-ink">{formatIST(row.started_at)}</div>
        <div className="text-meta text-ink-muted">{callLine(row)}</div>
      </div>
    ),
  },
  {
    id: "week",
    header: "Week sampled",
    hideBelow: "md",
    cell: (row) => (
      <div className="text-ink">
        {row.week_start}
        <div className="text-meta text-ink-muted">
          {row.population} {row.population === 1 ? "call" : "calls"} that week
        </div>
      </div>
    ),
  },
  {
    id: "drawn",
    header: "Drawn",
    hideBelow: "md",
    cell: (row) => (
      // The rank IN the draw and the size OF the draw: the pair that makes the sample
      // checkable. Guarded, because a `population` of 0 would print Infinity%.
      <div className="text-ink">
        #{row.selection_rank} of {row.target}
        {row.population > 0 && (
          <div className="text-meta text-ink-muted">
            {Math.round((row.target / row.population) * 100)}% sampled
          </div>
        )}
      </div>
    ),
  },
  {
    id: "review",
    header: "Review",
    hideBelow: "sm",
    cell: (row) => <ReviewState row={row} />,
  },
  {
    id: "more",
    header: "More",
    renderHeader: () => null,
    align: "right",
    cell: (row) => (
      <RowMenu
        label={row.tenant_name}
        items={[{ id: "client", label: "Open client", href: `/admin/tenants/${row.tenant_id}` }]}
      />
    ),
  },
];
