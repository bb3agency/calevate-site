"use client";

/**
 * An operator's turn detection for one agent (D-901): Silence, Ear or Smart for this agent
 * alone, or the console's mode that every agent follows. For trying a mode on one agent
 * without moving every client; never on a client's screen.
 */

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { CALL_HANDLING_EDITOR, CALL_HANDLING_NEXT_CALL } from "@/components/callHandlingRows";
import { SaveBar } from "@/components/console/saveBar";
import { TEXT_ACTION } from "@/components/console/section";
import { SettingRow } from "@/components/console/settingRow";
import { SegmentedControl } from "@/components/interior/segmented-control";
import { ProblemNotice, Skeleton } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  formatPause,
  sourceLabel,
  useAdminAgentTurnDetection,
  useAdminSetAgentTurnDetection,
  type AgentTurnDetection,
  type TurnDetection,
} from "@/lib/api/callHandling";

/** The console's own words for each mode (`config_catalog` `thinnest_turn_detection`). */
export const TURN_DETECTION_LABELS: Record<TurnDetection, string> = {
  timer: "Silence",
  ear: "Ear",
  smart: "Smart",
};

/** The pause this agent's calls use beside the mode, and whose it is. */
function pauseInForce(data: AgentTurnDetection): string {
  if (!data.turn_silence_applies) return "pause not used";
  return `pause ${formatPause(data.turn_silence_ms_effective)}, ${sourceLabel(data.turn_silence_source).toLowerCase()}`;
}

const FOLLOW = "console";
type Choice = TurnDetection | typeof FOLLOW;

const INFO =
  "Silence ends the caller's turn after the pause above, counted from their last words. Ear " +
  "listens live and waits through a pause mid-sentence; it does not use the pause. Smart lets " +
  "a model judge, and replies start later. Set one here to try it on this agent alone; every " +
  "other agent keeps the console's mode. Put on Silence here with no pause of its own, the " +
  "agent starts from the console's pause for that trial.";

export function TurnDetectionRow({
  tenantId,
  agentId,
  write,
}: {
  tenantId: string;
  agentId: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const state = useAdminAgentTurnDetection(tenantId, agentId);
  const save = useAdminSetAgentTurnDetection(tenantId, agentId);
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Turn detection saved" });
  const [editing, setEditing] = useState(false);
  const [choice, setChoice] = useState<Choice>(FOLLOW);

  if (state.isLoading) return <Skeleton rows={1} />;
  if (state.error || !state.data) {
    return (
      <ProblemNotice
        error={state.error ?? new Error("This agent's turn detection could not be read just now.")}
        onRetry={() => void state.refetch()}
      />
    );
  }
  const data = state.data;
  const saved: Choice = data.turn_detection ?? FOLLOW;
  const changed = editing && choice !== saved;
  const consoleMode = TURN_DETECTION_LABELS[data.console_turn_detection];
  const close = () => {
    setEditing(false);
    setChoice(saved);
  };

  return (
    <div>
      <SettingRow
        label="How this agent knows the caller has finished"
        hint={
          data.turn_detection === null
            ? "Follows the console"
            : `This agent only; the console is on ${consoleMode}`
        }
        info={<p>{INFO}</p>}
        value={`${TURN_DETECTION_LABELS[data.turn_detection_effective]} · ${pauseInForce(data)}`}
        action={
          editing || !write.allowed ? undefined : (
            <button
              type="button"
              onClick={() => {
                setChoice(saved);
                setEditing(true);
              }}
              className={TEXT_ACTION}
            >
              Change
            </button>
          )
        }
      />
      {save.error && <ProblemNotice error={save.error} />}
      {editing && (
        <form
          className="settings-enter space-y-3 pb-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(choice === FOLLOW ? null : choice, { onSuccess: () => setEditing(false) });
          }}
        >
          <div className={CALL_HANDLING_EDITOR}>
            <SegmentedControl
              label="Turn detection"
              options={[
                { value: FOLLOW, label: "Console" },
                ...(Object.keys(TURN_DETECTION_LABELS) as TurnDetection[]).map((mode) => ({
                  value: mode,
                  label: TURN_DETECTION_LABELS[mode],
                })),
              ]}
              value={choice}
              onValueChange={(value) => setChoice(value as Choice)}
            />
          </div>
          {(changed || save.isPending) && (
            <SaveBar label="Save" status={feedback.status} onCancel={close} note={CALL_HANDLING_NEXT_CALL} />
          )}
          {!changed && !save.isPending && (
            <button type="button" onClick={close} className={TEXT_ACTION}>
              Close
            </button>
          )}
        </form>
      )}
    </div>
  );
}
