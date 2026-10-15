import type { TaskStep, TaskStepHold } from "@/components/interior/task-steps";
import { formatCount, formatIST } from "@/components/ui";
import type { CampaignProgress } from "@/lib/api/campaigns";

/**
 * WHERE A LAUNCHED CAMPAIGN IS, as steps (D-773, founder 15 Oct 2026: the steps stay on
 * screen the whole time the campaign runs).
 *
 * Every step is read from `GET /v1/campaigns/{id}` and nothing is estimated:
 *
 * - **List ready**: the people on it, and how many the do-not-call scrub took off
 *   (`contacts.dnc_blocked`).
 * - **Compliance checks passed**: a campaign only has a `launched_at` once the launch gate
 *   let it through, so this step is done for every launched campaign.
 * - **Calling everyone once**: people not yet tried are `pending` minus `retries_waiting`.
 * - **Trying again**: only when the campaign retries at all (`retry_policy.max_attempts`).
 * - **All calls made**: the server's `completed`.
 *
 * A paused campaign, a running one the gate will not let dial (`not_calling`) and one
 * outside its calling hours are HELD on the step they reached, not spinning: nothing is
 * being called, and a spinner would say otherwise. A stopped campaign is held for good.
 */
export type CampaignRun = {
  steps: TaskStep[];
  current: number;
  hold: TaskStepHold | undefined;
  /** Everyone the campaign may call: the list minus the do-not-call matches. */
  callable: number;
  /** Of those, tried at least once or on a call right now. */
  called: number;
  notCalled: number;
  onCallNow: number;
  retriesWaiting: number;
  nextRetryAt: string | null;
  spoke: number;
};

function count(progress: CampaignProgress, status: string): number {
  return progress.contacts[status] ?? 0;
}

export function campaignRun(progress: CampaignProgress): CampaignRun {
  const dnc = count(progress, "dnc_blocked");
  const pending = count(progress, "pending");
  const onCallNow = count(progress, "dialing");
  const retriesWaiting = Math.min(progress.retries_waiting ?? 0, pending);
  const notCalled = pending - retriesWaiting;
  const callable = Math.max(0, progress.total - dnc);
  const called = Math.max(0, callable - notCalled);
  const spoke = count(progress, "connected") + count(progress, "completed");
  const retries = progress.retry_policy.max_attempts > 1;
  const finished = progress.status === "completed";
  const stopped = progress.status === "cancelled";

  const steps: TaskStep[] = [
    {
      id: "list",
      label: `List ready: ${formatCount(progress.total)} ${progress.total === 1 ? "person" : "people"}`,
      meta: dnc > 0 ? `${formatCount(dnc)} on do-not-call, skipped` : "Nobody on do-not-call",
    },
    {
      id: "checks",
      label: "Compliance checks passed",
      meta: progress.launched_at ? `Started ${formatIST(progress.launched_at)}` : undefined,
    },
    {
      id: "first",
      label: "Calling everyone once",
      meta: `${formatCount(called)} of ${formatCount(callable)}${onCallNow > 0 ? ` · ${formatCount(onCallNow)} on a call now` : ""}`,
    },
    ...(retries
      ? [
          {
            id: "retry",
            label: "Retrying people who didn't pick up",
            meta:
              retriesWaiting > 0
                ? `${formatCount(retriesWaiting)} waiting${progress.next_retry_at ? ` · next ${formatIST(progress.next_retry_at)}` : ""}`
                : undefined,
          },
        ]
      : []),
    {
      id: "done",
      label: stopped ? "Stopped for good" : finished ? "All calls made" : "Wrapping up",
    },
  ];

  const retryIndex = steps.findIndex((s) => s.id === "retry");
  const lastIndex = steps.length - 1;
  let current: number;
  if (finished) current = steps.length;
  else if (stopped) current = lastIndex;
  else if (notCalled > 0) current = 2;
  else if (retryIndex >= 0 && (retriesWaiting > 0 || onCallNow > 0)) current = retryIndex;
  else if (onCallNow > 0) current = 2;
  else current = lastIndex;

  const held =
    progress.status === "paused" ||
    (progress.status === "running" &&
      (progress.not_calling.length > 0 || progress.waiting_for_calling_hours));
  const hold: TaskStepHold | undefined = stopped ? "stopped" : held ? "paused" : undefined;

  return {
    steps,
    current,
    hold,
    callable,
    called,
    notCalled,
    onCallNow,
    retriesWaiting,
    nextRetryAt: progress.next_retry_at ?? null,
    spoke,
  };
}

/** The one line under the progress figure: what the campaign is doing this minute. */
export function runSentence(progress: CampaignProgress, run: CampaignRun): string {
  switch (progress.status) {
    case "completed":
      return "Finished. Everyone on the list was called as many times as you allowed.";
    case "cancelled":
      return run.notCalled > 0
        ? `Stopped. ${formatCount(run.notCalled)} ${run.notCalled === 1 ? "person was" : "people were"} never called.`
        : "Stopped.";
    case "paused":
      return "Paused. Nobody is being called.";
    default:
      if (progress.not_calling.length > 0) return "Not calling anyone right now.";
      if (progress.waiting_for_calling_hours) {
        const hours = progress.calling_hours;
        return `Waiting for calling hours. Calls go out ${hours ? `${hours.start}–${hours.end}` : "9am–9pm"} IST.`;
      }
      if (run.onCallNow > 0) {
        return `Calling now: ${formatCount(run.onCallNow)} ${run.onCallNow === 1 ? "call" : "calls"} in progress.`;
      }
      return "Calling. The next calls go out shortly.";
  }
}
