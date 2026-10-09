"use client";

import { EmptyState } from "@/components/console/emptyState";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";
import { useCancelJob, useCopilotJobs, type CopilotJobOut } from "@/lib/copilot/workspace";

import { JobProgress } from "../JobProgress";

const STATUS: Record<string, { words: string; tone: string }> = {
  queued: { words: "Starting", tone: "bg-ink/[0.06] text-ink" },
  running: { words: "Working", tone: "bg-brand-soft text-brand-strong" },
  done: { words: "Finished", tone: "bg-ink/[0.06] text-ink-muted" },
  failed: { words: "Stopped", tone: "border border-warn-line bg-warn-soft text-warn" },
  cancelled: { words: "Cancelled", tone: "bg-ink/[0.06] text-ink-muted" },
};

/**
 * THE BACKGROUND TASKS: requests bigger than one answer, and every routine run (D-694).
 * Each shows what it has done, how it ended, and — while it runs — a Stop that halts it
 * before its next step. What it already did stays done, and stays undoable from the
 * activity log.
 */
export function TasksList({
  session,
  onOpenApprovals,
}: {
  session: Session;
  onOpenApprovals: () => void;
}) {
  const jobs = useCopilotJobs(session);
  if (jobs.error != null) {
    return <ProblemNotice error={jobs.error} onRetry={() => void jobs.refetch()} />;
  }
  if (jobs.data === undefined) return <Skeleton rows={3} label="Loading tasks…" />;
  if (jobs.data.jobs.length === 0) {
    return (
      <EmptyState
        message="No tasks yet."
        hint="Ask for something bigger than one answer — or set up a routine — and it runs here in the background."
      />
    );
  }
  return (
    <ul className="space-y-3" aria-label="Background tasks">
      {jobs.data.jobs.map((job) => (
        <TaskRow key={job.id} session={session} job={job} onOpenApprovals={onOpenApprovals} />
      ))}
    </ul>
  );
}

function TaskRow({
  session,
  job,
  onOpenApprovals,
}: {
  session: Session;
  job: CopilotJobOut;
  onOpenApprovals: () => void;
}) {
  const cancel = useCancelJob(session);
  const status = lookup(STATUS, job.status) ?? STATUS.done;
  const running = job.status === "queued" || job.status === "running";
  const waiting = job.progress.some((entry) => entry.kind === "approval");
  return (
    <li className="space-y-3 rounded-card border border-line bg-surface px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-medium text-ink [overflow-wrap:anywhere]">
            {job.goal}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">Asked {formatIST(job.created_at)}</p>
        </div>
        <span
          className={`inline-flex shrink-0 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${status.tone}`}
        >
          {status.words}
        </span>
      </div>
      <JobProgress job={job} />
      {job.result != null && !running && (
        <p className="whitespace-pre-wrap break-words text-sm text-ink [overflow-wrap:anywhere]">
          {job.result}
        </p>
      )}
      {cancel.error != null && <ProblemNotice error={cancel.error} />}
      {(running || waiting) && (
        <div className="flex flex-wrap gap-2">
          {waiting && (
            <button type="button" onClick={onOpenApprovals} className={SECONDARY_BUTTON_SM}>
              Review approvals
            </button>
          )}
          {running && (
            <button
              type="button"
              onClick={() => cancel.mutate(job.id)}
              disabled={cancel.isPending}
              className={SECONDARY_BUTTON_SM}
            >
              {cancel.isPending ? "Stopping…" : "Stop"}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
