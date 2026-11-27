"use client";

/**
 * THE AGENT PAGE'S SIX TABS (redesign 28 Nov 2026, `docs/design/redesign-2026-11-28/PLAN.md`
 * §2, reconciling the founder's six with D-997):
 * What it says · What it knows · Actions · What it notes · Voice · Settings.
 *
 * The agent is still the staff member with no script of its own (D-997): what a call says is
 * written on its job, a campaign or an Inbound line. "What it says" lists those jobs, each
 * with the first thing it says and a link to where its words are changed, so the owner finds
 * an agent's words on the agent without the script being stored twice.
 *
 * "What it says" opens first because it holds the truthful-answer guarantee and the opening
 * notices (doctrine §8 rule 7: never behind a tab switch). The order after it is the order an
 * owner sets an agent up in: what it knows, what it does, what it writes down, how it sounds,
 * then the settings changed once.
 *
 * `LEGACY_SECTIONS` keeps every older address working: a bookmark, a link Pip, an email or the
 * server builds (`agents/readiness.py` `?section=training`, `crm/attention.py`
 * `?section=settings#call-handling`), or a test result's "Open call handling", opens the tab
 * that holds it now. The URL keeps the old value; the layout resolves it on read, so a `#`
 * anchor after it still lands.
 *
 * What it knows carries the count of its Questions to answer (D-893), read with the same query
 * as the list at the top of that tab, so the badge and the list are one cached read.
 */

import type { SettingsSection } from "@/components/console/settingsLayout";
import type { Agent } from "@/lib/api/agents";
import { useTeachQuestions } from "@/lib/api/teachQuestions";
import { useClientSession } from "@/lib/api/session";

export const AGENT_TABS = {
  script: "What it says",
  knowledge: "What it knows",
  actions: "Actions",
  notes: "What it notes",
  voice: "Voice",
  settings: "Settings",
} as const;

export type AgentTab = keyof typeof AGENT_TABS;

/** The tab list's accessible name; the page tour finds the tabs by it. */
export const AGENT_TABS_LABEL = "About this agent";

/** Sections the page no longer has, and the tab that holds what they held. */
export const LEGACY_SECTIONS: Readonly<Record<string, AgentTab>> = {
  // The first tab before 28 Nov 2026; its notices and checklist are on What it says.
  overview: "script",
  // The Calls section was call handling (D-751), which is on Settings; the latest calls
  // are the header's "Calls (n)".
  calls: "settings",
  training: "knowledge",
  test: "knowledge",
  captured: "notes",
  model: "settings",
  advanced: "settings",
};

/** The anchor on Settings that holds What it is (name, direction, languages). */
export const WHAT_IT_IS_ANCHOR = "what-it-is";

/** Where an agent's words are written: its inbound line, or the campaigns that call. */
export function scriptsHome(slug: string, direction: Agent["direction"]): string {
  return direction === "outbound" ? `/c/${slug}/campaigns` : `/c/${slug}/inbound`;
}

export function useAgentSections(agent: Pick<Agent, "id">): SettingsSection[] {
  const session = useClientSession();
  const questions = useTeachQuestions(session, agent.id);
  // No badge while the count is unread or failed: the tab's own list says which, and a
  // missing badge claims nothing.
  const open = questions.isSuccess && questions.data.open_count > 0 ? questions.data.open_count : null;
  return (Object.keys(AGENT_TABS) as AgentTab[]).map((id) => ({
    id,
    label: AGENT_TABS[id],
    ...(id === "knowledge" && open !== null ? { badge: open } : {}),
  }));
}
