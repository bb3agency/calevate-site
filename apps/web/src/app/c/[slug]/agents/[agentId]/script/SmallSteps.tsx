"use client";

import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";

import { FIELD, FIELD_HINT, FIELD_LABEL, QUIET_ICON_BUTTON } from "@/components/ui";
import { TEXT_ACTION } from "@/components/console/section";

import { addSmallStep, chars, moveSmallStep, type Issue, type Limits, type SmallStep } from "./scriptModel";

/**
 * A STEP'S SMALL STEPS (D-908): the ordered actions a caller does one at a time while the
 * agent waits, such as tapping through an app install. They go into the agent's instructions
 * under the step's name rather than into the step itself, so a guided call is not squeezed
 * into the step's 600 letters, and the step keeps one short line pointing at them.
 *
 * Built for a phone: each small step is a stacked card with its number, its two fields one
 * under the other, and touch-sized move and remove buttons, so nothing sits side by side on
 * a 375 px screen.
 */
export function SmallSteps({
  id,
  steps,
  limits,
  issues,
  onChange,
}: {
  id: string;
  steps: SmallStep[];
  limits: Limits;
  /** This step's issues; the ones named `procedure-<n>` belong to small step n. */
  issues: Issue[];
  onChange: (steps: SmallStep[]) => void;
}) {
  const set = (i: number, patch: Partial<SmallStep>) =>
    onChange(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const full = steps.length >= limits.maxProcedureSteps;
  return (
    <fieldset className="space-y-3">
      <legend className={FIELD_LABEL}>Small steps, one at a time</legend>
      <span className={FIELD_HINT}>
        For callers doing it as you talk. One at a time.{" "}
        <span className="tabular-nums">
          {steps.length} of {limits.maxProcedureSteps}
        </span>
      </span>
      {steps.length > 0 && (
        <ol className="space-y-3">
          {steps.map((step, i) => {
            const errs = issues.filter((issue) => issue.field === `procedure-${i}`);
            const errId = `${id}-${i}-err`;
            return (
              <li key={i} className="rounded-md border border-line p-3">
                <div className="flex items-center gap-1">
                  <span className="mr-auto text-meta font-medium text-ink">Small step {i + 1}</span>
                  <button
                    type="button"
                    className={QUIET_ICON_BUTTON}
                    aria-label={`Move small step ${i + 1} earlier`}
                    disabled={i === 0}
                    onClick={() => onChange(moveSmallStep(steps, i, i - 1))}
                  >
                    <ArrowUp aria-hidden className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className={QUIET_ICON_BUTTON}
                    aria-label={`Move small step ${i + 1} later`}
                    disabled={i === steps.length - 1}
                    onClick={() => onChange(moveSmallStep(steps, i, i + 1))}
                  >
                    <ArrowDown aria-hidden className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    className={QUIET_ICON_BUTTON}
                    aria-label={`Remove small step ${i + 1}`}
                    onClick={() => onChange(steps.filter((_, j) => j !== i))}
                  >
                    <X aria-hidden className="h-4 w-4" />
                  </button>
                </div>
                <label className="mt-2 block">
                  <span className="text-meta text-ink-muted">What they do</span>
                  <textarea
                    className={`${FIELD} mt-0.5`}
                    rows={2}
                    value={step.action}
                    maxLength={limits.procedureStepMax}
                    placeholder="For example: Ask them to keep their reference number ready."
                    aria-invalid={errs.length > 0 || undefined}
                    aria-describedby={errs.length ? errId : undefined}
                    onChange={(e) => set(i, { action: e.target.value })}
                  />
                </label>
                <label className="mt-2 block">
                  <span className="text-meta text-ink-muted">Wait until (optional)</span>
                  <input
                    className={`${FIELD} mt-0.5`}
                    value={step.wait_for}
                    maxLength={limits.procedureWaitMax}
                    placeholder="For example: they say they have it"
                    onChange={(e) => set(i, { wait_for: e.target.value })}
                  />
                </label>
                {chars(step.action) >= limits.procedureStepMax * 0.8 && (
                  <p className="mt-1 text-meta tabular-nums text-ink-muted">
                    {limits.procedureStepMax - chars(step.action)} letters left.
                  </p>
                )}
                {errs.length > 0 && (
                  <p id={errId} className="mt-1 text-meta text-danger">
                    {errs.map((e) => e.message).join(" ")}
                  </p>
                )}
              </li>
            );
          })}
        </ol>
      )}
      {full ? (
        <p className="text-meta text-ink-muted">
          {limits.maxProcedureSteps} small steps at most. Put the rest in the next step.
        </p>
      ) : (
        <button
          type="button"
          className={`${TEXT_ACTION} inline-flex items-center gap-1`}
          onClick={() => onChange(addSmallStep(steps, limits.maxProcedureSteps))}
        >
          <Plus aria-hidden className="h-3.5 w-3.5" />
          Add a small step
        </button>
      )}
    </fieldset>
  );
}
