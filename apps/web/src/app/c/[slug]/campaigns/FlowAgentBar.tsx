"use client";

/**
 * THE AGENT IN THE CALL FLOW: who speaks these scenarios, chosen here when the campaign has
 * none (or changed), and its voice's speed, loudness and emotion, which change the agent on
 * every call it makes (founder, 17 Nov 2026: small trainings that form the bigger picture).
 */

import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, UserRound } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useActionFeedback } from "@/components/arc/feedback";
import { ProblemNotice } from "@/components/ui";
import { isAssignable } from "@/lib/agentState";
import { useAgents, type Agent } from "@/lib/api/agents";
import { useUpdateCampaign } from "@/lib/api/campaigns";
import { workspaceKey } from "@/lib/api/campaignWorkspace";
import { useClientRealm } from "@/lib/api/session";

import { ClientVoiceTuning } from "../agents/panels/voiceTuning";
import type { FlowAgent } from "./LineCoach";

/** The campaign's agent as the flow uses it; null while there is none to speak. */
export function useFlowAgent(agentId: string, bar: (agent: Agent | null) => ReactNode): FlowAgent | null {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const agent = (agents.data ?? []).find((a) => a.id === agentId) ?? null;
  if (!agents.data) return null;
  return agent
    ? { id: agent.id, name: agent.name, voiceId: agent.engine_voice_id ?? null, bar: bar(agent) }
    : { id: "", name: "", voiceId: null, bar: bar(null) };
}

export function FlowAgentBar({
  campaignId,
  agentId,
  agent,
  canWrite,
  refusal,
}: {
  campaignId: string;
  agentId: string;
  agent: Agent | null;
  canWrite: boolean;
  refusal?: string;
}) {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  const update = useUpdateCampaign(session, campaignId);
  useActionFeedback(update, { errorDisplay: "inline", successToast: "Agent changed" });
  const client = useQueryClient();
  const [tuning, setTuning] = useState(false);
  const options = (agents.data ?? []).filter(isAssignable);

  return (
    <div className="mt-2 rounded-card border border-series-4/30 bg-series-4/5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <UserRound aria-hidden className="h-4 w-4 text-series-4" />
        <label className="flex items-center gap-1.5 text-meta font-medium text-ink">
          Agent
          <select
            className="rounded border border-line bg-surface px-1.5 py-0.5 text-meta"
            value={agent ? agentId : ""}
            disabled={!canWrite || update.isPending}
            title={refusal}
            onChange={(e) =>
              e.target.value &&
              update.mutate(
                { agent_id: e.target.value },
                { onSuccess: () => void client.invalidateQueries({ queryKey: workspaceKey(session.orgSlug, campaignId) }) },
              )
            }
          >
            {!agent && <option value="">Choose an agent</option>}
            {options.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {agent && (
          <button
            type="button"
            aria-expanded={tuning}
            className="ml-auto inline-flex items-center gap-1 text-meta text-brand-strong hover:underline"
            onClick={() => setTuning(!tuning)}
          >
            <ChevronDown aria-hidden className={`h-3.5 w-3.5 transition-transform ${tuning ? "" : "-rotate-90"}`} />
            Adjust {agent.name}&apos;s voice
          </button>
        )}
      </div>
      {!agent && <p className="mt-1 text-[12px] text-ink-muted">Choose the agent to hear each line in its voice.</p>}
      {update.error != null && <ProblemNotice error={update.error} />}
      {agent && tuning && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="mb-2 text-[12px] text-ink-muted">These change how {agent.name} sounds on every call, not only here.</p>
          <ClientVoiceTuning agentId={agent.id} voiceId={agent.engine_voice_id ?? null} />
        </div>
      )}
    </div>
  );
}
