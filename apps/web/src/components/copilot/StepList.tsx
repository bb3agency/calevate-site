"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, CircleMinus, Loader2, RotateCcw } from "lucide-react";

import { TONE_INK } from "@/components/ui";
import type { CopilotStep } from "@/lib/copilot/types";

/**
 * What the assistant DID to answer, under the answer.
 *
 * ## In words, not in machine names
 *
 * Each step reads as the server's plain label ("Searched your calls"), never as the tool's
 * identifier or its timing: those are for logs and support, and on a business owner's
 * screen "search_calls 93 ms" is noise (ux-writing). The identifier stays on the frame
 * (`step.tool`), and in the admin realm only it is each row's hover `title` for support.
 *
 * ## Quiet by default
 *
 * While steps run, each running one shows as a line with a small spinner ("Searching your
 * calls…"), which is how somebody tells a slow answer from a stuck one. Once they settle
 * they fold into ONE muted line ("Checked 2 things") that opens to the list
 * (progressive disclosure: the answer is the content, the steps are the receipt).
 *
 * ## Calm about what did not finish
 *
 * A step that failed or was refused says so in words, in the same muted ink as the rest:
 * the answer above already says what Pip could and could not do, and nothing here asks the
 * reader to act, so the warning colour would be an alarm with no action behind it. A step
 * that failed and then succeeded when Pip tried the same thing again is not a problem at
 * all: it reads "Tried again", without the reason it was first refused, and is not counted
 * in the summary.
 *
 * ## No repeated sentences
 *
 * A step's own result line is shown only when the list is open, only once per distinct
 * sentence, and only when the answer above has not already said it — an empty account
 * produced the same "no calls yet" sentence three times, once in the answer and once per
 * lookup.
 *
 * The list is not `aria-live`: it changes several times per second while a run is going,
 * and announcing every frame would talk over the answer, which IS announced.
 */
export function StepList({
  steps,
  answer = "",
  realm = "client",
}: {
  steps: CopilotStep[];
  answer?: string;
  realm?: "client" | "admin";
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (steps.length === 0) return null;
  // The tool's name on hover is for support, which only the operator's console is.
  const hover = (step: CopilotStep) => (realm === "admin" ? step.tool : undefined);

  const running = steps.filter((step) => step.status === "running");
  if (running.length > 0) {
    return (
      <ul className="space-y-1 text-meta text-ink-muted">
        {running.map((step) => (
          <li key={step.id} className="flex items-center gap-1.5" title={hover(step)}>
            <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin text-ink-faint motion-reduce:animate-none" />
            {labelOf(step)}
          </li>
        ))}
      </ul>
    );
  }

  const retried = recoveredSteps(steps);
  const problems = steps.filter((step) => isProblem(step) && !retried.has(step.id)).length;
  // A retry that worked is one thing done, not two.
  const counted = steps.length - retried.size;
  const summary =
    problems > 0
      ? problems === counted
        ? "Could not finish what it tried"
        : `${problems} of ${counted} steps did not finish`
      : `Checked ${counted === 1 ? "1 thing" : `${counted} things`}`;
  const shown = new Set<string>([normalise(answer)]);

  return (
    <div className="text-meta text-ink-muted">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        className="press inline-flex items-center gap-1.5 rounded-sm hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand touch:min-h-11"
      >
        {/* The summary's glyph carries the outcome's colour so a reader sees "something
            did not finish" without opening the list; the steps inside stay quiet. */}
        {problems > 0 ? (
          <CircleMinus aria-hidden className={`h-3.5 w-3.5 ${TONE_INK.warn}`} />
        ) : (
          <Check aria-hidden className={`h-3.5 w-3.5 ${TONE_INK.ok}`} />
        )}
        {summary}
        <ChevronDown aria-hidden className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <ul id={listId} className="mt-1.5 space-y-1.5 border-l border-line pl-3">
          {steps.map((step) => {
            const again = retried.has(step.id);
            // Why a retried step was refused is no longer true of anything on screen.
            const detail = again ? null : freshDetail(step.detail, shown);
            const failed = isProblem(step) && !again;
            return (
              <li key={step.id} title={hover(step)}>
                <span className={`flex items-center gap-1.5 ${failed || again ? "text-ink-muted" : "text-ink"}`}>
                  {again ? <RotateCcw aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-faint" /> : null}
                  {failed ? <CircleMinus aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-faint" /> : null}
                  {again ? "Tried again" : labelOf(step)}
                </span>
                {detail ? <span className="block break-words">{detail}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function isProblem(step: CopilotStep): boolean {
  return step.status === "failed" || step.status === "refused";
}

/** Problem steps that a later run of the same tool finished: a retry that worked. */
function recoveredSteps(steps: CopilotStep[]): Set<string> {
  const recovered = new Set<string>();
  steps.forEach((step, index) => {
    if (!isProblem(step)) return;
    if (steps.slice(index + 1).some((later) => later.tool === step.tool && later.status === "done")) {
      recovered.add(step.id);
    }
  });
  return recovered;
}

/** The server's words for the step, in the tense of its status. */
function labelOf(step: CopilotStep): string {
  const label = step.label?.trim();
  if (step.status === "failed" || step.status === "refused") {
    if (!label) return "One step did not finish";
    const doing = label.replace(/…$/, "");
    return `Could not finish ${doing.charAt(0).toLowerCase()}${doing.slice(1)}`;
  }
  if (label) return label;
  return step.status === "running" ? "Working…" : "Looked something up";
}

function normalise(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase();
}

/** The detail, unless the answer or an earlier step already said it. Records what it shows. */
function freshDetail(detail: string | null | undefined, shown: Set<string>): string | null {
  if (!detail) return null;
  const key = normalise(detail);
  if (key === "") return null;
  for (const seen of shown) if (seen.includes(key)) return null;
  shown.add(key);
  return detail;
}
