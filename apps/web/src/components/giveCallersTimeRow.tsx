"use client";

/**
 * "GIVE CALLERS TIME" (D-907): one row on an agent's call handling that sets it up, in one tap,
 * for a caller who follows along on their own phone and goes quiet for long stretches while
 * they do what the agent asked. The server sets the values (`POST .../call-handling/
 * give-callers-time`); this row only shows what they are and whether they are in force, so the
 * values have one spelling. Afterwards each is an ordinary setting in the rows below.
 *
 * "In use" is the server's `applied`: the silence settings match and the longest call is at
 * least the preset's. Any change made after reads as off, and the button offers the preset
 * again. When the agent's own judgement suggests it (`lib/api/callerHelp.ts`), the hint says
 * so and why, in place of the general one.
 */

import { type FeedbackStatus } from "@/components/arc/feedback";
import { SettingRow } from "@/components/console/settingRow";
import { ProblemNotice, SECONDARY_BUTTON_SM } from "@/components/ui";
import { formatSeconds, type GiveCallersTime } from "@/lib/api/callHandling";

/** What the preset does, in the words of the rows it changes. */
export function giveCallersTimeSteps(preset: GiveCallersTime): string[] {
  const ask = preset.nudge_phrase ? `"${preset.nudge_phrase}"` : "whether they are still there";
  return [
    `Asks ${ask} after ${formatSeconds(preset.nudge_after_seconds)} of quiet, up to ${preset.nudge_count} times.`,
    `Hangs up only after ${formatSeconds(preset.end_after_silence_seconds)} of silence.`,
    "Does not repeat an unanswered question while they are busy.",
    `Lets a call run for at least ${formatSeconds(preset.call_cap_s)}.`,
  ];
}

export function GiveCallersTimeRow({
  preset,
  canChange,
  status,
  error,
  onApply,
  suggested = null,
}: {
  preset: GiveCallersTime;
  canChange: boolean;
  /** The apply's state, from the caller's `useActionFeedback`. */
  status: FeedbackStatus;
  error: Error | null;
  onApply: () => void;
  /** "Suggested for <agent>: <why>", from the agent's own judgement; null when it is not. */
  suggested?: string | null;
}) {
  const pending = status === "pending";
  return (
    <div>
      <SettingRow
        label="Give callers time"
        hint={
          suggested && !preset.applied
            ? suggested
            : "Waits while callers do something on their phone."
        }
        info={
          <>
            <ul className="list-disc space-y-1 pl-4">
              {giveCallersTimeSteps(preset).map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
            <p className="mt-2">
              Change any of these in the rows below. Callers following on a screen? Turn that
              setting on too.
            </p>
          </>
        }
        value={preset.applied ? "In use" : undefined}
        control={
          preset.applied || !canChange ? undefined : (
            <button
              type="button"
              onClick={onApply}
              disabled={pending}
              aria-busy={pending || undefined}
              className={SECONDARY_BUTTON_SM}
            >
              {pending ? "Turning on" : "Turn on"}
            </button>
          )
        }
      />
      {!preset.applied && !canChange && (
        <p className="pb-3 text-meta text-ink-muted">Off for this agent.</p>
      )}
      {error && <ProblemNotice error={error} />}
    </div>
  );
}
