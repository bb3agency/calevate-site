"use client";

/**
 * WHICH CAMPAIGNS AND LINES TAKE A SET (D-1029): the checkbox list behind keeping the AI draft,
 * starting again from the standard set, and an operator's business-type move. A job nobody
 * customised (its list is empty or exactly a set the platform offered, `untouched` from the
 * server) starts ticked; one with its owner's own list starts unticked, so nothing anybody
 * chose is replaced without a tick. Each ticked job is sent with the digest of the list shown
 * here, so one changed meanwhile is refused rather than overwritten.
 */

import { useState } from "react";

import { CampaignStatusPill } from "@/app/c/[slug]/campaigns/campaignStatus";
import { STATE_DOT, StatusPill } from "@/components/console/statusPill";
import { TEXT_ACTION } from "@/components/console/section";
import { jobRef, type JobRef, type LeadFieldsJob } from "@/lib/api/leadFields";

/** A job's state in one mark: a campaign's own pill, a line's Live or Draft. */
export function JobStatusPill({ job }: { job: Pick<LeadFieldsJob, "kind" | "status" | "live"> }) {
  if (job.kind === "campaign") return <CampaignStatusPill status={job.status} />;
  return job.live ? (
    <StatusPill tone="ok">Live</StatusPill>
  ) : (
    <StatusPill tone="neutral" dot={STATE_DOT.draft}>
      Draft
    </StatusPill>
  );
}

/** The ticked jobs, starting from those nobody customised. */
export function useJobPicks(jobs: LeadFieldsJob[]) {
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(jobs.filter((job) => job.untouched).map((job) => `${job.kind}:${job.id}`)),
  );
  const refs: JobRef[] = jobs.filter((job) => picked.has(`${job.kind}:${job.id}`)).map(jobRef);
  return { picked, setPicked, refs };
}

export function ApplyToJobs({
  jobs,
  picks,
  disabled,
  legend,
}: {
  jobs: LeadFieldsJob[];
  picks: ReturnType<typeof useJobPicks>;
  disabled: boolean;
  /** What the ticks are for, read before the list ("Add them to"). */
  legend: string;
}) {
  const { picked, setPicked } = picks;
  if (jobs.length === 0) {
    return <p className="text-sm text-ink-muted">No campaigns or lines yet. New ones start with these.</p>;
  }
  const toggle = (key: string, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  const all = jobs.every((job) => picked.has(`${job.kind}:${job.id}`));
  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-sm font-medium text-ink">{legend}</legend>
      <div className="flex justify-end">
        <button
          type="button"
          className={`${TEXT_ACTION} text-xs`}
          onClick={() =>
            setPicked(all ? new Set() : new Set(jobs.map((job) => `${job.kind}:${job.id}`)))
          }
        >
          {all ? "Untick all" : "Tick all"}
        </button>
      </div>
      <ul className="divide-y divide-line border-y border-line">
        {jobs.map((job) => {
          const key = `${job.kind}:${job.id}`;
          return (
            <li key={key}>
              <label className="flex cursor-pointer items-center gap-3 py-2.5">
                <input
                  type="checkbox"
                  className="h-4 w-4 shrink-0 accent-[var(--brand-strong)]"
                  checked={picked.has(key)}
                  onChange={(event) => toggle(key, event.target.checked)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{job.name}</span>
                  <span className="block text-xs text-ink-muted">
                    {job.kind === "campaign" ? "Campaign" : "Inbound line"}
                    {job.untouched ? "" : " · has its own list"}
                  </span>
                </span>
                <span className="shrink-0">
                  <JobStatusPill job={job} />
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

/** What an apply did, from the counts the server returned. */
export function appliedSentence(result: { jobs_changed: number; jobs_waiting: number }): string {
  const { jobs_changed: changed, jobs_waiting: waiting } = result;
  if (changed === 0) return "Nothing changed. They already note these details.";
  const done = `${changed} ${changed === 1 ? "campaign or line" : "campaigns and lines"} updated.`;
  if (waiting === 0) return done;
  return `${done} ${waiting} will use them from their next start.`;
}
