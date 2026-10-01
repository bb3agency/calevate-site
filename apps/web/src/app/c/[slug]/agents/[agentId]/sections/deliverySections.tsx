"use client";

/**
 * VOICE and CALL HANDLING — the two sections built on `GET /v1/agents/{id}/pending`.
 *
 * Each reads the same cached query; a failed read is one refusal per section, never a zero
 * and never an empty picker.
 */

import { ProblemNotice, Skeleton } from "@/components/ui";
import { SettingRows } from "@/components/console/settingRow";
import type { Agent } from "@/lib/api/agents";
import { usePendingChanges } from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";

import { CallerContinuity } from "../../panels/callerContinuity";
import { CallCapChoice, VoiceChoice } from "../../panels/delivery";
import { Handover } from "../../panels/handover";
import { VoiceNow, WorstCaseCost } from "../../panels/publishing";

function usePending(agentId: string) {
  const session = useClientSession();
  return usePendingChanges(session, agentId);
}

export function VoiceSection({ agent }: { agent: Agent }) {
  const pending = usePending(agent.id);
  if (pending.isLoading) return <Skeleton rows={4} />;
  if (pending.error || !pending.data) {
    return (
      <ProblemNotice
        error={pending.error ?? new Error("This agent's voice could not be read just now.")}
        onRetry={() => void pending.refetch()}
      />
    );
  }
  return (
    <div className="space-y-6">
      <SettingRows className="border-y border-line">
        <VoiceNow state={pending.data} published={agent.published} />
      </SettingRows>
      <VoiceChoice agentId={agent.id} state={pending.data} />
    </div>
  );
}

export function CallHandlingSection({ agent }: { agent: Agent }) {
  const pending = usePending(agent.id);
  return (
    <div className="space-y-8">
      {pending.isLoading ? (
        <Skeleton rows={2} />
      ) : pending.error || !pending.data ? (
        <ProblemNotice
          error={pending.error ?? new Error("This agent's call limit could not be read just now.")}
          onRetry={() => void pending.refetch()}
        />
      ) : (
        <SettingRows className="border-y border-line">
          <CallCapChoice agentId={agent.id} state={pending.data} />
          <WorstCaseCost state={pending.data} />
        </SettingRows>
      )}
      <Handover agent={agent} />
      <CallerContinuity agent={agent} />
    </div>
  );
}
