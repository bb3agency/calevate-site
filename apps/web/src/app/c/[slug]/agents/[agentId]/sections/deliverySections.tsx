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
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

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
  useCopilotSurface({
    route: "/c/{slug}/agents/{id}",
    title: "Agent: call handling",
    realm: "client",
    fields: [],
    facts: [
      { key: "agent_id", label: "Agent id", value: agent.id },
      {
        key: "call_cap_s",
        label: "Longest one call may run (seconds)",
        value: pending.data ? String(pending.data.effective_call_cap_s) : pending.error ? "could not be read" : "still loading",
      },
      {
        key: "worst_case_call_cost_inr",
        label: "Most one call can cost (INR)",
        value: pending.data ? (pending.data.worst_case_call_cost_inr ?? "no limit set") : "not loaded",
      },
      { key: "caller_memory", label: "Remembers callers between calls", value: agent.caller_memory_enabled ? "yes" : "no" },
    ],
    apply: noFill,
  });
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
