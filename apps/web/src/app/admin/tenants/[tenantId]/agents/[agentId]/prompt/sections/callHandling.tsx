"use client";

/**
 * One client agent's pause before replying and hang-up (D-751), from the console: read as
 * the client sees it (view-as), changed through the operator's own door. The same rows as
 * the client's Call handling, so an operator on the phone with an owner sees their screen.
 */

import { HangUpRow, PauseRow } from "@/components/callHandlingRows";
import { SettingRows } from "@/components/console/settingRow";
import { ProblemNotice, RestrictionNote, Skeleton } from "@/components/ui";
import type { useAdminAccess } from "@/app/admin/access";
import {
  inheritLabels,
  useAdminSetAgentCallHandling,
  useTenantAgentCallHandling,
} from "@/lib/api/callHandling";

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
      <h3 className="text-heading text-ink">Pauses and hang-up</h3>
      <RestrictionNote reason={write.reason} />
      <SettingRows className="border-y border-line">
        <PauseRow
          idPrefix={`admin-${agentId}`}
          effective={data.turn_silence_ms_effective}
          source={data.turn_silence_source}
          own={data.turn_silence_ms}
          inheritLabel={labels.pause}
          minMs={data.bounds.turn_silence_min_ms}
          maxMs={data.bounds.turn_silence_max_ms}
          canChange={write.allowed}
          saving={save.isPending && save.variables?.turn_silence_ms !== undefined}
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
          saving={save.isPending && save.variables?.end_call_on_finish !== undefined}
          error={save.variables?.end_call_on_finish !== undefined ? save.error : null}
          onSave={(next, done) => save.mutate({ end_call_on_finish: next }, { onSuccess: done })}
        />
      </SettingRows>
    </div>
  );
}
