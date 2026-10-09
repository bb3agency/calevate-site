"use client";

import { ProgressBar } from "@/components/interior/progress-bar";
import { TaskSteps, type TaskStep } from "@/components/interior/task-steps";
import type { CopilotJobOut } from "@/lib/api/copilot";

/** How many of a task's latest steps are listed. The rest stay in the activity log. */
const SHOWN = 5;

/**
 * WHAT A BACKGROUND TASK HAS DONE SO FAR, AND WHETHER IT IS STILL GOING — shared by the
 * panel's job card and the workspace's task list so the two cannot tell different stories.
 *
 * A task has no percentage: it is a conversation with tools, and nobody knows its length in
 * advance. So the bar is indeterminate while it runs, and the steps are what it has
 * actually done, newest last, with "Working on it" as the step in progress.
 */
export function JobProgress({ job }: { job: CopilotJobOut }) {
  const running = job.status === "queued" || job.status === "running";
  const done: TaskStep[] = job.progress.slice(-SHOWN).map((entry, index) => ({
    id: `${entry.at}-${index}`,
    label: entry.text,
  }));
  const steps: TaskStep[] = running
    ? [...done, { id: "now", label: job.status === "queued" ? "Starting" : "Working on it" }]
    : done;
  return (
    <div className="space-y-2">
      {running && (
        <ProgressBar
          value={null}
          label={job.status === "queued" ? "Starting" : "Working on it"}
          pendingLabel="In progress"
        />
      )}
      {steps.length > 0 && (
        <TaskSteps
          steps={steps}
          current={running ? steps.length - 1 : steps.length}
          failed={job.status === "failed"}
          label="What this task has done"
        />
      )}
    </div>
  );
}
