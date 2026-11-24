"use client";

/**
 * WHERE PEOPLE DROP OFF (founder, 24 Nov 2026): a bar per step of the script, how many of the
 * judged calls reached it, did not, or were unclear (`calls.step_progress`, D-1036), and the
 * step that loses the most people with one press that asks Pip to fix it. Step names only,
 * never what anyone said (hard rule 6). Below the minimum sample it says so instead of
 * drawing noise.
 */

import { formatCount } from "@/components/ui";
import { stepFixInstruction, type DiagnosisStep } from "@/lib/api/improve";

import { AskPipFix } from "./AskPipFix";
import { ImproveCard, WithDiagnosis, type ImproveCardProps } from "./ImproveCard";

export const DROP_OFF_TITLE = "Where people drop off";

export function DropOffCard({ holder, canWrite, refusal }: ImproveCardProps) {
  return (
    <ImproveCard
      title={DROP_OFF_TITLE}
      hint="How far calls get through the script."
      info="A step counts as reached only when the person's own words show it."
    >
      <WithDiagnosis holder={holder} label="Reading where calls stop">
        {({ drop_off: drop, window_days }) => {
          if (drop.judged_calls === 0) {
            return <p className="text-meta text-ink-muted">No calls checked yet.</p>;
          }
          if (drop.judged_calls < drop.min_calls) {
            return (
              <p className="text-meta text-ink-muted">
                Too few calls to say yet: {formatCount(drop.judged_calls)} of{" "}
                {formatCount(drop.min_calls)} checked.
              </p>
            );
          }
          const worst = drop.steps.find((s) => s.step === drop.worst_step) ?? null;
          return (
            <>
              {worst ? (
                <p className="mb-3 text-body text-ink">
                  Most people stop at step {worst.step}: {worst.name || "unnamed"}.
                </p>
              ) : (
                <p className="mb-3 text-meta text-ink-muted">No step loses people yet.</p>
              )}
              <StepBars steps={drop.steps} total={drop.judged_calls} worst={drop.worst_step} />
              <p className="mt-2 text-meta text-ink-muted">
                {formatCount(drop.judged_calls)} calls, last {window_days} days.
              </p>
              {worst && (
                <div className="mt-3">
                  <AskPipFix
                    holder={holder}
                    instruction={stepFixInstruction(worst)}
                    label="Fix this step"
                    canWrite={canWrite}
                    refusal={refusal}
                  />
                </div>
              )}
            </>
          );
        }}
      </WithDiagnosis>
    </ImproveCard>
  );
}

function StepBars({
  steps,
  total,
  worst,
}: {
  steps: DiagnosisStep[];
  total: number;
  worst: number | null;
}) {
  const share = (n: number) => `${total > 0 ? (n / total) * 100 : 0}%`;
  return (
    <>
    <p aria-hidden className="mb-2 flex flex-wrap gap-x-3 text-meta text-ink-muted">
      <Swatch className="bg-brand">Reached</Swatch>
      <Swatch className="bg-warn">Not reached</Swatch>
      <Swatch className="bg-line">Not clear</Swatch>
    </p>
    <ol className="space-y-2" aria-label="Calls that reached each step">
      {steps.map((s) => {
        const isWorst = s.step === worst;
        return (
          <li key={s.step} className={isWorst ? "rounded-sm bg-warn-soft -mx-1.5 px-1.5 py-1" : ""}>
            <div className="flex items-baseline justify-between gap-3 text-meta">
              <span className="min-w-0 text-ink [overflow-wrap:anywhere]">
                <span className="text-ink-muted tabular-nums">{s.step}.</span> {s.name}
                {isWorst && <span className="sr-only"> (most people stop here)</span>}
                <span className="sr-only">
                  {`: ${s.reached} reached, ${s.not_reached} not reached, ${s.unclear} not clear`}
                </span>
              </span>
              <span className="shrink-0 text-ink tabular-nums">
                {formatCount(s.reached)} reached
                {s.lost_here > 0 && (
                  <span className="text-warn"> · {formatCount(s.lost_here)} lost here</span>
                )}
              </span>
            </div>
            {/* The drawing of the line above: reached, then not reached, then unclear. */}
            <span aria-hidden className="mt-1 flex h-2.5 overflow-hidden rounded-sm bg-surface-muted">
              <span className="bg-brand" style={{ width: share(s.reached) }} />
              <span className="bg-warn" style={{ width: share(s.not_reached) }} />
              <span className="bg-line" style={{ width: share(s.unclear) }} />
            </span>
          </li>
        );
      })}
    </ol>
    </>
  );
}

function Swatch({ className, children }: { className: string; children: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-sm ${className}`} />
      {children}
    </span>
  );
}
