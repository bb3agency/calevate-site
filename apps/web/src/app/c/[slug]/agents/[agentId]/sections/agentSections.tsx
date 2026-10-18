"use client";

/**
 * THE AGENT PAGE'S SEVEN TABS (D-825, founder 19 Oct 2026): Overview · Script · Training ·
 * Actions · What it notes · Voice · Settings.
 *
 * Ordered by what an owner comes to do: see how it is doing, change what it says, teach it,
 * then the rarer parts. Calls fold into Overview (its latest calls, and a link to all of
 * them); call handling, the model and the business-wide leads and calling hours fold into
 * Settings; knowledge, try-it and testing are Training.
 *
 * `LEGACY_SECTIONS` keeps every address the twelve-section page had working: a bookmark,
 * or a test result's "Open call handling", opens the tab that holds it now.
 *
 * Training carries the count of questions it could not answer on real calls, read with the
 * same filters as the list in that tab, so the badge and the list share one cached query.
 */

import type { SettingsSection } from "@/components/console/settingsLayout";
import type { Agent } from "@/lib/api/agents";
import { useKnowledgeGaps } from "@/lib/api/knowledgeGaps";
import { useClientSession } from "@/lib/api/session";

export const AGENT_TABS = {
  overview: "Overview",
  script: "Script",
  training: "Training",
  actions: "Actions",
  captured: "What it notes",
  voice: "Voice",
  settings: "Settings",
} as const;

export type AgentTab = keyof typeof AGENT_TABS;

/** The sections the page had before D-825, and the tab that holds each now. */
export const LEGACY_SECTIONS: Readonly<Record<string, AgentTab>> = {
  test: "training",
  knowledge: "training",
  calls: "settings",
  model: "settings",
  advanced: "settings",
};

/** The open-gap read Training's list makes; shared so the badge and the list are one query. */
export const OPEN_GAPS = { status: "open", limit: 20 } as const;

export function useAgentSections(agent: Pick<Agent, "id">): SettingsSection[] {
  const session = useClientSession();
  const gaps = useKnowledgeGaps(session, { agentId: agent.id, ...OPEN_GAPS });
  // No badge while the count is unread or failed: Training's own list says which, and a
  // missing badge claims nothing.
  const open = gaps.isSuccess && gaps.data.open_count > 0 ? gaps.data.open_count : null;
  return (Object.keys(AGENT_TABS) as AgentTab[]).map((id) => ({
    id,
    label: AGENT_TABS[id],
    ...(id === "training" && open !== null ? { badge: open } : {}),
  }));
}
