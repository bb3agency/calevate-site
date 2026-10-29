"use client";

import { Hourglass } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { Session } from "@/lib/api/client";
import { useCopilotJob } from "@/lib/api/copilot";
import { useCancelJob } from "@/lib/copilot/workspace";
import type { CopilotJobFrame } from "@/lib/copilot/types";

import { JobProgress } from "./JobProgress";

const STATUS_WORDS: Record<CopilotJobFrame["status"], string> = {
  queued: "Starting",
  running: "Working on it",
  done: "Finished",
  failed: "Stopped",
  cancelled: "Cancelled",
};

/**
 * A background job the assistant started (D-694): what it is doing, its latest steps,
 * and — once it finishes — what it did.
 *
 * The job runs on after the answer ends, so this card reads its own progress (polled while
 * it runs, `useCopilotJob`). Every change it reaches is named here and waits in the
 * Approvals inbox (D-729); nothing changes without the person's click. The assistant's page
 * lists every task with the same progress (`JobProgress`). Stop is offered here as well as
 * there, because this card is where the person watches the job they just started.
 */
export function JobCard({ session, job }: { session: Session; job: CopilotJobFrame }) {
  const read = useCopilotJob(session, job.job_id);
  const cancel = useCancelJob(session);
  const stop = useActionFeedback(cancel, { errorDisplay: "inline" });
  const current = read.data;
  const status = (current?.status ?? job.status) as CopilotJobFrame["status"];
  const running = status === "queued" || status === "running";
  return (
    <div className="space-y-2 border-l-2 border-line pl-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <Hourglass aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
        {lookup(STATUS_WORDS, status) ?? status}
      </p>
      <p className="text-xs text-ink-muted">{current?.goal ?? job.goal}</p>
      {current !== undefined && <JobProgress job={current} />}
      {current?.result != null && (status === "done" || status === "failed") && (
        <p className="whitespace-pre-wrap text-xs text-ink">{current.result}</p>
      )}
      {read.isError && <ProblemNotice error={read.error} />}
      {cancel.error != null && <ProblemNotice error={cancel.error} />}
      {running && (
        <ActionButton
          variant="secondary-sm"
          status={stop.status}
          onClick={() => stop.run(job.job_id)}
          pendingLabel="Stopping…"
          successLabel="Stopped"
        >
          Stop
        </ActionButton>
      )}
    </div>
  );
}
