"use client";

import { CheckCircle2, CircleMinus, CircleX, Hourglass, type LucideIcon } from "lucide-react";

import { ActionButton, useActionFeedback } from "@/components/arc/feedback";
import { NOTICE_BAR, ProblemNotice, TONE_INK, type NoticeTone } from "@/components/ui";
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

/** The card's rule and glyph per status: blue while it runs, green done, red failed. */
const STATUS_LOOK: Record<CopilotJobFrame["status"], { tone: NoticeTone; icon: LucideIcon }> = {
  queued: { tone: "info", icon: Hourglass },
  running: { tone: "info", icon: Hourglass },
  done: { tone: "ok", icon: CheckCircle2 },
  failed: { tone: "stop", icon: CircleX },
  cancelled: { tone: "neutral", icon: CircleMinus },
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
  const look = lookup(STATUS_LOOK, status) ?? STATUS_LOOK.running;
  return (
    <div className={`space-y-2 border-l-2 pl-3 ${NOTICE_BAR[look.tone]}`}>
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <look.icon aria-hidden className={`h-3.5 w-3.5 ${TONE_INK[look.tone]}`} />
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
