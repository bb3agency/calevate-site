"use client";

/**
 * One agent's call settings in Call handling: the pause before replying and the hang-up
 * (D-751), and what it does when the caller goes quiet, its lines while it looks something up
 * and a background sound (F3, F9).
 *
 * The owner changes them (`org:manage`: switching the hang-up off is a decision about the
 * account's money); anyone else who can open the agent reads the value in force and where it
 * comes from. A failed read is a refusal, never a default shown as if it were the agent's.
 */

import { useActionFeedback } from "@/components/arc/feedback";
import { HangUpRow, PauseRow } from "@/components/callHandlingRows";
import { AgentVoiceRows } from "@/components/callHandlingVoiceRows";
import { SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  inheritLabels,
  useAgentCallHandling,
  useSetAgentCallHandling,
} from "@/lib/api/callHandling";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

export function AgentCallHandlingRows({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const state = useAgentCallHandling(session, agentId);
  const save = useSetAgentCallHandling(session, agentId);
  // The row that saved shows pending and the error face on its save bar, with the refusal
  // beside it; the bar closes on success, so the success is a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Call settings saved" });
  const write = useWriteAccess(session, "org:manage", "change how this agent ends its turn and its calls");

  if (state.isLoading) return <Skeleton rows={2} />;
  if (state.error || !state.data) {
    return (
      <ProblemNotice
        error={state.error ?? new Error("This agent's call settings could not be read just now.")}
        onRetry={() => void state.refetch()}
      />
    );
  }
  const data = state.data;
  const labels = inheritLabels(data);
  return (
    <div className="space-y-2">
      <RestrictionNote reason={write.allowed ? null : write.reason} />
      <SettingRows className="border-y border-line">
        <PauseRow
          idPrefix={`agent-${agentId}`}
          effective={data.turn_silence_ms_effective}
          source={data.turn_silence_source}
          own={data.turn_silence_ms}
          inheritLabel={labels.pause}
          minMs={data.bounds.turn_silence_min_ms}
          maxMs={data.bounds.turn_silence_max_ms}
          canChange={write.allowed}
          status={save.variables?.turn_silence_ms !== undefined ? feedback.status : "idle"}
          error={save.variables?.turn_silence_ms !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ turn_silence_ms: next }, { onSuccess: done })}
        />
        <HangUpRow
          idPrefix={`agent-${agentId}`}
          effective={data.end_call_on_finish_effective}
          source={data.end_call_on_finish_source}
          own={data.end_call_on_finish}
          inheritLabel={labels.hangUp}
          canChange={write.allowed}
          status={save.variables?.end_call_on_finish !== undefined ? feedback.status : "idle"}
          error={save.variables?.end_call_on_finish !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ end_call_on_finish: next }, { onSuccess: done })}
        />
        <AgentVoiceRows
          idPrefix={`agent-${agentId}`}
          data={data}
          canChange={write.allowed}
          save={save}
          status={feedback.status}
        />
      </SettingRows>
    </div>
  );
}
