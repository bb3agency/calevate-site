"use client";

/**
 * THE AGENT THE CALL STEPS SPEAK IN: the campaign's own, chosen in the Script tab's Agent
 * section (founder, 18 Nov 2026: no agent picker in the flow; prompt to choose one there).
 */

import type { ReactNode } from "react";

import { NoticeBox } from "@/components/ui";
import { useAgents } from "@/lib/api/agents";
import { useClientRealm } from "@/lib/api/session";

import type { FlowAgent } from "./LineCoach";
import { agentSectionId, useOpenCampaignSection } from "./campaignSections";

/** The campaign's agent as the flow uses it; null while the list is loading. */
export function useFlowAgent(agentId: string, missing: ReactNode): FlowAgent | null {
  const { session } = useClientRealm();
  const agents = useAgents(session);
  if (!agents.data) return null;
  const agent = agents.data.find((a) => a.id === agentId);
  return agent
    ? { id: agent.id, name: agent.name, voiceId: agent.engine_voice_id ?? null, missing }
    : { id: "", name: "", voiceId: null, missing };
}

/** Shown in the scenario editor while the campaign has no agent. */
export function ChooseAgentPrompt({ campaignId }: { campaignId: string }) {
  const openSection = useOpenCampaignSection();
  return (
    <NoticeBox
      tone="warn"
      action={
        <button
          type="button"
          className="font-medium text-brand-strong underline"
          onClick={() => openSection(agentSectionId(campaignId))}
        >
          Go to Agent
        </button>
      }
    >
      Choose this campaign&apos;s agent to hear each line in its voice.
    </NoticeBox>
  );
}
