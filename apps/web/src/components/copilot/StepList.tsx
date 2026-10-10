"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, Loader2, TriangleAlert } from "lucide-react";

import type { CopilotStep } from "@/lib/copilot/types";

/**
 * What the assistant DID to answer, under the answer.
 *
 * ## In words, not in machine names
 *
 * Each step reads as the server's plain label ("Searched your calls"), never as the tool's
 * identifier or its timing: those are for logs and support, and on a business owner's
 * screen "search_calls 93 ms" is noise (ux-writing). The identifier stays on the frame
 * (`step.tool`) and in the `title` of each row for anybody quoting it to support.
 *
 * ## Quiet by default
 *
 * While steps run, each running one shows as a line with a small spinner ("Searching your
 * calls…"), which is how somebody tells a slow answer from a stuck one. Once they settle
 * they fold into ONE muted line ("Checked 2 things") that opens to the list
 * (progressive disclosure: the answer is the content, the steps are the receipt). A step
 * that failed or was refused keeps the line in the warning tone and says so in words.
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
export function StepList({ steps, answer = "" }: { steps: CopilotStep[]; answer?: string }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (steps.length === 0) return null;

  const running = steps.filter((step) => step.status === "running");
  if (running.length > 0) {
    return (
      <ul className="space-y-1 text-meta text-ink-muted">
        {running.map((step) => (
          <li key={step.id} className="flex items-center gap-1.5" title={step.tool}>
            <Loader2 aria-hidden className="h-3.5 w-3.5 shrink-0 animate-spin text-ink-faint motion-reduce:animate-none" />
            {labelOf(step)}
          </li>
        ))}
      </ul>
    );
  }

  const problems = steps.filter((step) => step.status === "failed" || step.status === "refused").length;
  const summary =
    problems > 0
      ? problems === steps.length
        ? "Could not finish what it tried"
        : `${problems} of ${steps.length} steps did not finish`
      : `Checked ${steps.length === 1 ? "1 thing" : `${steps.length} things`}`;
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
        {problems > 0 ? (
          <TriangleAlert aria-hidden className="h-3.5 w-3.5 text-warn" />
        ) : (
          <Check aria-hidden className="h-3.5 w-3.5 text-ink-faint" />
        )}
        {summary}
        <ChevronDown aria-hidden className={`h-3.5 w-3.5 transition-transform duration-(--duration-fast) ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <ul id={listId} className="mt-1.5 space-y-1.5 border-l border-line pl-3">
          {steps.map((step) => {
            const detail = freshDetail(step.detail, shown);
            const failed = step.status === "failed" || step.status === "refused";
            return (
              <li key={step.id} title={step.tool}>
                <span className={`flex items-center gap-1.5 ${failed ? "text-warn" : "text-ink"}`}>
                  {failed ? <TriangleAlert aria-hidden className="h-3.5 w-3.5 shrink-0" /> : null}
                  {labelOf(step)}
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
