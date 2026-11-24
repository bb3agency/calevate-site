"use client";

import { Section, TEXT_ACTION_SM } from "@/components/console/section";
import { StatusPill } from "@/components/console/statusPill";
import type { NoticeTone } from "@/components/ui";
import type { components } from "@/lib/api/schema";

import { jumpToTurn } from "./CallMistakesCard";

export type CallStep = components["schemas"]["CallProgressStepOut"];

export const STEPS_TITLE = "Where the call got to";

export const STEP_STATE: Record<CallStep["state"], { word: string; tone: NoticeTone }> = {
  reached: { word: "Done", tone: "ok" },
  not_reached: { word: "Not done", tone: "warn" },
  unclear: { word: "Not clear", tone: "neutral" },
};

/**
 * Each step of the call's script and whether the person's own words showed its outcome
 * (founder, 24 Nov 2026), by the step's names. A done step whose line is on screen jumps to
 * it. Hidden when the call was never judged (the screen decides).
 */
export function CallStepsCard({
  steps,
  turnsOnScreen,
}: {
  steps: readonly CallStep[];
  turnsOnScreen: ReadonlySet<number>;
}) {
  return (
    <Section title={STEPS_TITLE}>
      <ol className="mt-1 divide-y divide-line" aria-label={STEPS_TITLE}>
        {steps.map((step) => {
          const shown = STEP_STATE[step.state];
          return (
            <li key={step.step} className="flex flex-wrap items-center gap-x-3 py-2 first:pt-0">
              <span className="min-w-0 flex-1 text-body text-ink [overflow-wrap:anywhere]">
                <span className="text-ink-muted">{step.step}.</span> {step.name}
              </span>
              <StatusPill tone={shown.tone}>{shown.word}</StatusPill>
              {step.turn_idx !== null && turnsOnScreen.has(step.turn_idx) ? (
                <button
                  type="button"
                  className={`${TEXT_ACTION_SM} -mx-2`}
                  aria-label={`Show where: ${step.name}`}
                  onClick={() => jumpToTurn(step.turn_idx as number)}
                >
                  Show where
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
    </Section>
  );
}
