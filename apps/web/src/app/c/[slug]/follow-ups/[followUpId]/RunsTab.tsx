"use client";

import Link from "next/link";
import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ConfirmDialog } from "@/components/confirmDialog";
import { DataTable, type DataColumn } from "@/components/console/dataTable";
import { EmptyState } from "@/components/console/emptyState";
import { StatusPill } from "@/components/console/statusPill";
import { LoadMore } from "@/components/interior/load-more";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST, type NoticeTone } from "@/components/ui";
import {
  useFollowUpRuns,
  useStopFollowUpRun,
  type FollowUpOut,
  type FollowUpRunOut,
} from "@/lib/api/followUps";
import { useClientRealm } from "@/lib/api/session";
import { lookup } from "@/lib/lookup";

import { resultWords, runStatusWords } from "../followUpCopy";

const RUN_TONES: Record<string, NoticeTone> = {
  running: "ok",
  waiting: "neutral",
  done: "neutral",
  stopped: "warn",
};

/**
 * The leads going through this Follow-up, newest first, a page at a time. A lead still in
 * it can be stopped; stopping is confirmed because the next step will not happen.
 */
export function RunsTab({ followUp, canStop }: { followUp: FollowUpOut; canStop: boolean }) {
  const { session, href } = useClientRealm();
  const slug = session.orgSlug;
  const runs = useFollowUpRuns(session, followUp.id);
  const stop = useStopFollowUpRun(session, followUp.id);
  const feedback = useActionFeedback(stop, {
    errorDisplay: "inline",
    successToast: "Stopped",
    successDescription: "Nothing more happens for this lead here.",
  });
  const [stopping, setStopping] = useState<FollowUpRunOut | null>(null);
  const summaries = new Map(followUp.steps.map((step) => [step.id, step.summary]));
  const rows = runs.data?.pages.flatMap((page) => page.items);

  const leadName = (run: FollowUpRunOut) => run.lead_name ?? "Lead being added";

  const columns: DataColumn<FollowUpRunOut>[] = [
    {
      id: "lead",
      header: "Lead",
      cell: (run) =>
        run.lead_id ? (
          <Link
            href={href(`/c/${slug}/leads/${run.lead_id}`)}
            className="font-medium text-ink underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            {leadName(run)}
          </Link>
        ) : (
          <span className="text-ink-muted">{leadName(run)}</span>
        ),
    },
    {
      id: "where",
      header: "Where they are",
      card: "block",
      cell: (run) =>
        run.status === "done" || run.status === "stopped" ? (
          <span className="text-ink-muted">Finished</span>
        ) : (
          <span className="block min-w-0">
            <span className="block text-ink [overflow-wrap:anywhere]">
              {run.step_summary ?? summaries.get(run.step_id) ?? "Starting"}
            </span>
            {run.status === "waiting" && run.wake_at && (
              <span className="block text-meta text-ink-muted">Next: {formatIST(run.wake_at)}</span>
            )}
          </span>
        ),
    },
    {
      id: "last",
      header: "Last result",
      cell: (run) => <span className="text-ink-muted">{resultWords(run.last_result)}</span>,
    },
    {
      id: "started",
      header: "Started",
      hideBelow: "md",
      sort: { value: (run) => run.started_at, kind: "time", first: "desc" },
      cell: (run) => <span className="whitespace-nowrap text-ink-muted">{formatIST(run.started_at)}</span>,
    },
    {
      id: "status",
      header: "Status",
      flash: (run) => run.status,
      cell: (run) => (
        <StatusPill tone={run.goal_reached ? "ok" : (lookup(RUN_TONES, run.status) ?? "neutral")}>
          {run.goal_reached ? "Reached goal" : runStatusWords(run.status)}
        </StatusPill>
      ),
    },
    ...(canStop
      ? [
          {
            id: "stop",
            header: "Action",
            align: "right" as const,
            card: "block" as const,
            cell: (run: FollowUpRunOut) =>
              run.status === "running" || run.status === "waiting" ? (
                <button
                  type="button"
                  className={`${SECONDARY_BUTTON_SM} max-sm:min-h-11`}
                  aria-label={`Stop for ${leadName(run)}`}
                  onClick={() => {
                    stop.reset();
                    setStopping(run);
                  }}
                >
                  Stop
                </button>
              ) : null,
          },
        ]
      : []),
  ];

  if (runs.isLoading) return <Skeleton rows={4} label="Loading the leads in this Follow-up" />;
  if (!rows) return <ProblemNotice error={runs.error} onRetry={() => void runs.refetch()} />;

  return (
    <div className="space-y-3">
      {rows.length === 0 ? (
        <EmptyState message="No leads in it yet." align="start" />
      ) : (
        <div className="border-y border-line">
          <DataTable
            label="Leads in this Follow-up"
            rows={rows}
            columns={columns}
            getRowId={(run) => run.id}
            partialNote={runs.hasNextPage ? "Sorting the leads loaded so far." : undefined}
          />
          {runs.hasNextPage && (
            <LoadMore
              auto={false}
              hasMore={runs.hasNextPage}
              labels={{ idle: "Show more" }}
              onLoad={async () => {
                const result = await runs.fetchNextPage();
                if (result.isError) throw result.error;
                return result.hasNextPage;
              }}
              className="py-1"
            />
          )}
        </div>
      )}

      {stopping && (
        <ConfirmDialog
          title={`Stop for ${leadName(stopping)}?`}
          confirmLabel="Stop it"
          pendingLabel="Stopping…"
          cancelLabel="Keep going"
          status={feedback.status}
          error={stop.error}
          onCancel={() => {
            stop.reset();
            setStopping(null);
          }}
          onConfirm={() => stop.mutate(stopping.id, { onSuccess: () => setStopping(null) })}
        >
          <p>The next step will not happen for this lead.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
