"use client";

import { FlashValue } from "@/components/console/valueFlash";
import { ProgressBar } from "@/components/interior/progress-bar";
import { TaskSteps } from "@/components/interior/task-steps";
import { formatCount, formatIST } from "@/components/ui";
import type { CampaignProgress } from "@/lib/api/campaigns";

import { campaignRun, runSentence } from "./campaignProgress";

/**
 * THE PRIMARY SURFACE OF A LAUNCHED CAMPAIGN: how far through the list it is, and what it
 * is doing right now (UX-DOCTRINE §1: the job of this screen while a campaign runs is
 * "is it working, and how far has it got").
 *
 * The figure and the bar are people called at least once out of everyone it may call;
 * the steps say which part of the run that is. All of it is the progress read, which the
 * live stream refetches on every campaign change (D-774), so it moves without a reload:
 * the figures mark a change with the value flash and the steps tick over in place.
 */
export function CampaignRun({ progress }: { progress: CampaignProgress }) {
  const run = campaignRun(progress);
  const live = progress.status === "running" || progress.status === "paused";
  const calling = run.hold === undefined && progress.status === "running" && run.onCallNow > 0;
  const facts: { label: string; value: number; hint?: string }[] = live
    ? [
        { label: "On a call now", value: run.onCallNow },
        { label: "Not called yet", value: run.notCalled },
        {
          label: "Waiting for another try",
          value: run.retriesWaiting,
          hint: run.retriesWaiting > 0 && run.nextRetryAt ? `Next ${formatIST(run.nextRetryAt)}` : undefined,
        },
        { label: "Spoke to your agent", value: run.spoke },
      ]
    : [
        { label: "Spoke to your agent", value: run.spoke },
        { label: "Never reached", value: Math.max(0, run.callable - run.spoke) },
      ];

  return (
    <section aria-labelledby="campaign-run" className="grid grid-cols-1 gap-x-12 gap-y-8 page-lg:grid-cols-[minmax(0,1fr)_15rem]">
      <div className="min-w-0 space-y-5">
        <div>
          <h2 id="campaign-run" className="text-heading text-ink">
            Progress
          </h2>
          <p className="mt-3 flex flex-wrap items-baseline gap-x-2 text-ink">
            <FlashValue value={String(run.called)} className="text-[2.25rem] font-semibold leading-none tracking-tight tabular-nums">
              {formatCount(run.called)}
            </FlashValue>
            <span className="text-body text-ink-muted">
              of {formatCount(run.callable)} {run.callable === 1 ? "person" : "people"} called
            </span>
          </p>
          <p role="status" className="mt-1 text-body text-ink-muted">
            {/* The one "working now" line on this screen gets the shimmer, and only while
                calls are actually in progress; a pause or a wait is plain text. */}
            <span className={calling ? "text-shimmer" : undefined}>{runSentence(progress, run)}</span>
          </p>
        </div>
        <ProgressBar
          value={run.called}
          max={Math.max(run.callable, 1)}
          label="Called at least once"
          completeLabel="Everyone has been called"
        />
        <TaskSteps
          size="md"
          steps={run.steps}
          current={run.current}
          hold={run.hold}
          label="Where this campaign is"
        />
      </div>

      <dl className="divide-y divide-line self-start border-y border-line page-lg:mt-9">
        {facts.map((fact) => (
          <div key={fact.label} className="flex items-baseline justify-between gap-4 py-3">
            <dt className="text-body text-ink-muted">
              {fact.label}
              {fact.hint ? <span className="block text-meta">{fact.hint}</span> : null}
            </dt>
            <dd className="text-body font-medium tabular-nums text-ink">
              <FlashValue value={String(fact.value)}>{formatCount(fact.value)}</FlashValue>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
