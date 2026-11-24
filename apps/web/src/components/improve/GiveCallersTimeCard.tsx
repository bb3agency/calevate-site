"use client";

/**
 * GIVE CALLERS TIME on a campaign or Inbound line (founder, 25 Nov 2026). When the script asks
 * the caller to do things on their phone, a quiet caller is given time instead of being hung
 * up on after about half a minute. It switches on by itself for such a script; the owner can
 * turn it off or on, and that choice is kept (`agents/give_callers_time`).
 */

import { useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice, Skeleton, ToggleSwitch } from "@/components/ui";
import { useHolderGiveTime, useSetHolderGiveTime, type HolderGiveTime } from "@/lib/api/improve";
import { useClientRealm } from "@/lib/api/session";

import { ImproveCard, MoveError, type ImproveCardProps } from "./ImproveCard";

function minutesWords(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return minutes === 1 ? "1 minute" : `${minutes} minutes`;
}

function stateWords(data: HolderGiveTime): string {
  if (data.owner_choice === null) {
    return data.script_asks
      ? "On, because the script asks callers to do things on their phone."
      : "Off. The script does not ask callers to do things on their phone.";
  }
  return data.on ? "On. You turned it on." : "Off. You turned it off.";
}

export function GiveCallersTimeCard({ holder, canWrite, refusal }: ImproveCardProps) {
  const { session } = useClientRealm();
  const read = useHolderGiveTime(session, holder);
  const save = useSetHolderGiveTime(session, holder);
  useActionFeedback(save, {
    errorDisplay: "inline",
    successToast: (_, on) => (on ? "Quiet callers get time" : "Quiet callers are not given extra time"),
  });
  const data = read.data;
  return (
    <ImproveCard
      title="Give callers time"
      hint="A caller busy on their phone is not hung up on."
      info={
        data && (
          <p>
            A quiet caller is asked if they are still there after {data.nudge_after_seconds} seconds,
            up to {data.nudge_count} times. The call ends after{" "}
            {minutesWords(data.end_after_silence_seconds)} of silence, and can run up to{" "}
            {minutesWords(data.call_cap_s)}. Settings you chose on the agent are kept.
          </p>
        )
      }
    >
      {read.isLoading ? (
        <Skeleton rows={1} label="Reading whether callers get time" />
      ) : !data ? (
        <ProblemNotice error={read.error} onRetry={() => read.refetch()} />
      ) : (
        <>
          <ToggleSwitch
            label="Give quiet callers time"
            hint={stateWords(data)}
            checked={data.on}
            disabled={!canWrite || save.isPending}
            onChange={(on) => save.mutate(on)}
          />
          {!canWrite && refusal && <p className="mt-2 text-meta text-ink-muted">{refusal}</p>}
          <MoveError error={save.error} fallback="That did not save" />
        </>
      )}
    </ImproveCard>
  );
}
