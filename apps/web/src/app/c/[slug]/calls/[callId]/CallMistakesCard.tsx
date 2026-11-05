"use client";

import { Section, TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import { CALL_MISTAKE_TOLD, type CallMistake } from "@/lib/api/callMistakes";

/**
 * "What went wrong on this call" (D-949): the mistakes the agent made on this call, each a
 * rule we fix, so every row says our team has been told and none asks the owner to act. A row
 * whose transcript line is on screen jumps to it. Hidden when empty (the screen decides).
 */
export function CallMistakesCard({
  mistakes,
  turnsOnScreen,
}: {
  mistakes: readonly CallMistake[];
  /** The transcript turns being shown, by `idx`: a row can only jump to one of these. */
  turnsOnScreen: ReadonlySet<number>;
}) {
  return (
    <Section title="What went wrong on this call">
      <ul className="mt-1 divide-y divide-line" aria-label="What went wrong on this call">
        {mistakes.map((mistake) => (
          <li key={`${mistake.kind}-${mistake.turn_idx}`} className="py-2.5 first:pt-0">
            <p className="text-body text-ink [overflow-wrap:anywhere]">{mistake.label}</p>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3">
              <StatusPill tone="neutral">{CALL_MISTAKE_TOLD}</StatusPill>
              {turnsOnScreen.has(mistake.turn_idx) ? (
                <button
                  type="button"
                  className={`${TEXT_ACTION_SM} -mx-2`}
                  aria-label={`Show where it happened: ${mistake.label}`}
                  onClick={() => jumpToTurn(mistake.turn_idx)}
                >
                  Show where
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

/**
 * Brings the transcript line into view and moves focus to it, so a keyboard or screen
 * reader user lands where a sighted one looks. `data-turn` is `TranscriptCard`'s own
 * anchor (its follow-along uses it); a line that is not rendered is left alone.
 */
function jumpToTurn(idx: number) {
  const line = document.querySelector<HTMLElement>(`[data-turn="${idx}"]`);
  if (!line) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  line.scrollIntoView?.({ block: "center", behavior: reduce ? "auto" : "smooth" });
  line.focus({ preventScroll: true });
}
