"use client";

/**
 * OPENINGS THAT LOSE PEOPLE (founder, 24 Nov 2026): the share of answered calls that hung up
 * within the first seconds, beside the account's other campaigns (or other lines), and one
 * press that asks Pip to rewrite the opening. The AI and recording notices are never the
 * thing to cut (hard rule 5): the rewrite keeps them, and this card never offers otherwise.
 */

import { formatCount } from "@/components/ui";
import { openingFixInstruction } from "@/lib/api/improve";

import { AskPipFix } from "./AskPipFix";
import { ImproveCard, WithDiagnosis, type ImproveCardProps } from "./ImproveCard";

export const OPENING_TITLE = "Openings that lose people";

/** How much worse than the others before the rewrite is the first thing offered. */
const WORSE_BY = 0.05;

function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

export function OpeningLossCard({ holder, canWrite, refusal }: ImproveCardProps) {
  const others = holder.kind === "campaign" ? "your other campaigns" : "your other lines";
  return (
    <ImproveCard
      title={OPENING_TITLE}
      hint="People who hang up while the opening is said."
      info="The AI and recording notices stay in the opening. Pip rewrites the rest of it."
    >
      <WithDiagnosis holder={holder} label="Reading how many hang up early">
        {({ early_hang_ups: e }) => {
          if (e.answered === 0) {
            return <p className="text-meta text-ink-muted">No answered calls yet.</p>;
          }
          if (e.rate === null) {
            return (
              <p className="text-meta text-ink-muted">
                Too few calls to say yet: {formatCount(e.answered)} of {formatCount(e.min_answered)}{" "}
                answered.
              </p>
            );
          }
          const worse = e.others_rate !== null && e.rate - e.others_rate >= WORSE_BY;
          return (
            <>
              <p className="text-body text-ink">
                <span className="text-title font-semibold tabular-nums">{percent(e.rate)}</span>{" "}
                hung up in the first {e.early_seconds} seconds.
              </p>
              <p className="mt-1 text-meta text-ink-muted">
                {formatCount(e.early)} of {formatCount(e.answered)} answered calls.{" "}
                {e.others_rate === null
                  ? `Not enough calls on ${others} to compare.`
                  : `${others[0].toUpperCase()}${others.slice(1)}: ${percent(e.others_rate)}.`}
              </p>
              {worse && (
                <p className="mt-2 text-meta text-warn">More than on {others}.</p>
              )}
              {e.early > 0 && (
                <div className="mt-3">
                  <AskPipFix
                    holder={holder}
                    instruction={openingFixInstruction(holder)}
                    label="Rewrite the opening"
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
