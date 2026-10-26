"use client";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { EmptySketch } from "@/components/console/emptySketch";
import { StatusPill } from "@/components/console/statusPill";
import { EmptyState } from "@/components/console/emptyState";
import { ProblemNotice, SECONDARY_BUTTON_SM, Skeleton, formatIST, type NoticeTone } from "@/components/ui";
import type { Session } from "@/lib/api/client";
import { lookup } from "@/lib/lookup";
import { useCancelJob, useCopilotJobs, type CopilotJobOut } from "@/lib/copilot/workspace";

import { useRecentPlans } from "@/lib/copilot/plans";

import { JobProgress } from "../JobProgress";
import { PlanCard } from "../PlanCard";

const STATUS: Record<string, { words: string; tone: NoticeTone }> = {
  queued: { words: "Starting", tone: "neutral" },
  running: { words: "Working", tone: "ok" },
  done: { words: "Finished", tone: "neutral" },
  failed: { words: "Stopped", tone: "warn" },
  cancelled: { words: "Cancelled", tone: "neutral" },
};

/**
 * THE BACKGROUND TASKS: requests bigger than one answer, and every routine run (D-694).
 * Each shows what it has done, how it ended, and — while it runs — a Stop that halts it
 * before its next step. A task changes nothing itself: every change it reached waits in
 * Approvals (D-729).
 */
export function TasksList({
  session,
  onOpenApprovals,
}: {
  session: Session;
  onOpenApprovals: () => void;
}) {
  const jobs = useCopilotJobs(session);
  const plans = useRecentPlans(session);
  // PLANS FIRST (D-893): a change over many records, approved once, running here. A failed
  // read says so rather than reading as "no plans".
  const planList = plans.isSuccess ? plans.data.plans : [];
  const planSection = plans.isError ? (
    <ProblemNotice error={plans.error} onRetry={() => void plans.refetch()} />
  ) : planList.length > 0 ? (
      <section aria-label="Plans" className="space-y-3">
        <h3 className="text-sm font-medium text-ink">Plans</h3>
        <ul className="space-y-4">
          {planList.map((plan) => (
            <li key={plan.id}>
              <PlanCard session={session} planId={plan.id} />
            </li>
          ))}
        </ul>
      </section>
    ) : null;
  if (jobs.error != null) {
    return <ProblemNotice error={jobs.error} onRetry={() => void jobs.refetch()} />;
  }
  if (jobs.data === undefined) return <Skeleton rows={3} label="Loading tasks…" />;
  if (jobs.data.jobs.length === 0) {
    return (
      <div className="space-y-6">
        {planSection}
        {plans.isSuccess && planList.length === 0 && (
          <EmptyState
            illustration={<EmptySketch kind="chat" />}
            message="No tasks yet."
            hint="Ask for something bigger than one answer — or set up a routine — and it runs here in the background."
          />
        )}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {planSection}
      <ul className="divide-y divide-line border-y border-line" aria-label="Background tasks">
        {jobs.data.jobs.map((job) => (
          <TaskRow key={job.id} session={session} job={job} onOpenApprovals={onOpenApprovals} />
        ))}
      </ul>
    </div>
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
  const cancelFeedback = useActionFeedback(cancel, { errorDisplay: "inline" });
  const status = lookup(STATUS, job.status) ?? STATUS.done;
  const running = job.status === "queued" || job.status === "running";
  const waiting = job.progress.some((entry) => entry.kind === "approval");
  return (
    <li className="space-y-3 py-3.5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-medium text-ink [overflow-wrap:anywhere]">
            {job.goal}
          </p>
          <p className="mt-0.5 text-xs text-ink-muted">Asked {formatIST(job.created_at)}</p>
        </div>
        <StatusPill tone={status.tone}>{status.words}</StatusPill>
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
            <ActionButton
              variant="secondary-sm"
              status={cancelFeedback.status}
              onClick={() => cancelFeedback.run(job.id)}
              pendingLabel="Stopping…"
              successLabel="Stopped"
            >
              Stop
            </ActionButton>
          )}
        </div>
      )}
    </li>
  );
}
