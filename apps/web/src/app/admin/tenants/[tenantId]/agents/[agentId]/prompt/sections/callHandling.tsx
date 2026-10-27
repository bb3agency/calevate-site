"use client";

/**
 * One client agent's call settings (D-751, F3, F9), from the console: read as
 * the client sees it (view-as), changed through the operator's own door. The same rows as
 * the client's Call handling, so an operator on the phone with an owner sees their screen.
 */

import { useActionFeedback } from "@/components/arc/feedback";
import {
  HangUpRow,
  OpeningWaitRow,
  OpeningWaitsRow,
  PauseRow,
  ReaskRow,
} from "@/components/callHandlingRows";
import { AgentVoiceRows } from "@/components/callHandlingVoiceRows";
import { PatientCallerRow } from "@/components/patientCallerRow";
import { SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  inheritLabels,
  openingWaitMs,
  useAdminApplyPatientCaller,
  useAdminSetAgentCallHandling,
  useTenantAgentCallHandling,
} from "@/lib/api/callHandling";

import { TurnDetectionRow } from "./turnDetection";

export function CallHandlingPanel({
  tenantId,
  agentId,
  slug,
  write,
}: {
  tenantId: string;
  agentId: string;
  slug: string;
  write: ReturnType<typeof useAdminAccess>;
}) {
  const state = useTenantAgentCallHandling(slug, agentId);
  const save = useAdminSetAgentCallHandling({ tenantId, agentId, slug });
  // The row that saved shows pending and the error face on its save bar, with the refusal
  // beside it; the bar closes on success, so the success is a toast.
  const feedback = useActionFeedback(save, { errorDisplay: "inline", successToast: "Call settings saved" });
  const patient = useAdminApplyPatientCaller({ tenantId, agentId, slug });
  const patientFeedback = useActionFeedback(patient, {
    errorDisplay: "inline",
    successToast: "Patient caller set on this agent",
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
  return (
    <div className="mt-8 space-y-2">
      <h3 className="text-heading text-ink">Call handling</h3>
      <RestrictionNote reason={write.reason} />
      <SettingRows className="border-y border-line">
        <PatientCallerRow
          preset={data.patient_caller}
          canChange={write.allowed}
          status={patientFeedback.status}
          error={patient.error}
          onApply={() => patient.mutate()}
        />
        <PauseRow
          idPrefix={`admin-${agentId}`}
          effective={data.turn_silence_ms_effective}
          source={data.turn_silence_source}
          own={data.turn_silence_ms}
          inheritLabel={labels.pause}
          minMs={data.bounds.turn_silence_min_ms}
          maxMs={data.bounds.turn_silence_max_ms}
          notUsed={!data.turn_silence_applies}
          canChange={write.allowed}
          status={save.variables?.turn_silence_ms !== undefined ? feedback.status : "idle"}
          error={save.variables?.turn_silence_ms !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ turn_silence_ms: next }, { onSuccess: done })}
        />
        <HangUpRow
          idPrefix={`admin-${agentId}`}
          effective={data.end_call_on_finish_effective}
          source={data.end_call_on_finish_source}
          own={data.end_call_on_finish}
          inheritLabel={labels.hangUp}
          canChange={write.allowed}
          status={save.variables?.end_call_on_finish !== undefined ? feedback.status : "idle"}
          error={save.variables?.end_call_on_finish !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ end_call_on_finish: next }, { onSuccess: done })}
        />
        <OpeningWaitsRow
          on={data.opening_waits_for_caller}
          canChange={write.allowed}
          status={save.variables?.opening_waits_for_caller !== undefined ? feedback.status : "idle"}
          error={save.variables?.opening_waits_for_caller !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ opening_waits_for_caller: next }, { onSuccess: done })}
          waitMs={openingWaitMs(data)}
        />
        {data.opening_waits_for_caller && data.bounds.opening_wait_available && (
          <OpeningWaitRow
            idPrefix={`admin-${agentId}`}
            effective={openingWaitMs(data)}
            source={data.opening_wait_ms_source}
            own={data.opening_wait_ms}
            inheritLabel={labels.openingWait}
            minMs={data.bounds.opening_wait_min_ms}
            maxMs={data.bounds.opening_wait_max_ms}
            stepMs={data.bounds.opening_wait_step_ms}
            canChange={write.allowed}
            status={save.variables?.opening_wait_ms !== undefined ? feedback.status : "idle"}
            error={save.variables?.opening_wait_ms !== undefined ? save.error : null}
            onSave={(next, done) => save.mutate({ opening_wait_ms: next }, { onSuccess: done })}
          />
        )}
        <TurnDetectionRow tenantId={tenantId} agentId={agentId} write={write} />
        <AgentVoiceRows
          idPrefix={`admin-${agentId}`}
          data={data}
          canChange={write.allowed}
          onSave={(payload, done) => save.mutate(payload, { onSuccess: done })}
          error={save.error}
          status={feedback.status}
        />
        <ReaskRow
          idPrefix={`admin-${agentId}`}
          effective={data.reask_after_ms_effective}
          source={data.reask_after_ms_source}
          own={data.reask_after_ms}
          inheritLabel={labels.reask}
          minMs={data.bounds.reask_after_min_ms}
          maxMs={data.bounds.reask_after_max_ms}
          stepMs={data.bounds.reask_after_step_ms}
          seedMs={data.bounds.platform_reask_after_ms}
          canChange={write.allowed}
          status={save.variables?.reask_after_ms !== undefined ? feedback.status : "idle"}
          error={save.variables?.reask_after_ms !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ reask_after_ms: next }, { onSuccess: done })}
        />
      </SettingRows>
    </div>
  );
}
