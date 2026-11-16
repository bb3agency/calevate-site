"use client";

/**
 * THE AGENT PAGE'S FOUR TABS (D-997, founder 16 Nov 2026):
 * Overview · Actions · Settings · Training.
 *
 * The agent is the staff member: its name, voice, languages, settings and actions. It has no
 * script of its own; what it says is written where the call comes from, an inbound line
 * (`/c/{slug}/inbound`) or a campaign, because one agent can answer a line and call for a
 * campaign in different words. So the old Script tab is gone rather than moved, Voice and
 * What it notes are sections of Settings, and Overview says once where scripts live now.
 * What it notes sits in Settings only until lines and campaigns carry their own fields.
 *
 * Calls fold into Overview (its latest calls, and a link to all of them); call handling, the
 * model and the business-wide leads and calling hours are in Settings; knowledge, try-it and
 * testing are Training (D-825).
 *
 * `LEGACY_SECTIONS` keeps every older address working: a bookmark, a link Pip or the server
 * still builds, or a test result's "Open call handling" opens the tab that holds it now.
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
  actions: "Actions",
  settings: "Settings",
  training: "Training",
} as const;

export type AgentTab = keyof typeof AGENT_TABS;

/** The tab list's accessible name; the page tour finds the tabs by it. */
export const AGENT_TABS_LABEL = "About this agent";

/** Sections the page no longer has, and the tab that holds what they held. */
export const LEGACY_SECTIONS: Readonly<Record<string, AgentTab>> = {
  test: "training",
  knowledge: "training",
  calls: "settings",
  model: "settings",
  advanced: "settings",
  script: "overview",
  voice: "settings",
  captured: "settings",
};

/** Where an agent's words are written now: its inbound line, or the campaigns that call. */
export function scriptsHome(slug: string, direction: Agent["direction"]): string {
  return direction === "outbound" ? `/c/${slug}/campaigns` : `/c/${slug}/inbound`;
}

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
