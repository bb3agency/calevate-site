"use client";

import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import type { TimelineEntry } from "@/lib/copilot/liveEvents";
import type { CopilotStep } from "@/lib/copilot/types";

import { labelOf } from "./StepList";
import { StepRow } from "./StepRow";
import { ThoughtRow } from "./ThoughtRow";
import { TimelineList } from "./TimelineRow";

/**
 * The run as it happens: each model turn's thinking and each tool call, in the order they
 * came, on one thread. Once the answer is in, `StepList` folds the calls into its one-line
 * receipt and only the thinking stays here, folded ("Thought for 3s").
 *
 * Not `aria-live`: these rows change several times a second, and the answer, which is
 * announced, is what a screen-reader user is waiting for.
 */
export function RunTimeline({
  entries,
  steps,
  now,
  live,
  reduced,
  realm = "client",
}: {
  entries: readonly TimelineEntry[];
  steps: readonly CopilotStep[];
  now: number;
  /** The run is still going; false draws the settled thinking only. */
  live: boolean;
  reduced: boolean;
  realm?: "client" | "admin";
}) {
  const byId = new Map(steps.map((step) => [step.id, step]));
  const shown = live ? entries : entries.filter((entry) => entry.kind === "thought");
  if (shown.length === 0) return null;
  const last = shown[shown.length - 1];
  return (
    <TimelineList label={live ? `What ${ASSISTANT_NAME} is doing` : `What ${ASSISTANT_NAME} thought`}>
      {shown.map((entry) => {
        if (entry.kind === "thought") {
          return (
            <ThoughtRow
              key={entry.id}
              thought={entry}
              live={live && entry === last && entry.endedAt === null}
              reduced={reduced}
              arrived={live && !reduced}
            />
          );
        }
        const step = byId.get(entry.id);
        if (step === undefined) return null;
        return (
          <StepRow
            key={entry.id}
            step={step}
            label={labelOf(step)}
            startedAt={entry.startedAt}
            now={now}
            live
            arrived={!reduced}
            title={realm === "admin" ? step.tool : undefined}
          />
        );
      })}
    </TimelineList>
  );
}
