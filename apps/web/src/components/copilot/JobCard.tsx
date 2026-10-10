"use client";

import { Hourglass } from "lucide-react";

import { ProblemNotice } from "@/components/ui";
import { lookup } from "@/lib/lookup";
import type { Session } from "@/lib/api/client";
import { useCopilotJob } from "@/lib/api/copilot";
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
 * it runs, `useCopilotJob`). Steps that need the person's approval are named here and wait
 * in the Approvals inbox; nothing irreversible happens without them. The assistant's page
 * lists every task with the same progress (`JobProgress`).
 */
export function JobCard({ session, job }: { session: Session; job: CopilotJobFrame }) {
  const read = useCopilotJob(session, job.job_id);
  const current = read.data;
  const status = (current?.status ?? job.status) as CopilotJobFrame["status"];
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
    </div>
  );
}
