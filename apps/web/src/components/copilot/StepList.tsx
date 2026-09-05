"use client";

import { Check, CircleSlash, Loader2, TriangleAlert } from "lucide-react";

import type { CopilotStep } from "@/lib/copilot/types";

/**
 * What the assistant is DOING, while it does it.
 *
 * ## Why this exists at all
 *
 * Before it, the only thing this panel could show between a question and its answer was a
 * two-row skeleton. That is fine for one sentence composed in two seconds and wrong for
 * what the assistant now is: a run that may read four things and change one, over tens of
 * seconds, on the person's own account. The pattern that current agentic products converge
 * on is to show each tool call with its inputs, its result and how long it took — it is
 * what lets somebody tell a slow answer from a stuck one, see WHICH of their data was
 * read, and notice a run heading somewhere they did not intend while there is still time
 * to say so.
 *
 * ## Two frames, one row
 *
 * The server sends `running` when a call starts and exactly one terminal frame when it
 * ends, sharing an `id`; the conversation hook upserts on that id, so one call is one row
 * that changes state. Appending both would render a single lookup as two lines and make a
 * two-lookup turn look like four.
 *
 * ## Why the tool's machine name is shown
 *
 * Deliberately, and not as a placeholder for a friendlier label. `agents_list` is what the
 * server logs, what the audit row and the tool registry call it, and what a person quoting
 * this panel in a support message needs to say. A prose label per tool would be a second
 * naming of every tool, kept in a different file from the registry, and the first one to
 * drift would be the one on screen. The SENTENCE a person reads is `detail`, which is the
 * tool's own answer.
 *
 * ## What is safe to render here
 *
 * `args` and `detail` are bounded previews the server has already stripped of invisible
 * characters and truncated (`service.MAX_STEP_CHARS`). They are the person's own account
 * data going back to the person's own screen — the request was refused outright if it
 * still carried an unredacted personal value — and they are never logged or stored on
 * either side. The list is not `aria-live`: it changes several times per second and
 * announcing every frame would talk over the answer, which is the thing a screen-reader
 * user is waiting for and which IS announced.
 */
export function StepList({ steps }: { steps: CopilotStep[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className="space-y-1">
      {steps.map((step) => (
        <li
          key={step.id}
          className="flex items-start gap-1.5 rounded-md bg-black/[0.03] px-2 py-1 text-xs dark:bg-white/[0.04]"
        >
          <StepIcon status={step.status} />
          <div className="min-w-0 flex-1">
            <p className="flex items-baseline gap-1.5">
              <span className="font-mono text-[11px] text-ink">{step.tool}</span>
              {step.elapsed_ms !== null && (
                <span className="text-ink-faint tabular-nums">{elapsed(step.elapsed_ms)}</span>
              )}
            </p>
            {/* The arguments are shown only while the call is IN FLIGHT. Once the result is
                on screen it is the more useful of the two and the row must stay one or two
                lines — a panel whose step list is taller than its answer has inverted the
                thing it was built to support. */}
            {step.status === "running" && step.args !== "" && (
              <p className="truncate font-mono text-[11px] text-ink-faint">{step.args}</p>
            )}
            {/* `break-words` because this is the TOOL'S OWN ANSWER, up to
                `service.MAX_STEP_CHARS` of it, and the panel is 24rem wide at most. A
                result with no space in it — a slug, a long id, a run of one word — has
                nothing to wrap on, and an unbroken 200-character run pushes the row past
                the panel's edge and takes the horizontal scrollbar with it. */}
            {step.detail !== null && step.detail !== "" && (
              <p className="break-words text-ink-muted">{step.detail}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/**
 * The status, as one glyph. `aria-hidden` on all four: the row's text already says which
 * tool ran and what it answered, and a screen reader reading "check mark" adds nothing a
 * person can act on.
 */
function StepIcon({ status }: { status: CopilotStep["status"] }) {
  const shared = "mt-0.5 h-3.5 w-3.5 shrink-0";
  if (status === "running") {
    return <Loader2 aria-hidden className={`${shared} animate-spin text-ink-faint`} />;
  }
  if (status === "refused") return <CircleSlash aria-hidden className={`${shared} text-ink-muted`} />;
  if (status === "failed") return <TriangleAlert aria-hidden className={`${shared} text-danger`} />;
  return <Check aria-hidden className={`${shared} text-ink-faint`} />;
}

/**
 * A duration a person can read at a glance.
 *
 * Milliseconds below a second and one decimal above it: "840 ms" and "2.4 s" are both
 * immediately comparable, where "2437 ms" makes somebody count digits. No unit smaller
 * than a millisecond, because the server measures in whole ones.
 */
function elapsed(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}
