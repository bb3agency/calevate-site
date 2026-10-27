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
import { pauseLabel, sourceLabel, useAgentCallHandling } from "@/lib/api/callHandling";
import { usePendingChanges } from "@/lib/api/publishing";
import { useClientSession } from "@/lib/api/session";
import { useCopilotSurface } from "@/lib/copilot/registry";
import { noFill } from "@/lib/copilot/types";

import { AgentCallHandlingRows } from "../../panels/callHandling";
import { CallerContinuity } from "../../panels/callerContinuity";
import { CallCapChoice, VoiceChoice } from "../../panels/delivery";
import { Handover } from "../../panels/handover";
import { VoiceNow, WorstCaseCost } from "../../panels/publishing";
import { ClientVoiceTuning } from "../../panels/voiceTuning";

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
      {/* No top rule: this list opens the tab, directly under the tab bar's own line. */}
      <SettingRows className="border-b border-line">
        <VoiceNow state={pending.data} published={agent.published} />
      </SettingRows>
      <VoiceChoice agentId={agent.id} state={pending.data} />
      <ClientVoiceTuning agentId={agent.id} voiceId={agent.engine_voice_id ?? null} />
    </div>
  );
}

export function CallHandlingSection({ agent }: { agent: Agent }) {
  const pending = usePending(agent.id);
  const session = useClientSession();
  const handling = useAgentCallHandling(session, agent.id);
  const unread = handling.error ? "could not be read" : "still loading";
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
      {
        key: "pause_before_reply",
        label: "Pause before the agent replies",
        value: handling.data
          ? handling.data.turn_silence_applies
            ? `${pauseLabel(handling.data.turn_silence_ms_effective)}, ${sourceLabel(handling.data.turn_silence_source).toLowerCase()}`
            : "not used: the agent hears when the caller has finished"
          : unread,
      },
      {
        key: "hang_up_when_finished",
        label: "Hangs up when the conversation ends",
        value: handling.data
          ? `${handling.data.end_call_on_finish_effective ? "yes" : "no, the call stays connected and charged until the caller hangs up"}, ${sourceLabel(handling.data.end_call_on_finish_source).toLowerCase()}`
          : unread,
      },
      {
        key: "waits_for_hello",
        label: "Waits for the first words of the person who picks up before speaking",
        value: handling.data ? (handling.data.opening_waits_for_caller ? "yes" : "no") : unread,
      },
    ],
    apply: noFill,
  });
  return (
    <div className="space-y-8">
      {/* One list: the call-handling rows continue the call-limit rows, so the two share
          a single rule between them rather than each drawing its own edge. */}
      <div>
        {pending.isLoading ? (
          <Skeleton rows={2} />
        ) : pending.error || !pending.data ? (
          <ProblemNotice
            error={pending.error ?? new Error("This agent's call limit could not be read just now.")}
            onRetry={() => void pending.refetch()}
          />
        ) : (
          <SettingRows className="border-t border-line">
            <CallCapChoice agentId={agent.id} state={pending.data} />
            <WorstCaseCost state={pending.data} />
          </SettingRows>
        )}
        <AgentCallHandlingRows agentId={agent.id} />
      </div>
      <Handover agent={agent} />
      <CallerContinuity agent={agent} />
    </div>
  );
}
