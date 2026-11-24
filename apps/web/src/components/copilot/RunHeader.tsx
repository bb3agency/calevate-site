"use client";

import { forwardRef } from "react";

import { ActionButton } from "@/components/arc/feedback";
import { PipMark } from "@/components/illustration/pip";
import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";
import { formatWorkTime } from "@/lib/copilot/liveEvents";

export type RunHeaderState = "working" | "stopping" | "waiting";

function headline(state: RunHeaderState): string {
  switch (state) {
    case "working":
      return "Working";
    case "stopping":
      return "Stopping";
    case "waiting":
      return "Waiting for you";
  }
}

/** Said once per state for a screen reader; the seconds are not, they change every second. */
function spoken(state: RunHeaderState): string {
  switch (state) {
    case "working":
      return `${ASSISTANT_NAME} is working.`;
    case "stopping":
      return `Stopping ${ASSISTANT_NAME}.`;
    case "waiting":
      return `${ASSISTANT_NAME} is waiting for you to decide.`;
  }
}

/**
 * The top of Pip's thread while it works: what it is doing, for how long, and Stop.
 *
 * Stop stays pressed (ActionButton's spinner) from the click until the server's `stopped`
 * frame ends the run, because the server is what stops: closing the connection alone would
 * leave the model and any draft running. When the run waits on a decision the header says
 * so and focus can be moved here (`tabIndex={-1}`), so a keyboard user lands on the choice.
 */
export const RunHeader = forwardRef<HTMLHeadingElement, {
  state: RunHeaderState;
  /** Epoch ms the counter starts from: the run's start, or when the wait began. */
  since: number;
  now: number;
  reduced: boolean;
  onStop?: () => void;
}>(function RunHeader({ state, since, now, reduced, onStop }, ref) {
  return (
    <div className="flex min-h-9 items-center gap-2" data-testid="run-header">
      <PipMark size={20} thinking={state === "working" && !reduced} className="shrink-0" />
      <h3 ref={ref} tabIndex={-1} className="min-w-0 text-meta font-medium text-ink focus:outline-none">
        {headline(state)}{" "}
        <span aria-hidden className="font-normal tabular-nums text-ink-faint">
          {formatWorkTime(now - since)}
        </span>
      </h3>
      <span role="status" className="sr-only">
        {spoken(state)}
      </span>
      {state !== "waiting" && onStop ? (
        <ActionButton
          variant="secondary-sm"
          className="ml-auto"
          status={state === "stopping" ? "pending" : "idle"}
          pendingLabel="Stopping"
          onClick={onStop}
        >
          Stop
        </ActionButton>
      ) : null}
    </div>
  );
});
