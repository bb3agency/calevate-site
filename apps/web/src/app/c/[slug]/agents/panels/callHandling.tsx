"use client";

/**
 * One agent's call settings on its Settings: the pause before replying and the hang-up
 * (D-751), whether its first words wait for the person's hello (D-871), and what it does when
 * the caller goes quiet, its lines while it looks something up and a background sound (F3,
 * F9).
 *
 * This is the only place a client changes them (founder, 27 Oct 2026). Each row's editor asks
 * whom the change is for: "Just this agent" saves the agent's own value, "All my agents" makes
 * it the value every agent shares and drops each agent's own. The account read tells the
 * second choice how many agents with their own value it changes. Waiting for hello has no
 * shared value, so it stays per agent; how long it waits (D-901) inherits like the pause, and
 * shows only while waiting is on and the platform offers it. How soon an unanswered question
 * is asked again (D-907) inherits the same way. "Give callers time" sets the silence rows and
 * the longest call for a caller following along on their phone in one tap (D-907).
 *
 * The owner changes them (`org:manage`: switching the hang-up off is a decision about the
 * account's money); anyone else who can open the agent reads the value in force and where it
 * comes from. A failed read is a refusal, never a default shown as if it were the agent's.
 */

import { useState } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import {
  HangUpRow,
  OpeningWaitRow,
  OpeningWaitsRow,
  PauseRow,
  ReaskRow,
  type ScopeOffer,
} from "@/components/callHandlingRows";
import { AgentVoiceRows } from "@/components/callHandlingVoiceRows";
import { PatientCallerRow } from "@/components/patientCallerRow";
import { SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import {
  inheritLabels,
  openingWaitMs,
  othersWithOwn,
  platformLabels,
  useAgentCallHandling,
  useApplyPatientCaller,
  useOrganizationCallHandling,
  useSaveCallHandling,
  type AgentCallHandlingIn,
  type CallHandlingScope,
  type DefaultsRow,
} from "@/lib/api/callHandling";
import { useWriteAccess } from "@/lib/api/hooks";
import { useClientSession } from "@/lib/api/session";

/** Which row the last save came from, so its busy state and refusal show on that row. */
type Row = DefaultsRow | "opening";

export function AgentCallHandlingRows({ agentId }: { agentId: string }) {
  const session = useClientSession();
  const state = useAgentCallHandling(session, agentId);
  const write = useWriteAccess(session, "org:manage", "change how this agent ends its turn and its calls");
  // Read only for a reader who may save for every agent: it counts the agents that change.
  const account = useOrganizationCallHandling(session, { enabled: write.allowed });
  const save = useSaveCallHandling(session, agentId);
  // The bar closes on success, so the success is a toast, worded for whom it changed.
  const feedback = useActionFeedback(save, {
    errorDisplay: "inline",
    successToast: (_data, variables) =>
      variables.scope === "all" ? "Saved for all your agents" : "Saved for this agent",
  });
  const [row, setRow] = useState<Row | null>(null);
  const patient = useApplyPatientCaller(session, agentId);
  const patientFeedback = useActionFeedback(patient, {
    errorDisplay: "inline",
    successToast: "This agent now gives callers time",
  });

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
  const calevate = platformLabels(data.bounds);
  // Without the account read there is no count to state, so "All my agents" waits for it
  // rather than offering a change whose reach it cannot say.
  const others = write.allowed && account.data ? othersWithOwn(account.data, agentId) : null;
  const offer = (which: DefaultsRow, inherit: string): ScopeOffer<string> | undefined =>
    others ? { others: others[which], inherit } : undefined;

  const send = (which: Row, changes: AgentCallHandlingIn, done: () => void, scope: CallHandlingScope) => {
    setRow(which);
    save.mutate({ scope, changes }, { onSuccess: done });
  };
  const rowStatus = (which: Row) => (row === which ? feedback.status : "idle");
  const failed = (which: Row) => (row === which ? save.error : null);

  return (
    <div className="space-y-2">
      <RestrictionNote reason={write.allowed ? null : write.reason} />
      <SettingRows className="border-y border-line">
        <PatientCallerRow
          preset={data.patient_caller}
          canChange={write.allowed}
          status={patientFeedback.status}
          error={patient.error}
          onApply={() => patient.mutate()}
        />
        <PauseRow
          idPrefix={`agent-${agentId}`}
          effective={data.turn_silence_ms_effective}
          source={data.turn_silence_source}
          own={data.turn_silence_ms}
          inheritLabel={labels.pause}
          minMs={data.bounds.turn_silence_min_ms}
          maxMs={data.bounds.turn_silence_max_ms}
          notUsed={!data.turn_silence_applies}
          canChange={write.allowed && data.turn_silence_applies}
          status={rowStatus("pause")}
          error={failed("pause")}
          scope={offer("pause", calevate.pause)}
          onSave={(next, done, scope) => send("pause", { turn_silence_ms: next }, done, scope)}
        />
        <HangUpRow
          idPrefix={`agent-${agentId}`}
          effective={data.end_call_on_finish_effective}
          source={data.end_call_on_finish_source}
          own={data.end_call_on_finish}
          inheritLabel={labels.hangUp}
          canChange={write.allowed}
          status={rowStatus("hang-up")}
          error={failed("hang-up")}
          scope={offer("hang-up", calevate.hangUp)}
          onSave={(next, done, scope) => send("hang-up", { end_call_on_finish: next }, done, scope)}
        />
        <OpeningWaitsRow
          on={data.opening_waits_for_caller}
          waitMs={openingWaitMs(data)}
          canChange={write.allowed}
          status={rowStatus("opening")}
          error={failed("opening")}
          onSave={(next, done) => send("opening", { opening_waits_for_caller: next }, done, "agent")}
        />
        {data.opening_waits_for_caller && data.bounds.opening_wait_available && (
          <OpeningWaitRow
            idPrefix={`agent-${agentId}`}
            effective={openingWaitMs(data)}
            source={data.opening_wait_ms_source}
            own={data.opening_wait_ms}
            inheritLabel={labels.openingWait}
            minMs={data.bounds.opening_wait_min_ms}
            maxMs={data.bounds.opening_wait_max_ms}
            stepMs={data.bounds.opening_wait_step_ms}
            canChange={write.allowed}
            status={rowStatus("opening-wait")}
            error={failed("opening-wait")}
            scope={offer("opening-wait", calevate.openingWait)}
            onSave={(next, done, scope) => send("opening-wait", { opening_wait_ms: next }, done, scope)}
          />
        )}
        <AgentVoiceRows
          idPrefix={`agent-${agentId}`}
          data={data}
          canChange={write.allowed}
          status={
            row === "silence" || row === "filler" || row === "sound" ? feedback.status : "idle"
          }
          error={row === "silence" || row === "filler" || row === "sound" ? save.error : null}
          others={others ?? undefined}
          onSave={(changes, done, scope) => {
            // The voice rows track which of them saved; this records that one of them did.
            setRow(voiceRow(changes));
            save.mutate({ scope, changes }, { onSuccess: done });
          }}
        />
        <ReaskRow
          idPrefix={`agent-${agentId}`}
          effective={data.reask_after_ms_effective}
          source={data.reask_after_ms_source}
          own={data.reask_after_ms}
          inheritLabel={labels.reask}
          minMs={data.bounds.reask_after_min_ms}
          maxMs={data.bounds.reask_after_max_ms}
          stepMs={data.bounds.reask_after_step_ms}
          seedMs={data.bounds.platform_reask_after_ms}
          canChange={write.allowed}
          status={rowStatus("reask")}
          error={failed("reask")}
          scope={offer("reask", calevate.reask)}
          onSave={(next, done, scope) => send("reask", { reask_after_ms: next }, done, scope)}
        />
      </SettingRows>
    </div>
  );
}

/** The voice row a save came from, by the fields it names. */
function voiceRow(changes: AgentCallHandlingIn): Row {
  if ("filler_lines" in changes) return "filler";
  if ("ambience" in changes || "ambience_volume_pct" in changes) return "sound";
  return "silence";
}
