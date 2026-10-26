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
 * Training carries the count of its Questions to answer (D-893), read with the same query as
 * the list at the top of that tab, so the badge and the list are one cached read.
 */

import type { SettingsSection } from "@/components/console/settingsLayout";
import type { Agent } from "@/lib/api/agents";
import { useTeachQuestions } from "@/lib/api/teachQuestions";
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

/** The tab list's accessible name; the page tour finds the tabs by it. */
export const AGENT_TABS_LABEL = "About this agent";

/** The sections the page had before D-825, and the tab that holds each now. */
export const LEGACY_SECTIONS: Readonly<Record<string, AgentTab>> = {
  test: "training",
  knowledge: "training",
  calls: "settings",
  model: "settings",
  advanced: "settings",
};


export function useAgentSections(agent: Pick<Agent, "id">): SettingsSection[] {
  const session = useClientSession();
  const questions = useTeachQuestions(session, agent.id);
  // No badge while the count is unread or failed: Training's own list says which, and a
  // missing badge claims nothing.
  const open = questions.isSuccess && questions.data.open_count > 0 ? questions.data.open_count : null;
  return (Object.keys(AGENT_TABS) as AgentTab[]).map((id) => ({
    id,
    label: AGENT_TABS[id],
    ...(id === "training" && open !== null ? { badge: open } : {}),
  }));
}
