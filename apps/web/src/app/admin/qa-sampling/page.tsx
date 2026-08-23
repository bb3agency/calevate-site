"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, ClipboardCheck, TriangleAlert } from "lucide-react";

import {
  Card,
  EmptyState,
  FilterChip,
  NoticeBox,
  ProblemNotice,
  ScrollRegion,
  Skeleton,
  formatDuration,
  formatIST,
} from "@/components/ui";
import { useQaSamples, VERDICTS, type QaSample } from "@/lib/api/qaSamples";

/**
 * The QA sampling queue — which calls we spot-checked this week, and why those ones.
 *
 * SURFACES §1 asks for a spot-check of ~5% of calls per client per week with the queue
 * surfaced in admin. It did not exist. The draw is `apps/api/quality/sampling.py` and
 * the weekly tick is `apps/workers/qa_sampling.py`; this is where a reviewer works it.
 *
 * **This is a work QUEUE, not a report**, and three things follow:
 *
 * 1. **The draw's evidence is on the screen, not just in the database.** Every row says
 *    which week it came from, how many calls that week held, how many were drawn, and
 *    where this call ranked in the published order. A queue that showed only the calls
 *    would look like a list somebody chose by taste, and "we sample 5%" would be a claim
 *    with nothing behind it. The seed is on the row detail so the order can be re-run.
 * 2. **Every row ends in the review.** A sampled call nobody opened is not a control, so
 *    each row is a link into the call, and the pending filter is the default.
 * 3. **Empty is the GOOD state** — every drawn call has been reviewed. It is said as
 *    such, because a queue that renders "no data" at its own success reads as a failed
 *    load. A FAILED read gets a third branch: "nobody is waiting" is a claim about the
 *    world and a dead token is not evidence for it.
 *
 * Hard rule 6 is a property of the payload and nothing here widens it: the list carries
 * ids, timings and tags — no phone number, no transcript text, not even a redacted one.
 * The conversation is one click away, on the detail screen, where reading it is audited.
 *
 * The page carries no `<h1>`: the shell derives the title from the nav list it renders
 * the sidebar from (`app/admin/layout.tsx`).
 */
export default function QaSamplingPage() {
  const [pending, setPending] = useState(true);
  const queue = useQaSamples(pending);
  const rows = queue.data ?? [];
  const defects = rows.filter((row) => row.verdict === "defect");

  return (
    <div className="space-y-4 pb-12">
      <p className="text-sm text-ink-muted">
        Five percent of every client&apos;s completed calls each week, drawn by a published
        rule rather than by hand. Newest week first, in the order the draw made.
      </p>

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Which calls">
        <FilterChip label="Not yet reviewed" active={pending} onClick={() => setPending(true)} />
        <FilterChip label="Every sampled call" active={!pending} onClick={() => setPending(false)} />
      </div>

      {queue.error && <ProblemNotice error={queue.error} onRetry={() => void queue.refetch()} />}

      {!queue.isLoading && !queue.error && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="inline-flex items-center gap-2 font-semibold text-ink">
            <ClipboardCheck className="h-4 w-4 text-ink-faint" />
            {rows.length} {rows.length === 1 ? "call" : "calls"}
            {pending ? " waiting for review" : " sampled"}
          </span>
          {!pending && defects.length > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              <TriangleAlert className="h-3.5 w-3.5" />
              {defects.length} marked as a defect
            </span>
          )}
        </div>
      )}

      <Card bodyClassName="p-0">
        {queue.isLoading ? (
          <div className="p-6">
            <Skeleton rows={4} />
          </div>
        ) : /* `|| !queue.data` because a failed read is not the only way to have no
               answer: while the browser is offline TanStack PAUSES the query rather than
               running it (`fetchStatus: "paused"`), and a paused query reports
               `isLoading === false` and `error === null` with `data === undefined`. This
               arm used to be skipped in that state and the empty state below told an
               operator every sampled call had been reviewed, off a request nobody made. */
        queue.error || !queue.data ? (
          <div className="p-6">
            <NoticeBox
              tone="warn"
              icon={<TriangleAlert className="h-5 w-5" />}
              title="The sampling queue could not be read"
            >
              <p className="mt-1">
                So we cannot say whether anything is waiting for review. This is not an empty
                queue.
              </p>
            </NoticeBox>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={pending ? "Every sampled call has been reviewed" : "Nothing sampled yet"}
            hint={
              pending
                ? "The weekly draw refills this list every Monday, from the calls each client completed in the week that just closed."
                : "The draw runs once a week and takes five percent of each client's completed calls. A client with no completed calls yet has nothing to sample."
            }
          />
        ) : (
          <ScrollRegion label="Calls drawn for the weekly QA spot-check">
            <table className="w-full min-w-[860px] text-sm">
              <caption className="sr-only">Calls drawn for the weekly QA spot-check</caption>
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wider text-ink-faint">
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Client
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Call
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Week sampled
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Drawn
                  </th>
                  <th scope="col" className="px-6 py-3 font-semibold">
                    Review
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((row) => (
                  <SampleRow key={row.id} row={row} />
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </Card>

      <p className="text-xs text-ink-faint">
        The draw can be checked and re-run: every call gets a fixed place from a seed that is
        printed on each review, so the same week always produces the same sample and nobody —
        including us — can quietly re-roll it. A call is never sampled twice.
      </p>
    </div>
  );
}

function SampleRow({ row }: { row: QaSample }) {
  const verdict = row.verdict ? VERDICTS[row.verdict] : null;
  return (
    <tr className="align-top hover:bg-black/[0.02] dark:hover:bg-white/[0.03]">
      <td className="px-6 py-3">
        <Link
          href={`/admin/tenants/${row.tenant_id}`}
          className="font-semibold text-ink hover:underline"
        >
          {row.tenant_name}
        </Link>
        <div className="text-xs text-ink-faint">/c/{row.tenant_slug}</div>
      </td>
      <td className="px-6 py-3">
        <div className="text-ink">{formatIST(row.started_at)}</div>
        <div className="text-xs text-ink-faint">
          {formatDuration(row.duration_s)} · {row.direction} · {row.agent_name}
          {row.outcome_tag ? ` · ${row.outcome_tag.replace(/_/g, " ")}` : ""}
        </div>
      </td>
      <td className="px-6 py-3 text-ink">
        {row.week_start}
        <div className="text-xs text-ink-faint">
          {row.population} {row.population === 1 ? "call" : "calls"} that week
        </div>
      </td>
      <td className="px-6 py-3 text-ink">
        {/* The rank IN the draw, and the size OF the draw. This is the pair that makes
            the sample checkable rather than merely plausible. */}
        #{row.selection_rank} of {row.target}
        <div className="text-xs text-ink-faint">{Math.round((row.target / row.population) * 100)}% sampled</div>
      </td>
      <td className="px-6 py-3">
        {verdict ? (
          <div>
            <span className="font-medium text-ink">{verdict.label}</span>
            <div className="text-xs text-ink-faint">{formatIST(row.reviewed_at)}</div>
          </div>
        ) : (
          <Link
            href={`/admin/qa-sampling/${row.id}`}
            className="inline-flex items-center gap-1.5 font-medium text-brand-strong hover:underline"
          >
            Review this call
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        )}
      </td>
    </tr>
  );
}
