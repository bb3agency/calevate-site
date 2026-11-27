"use client";

/**
 * WHICH TAB HOLDS WHICH SECTION of a campaign's page, and the one way to go to a section.
 *
 * The page used to be one long scroll, so every "Add people", "Show me" and "Go to Agent"
 * was a `scrollIntoView` on an element id. With tabs the element may sit in a hidden panel,
 * where a scroll moves nothing (defect C13-a: "Show me" did nothing). `openCampaignSection`
 * switches to the section's tab first, then scrolls and outlines it, and every jump on the
 * page goes through it.
 */

import { createContext, useCallback, useContext, type ReactNode } from "react";

import { CAMPAIGN_TEST_ANCHOR } from "@/lib/api/agentJobs";
import { lookup } from "@/lib/lookup";

export type CampaignTab = "script" | "people" | "settings" | "checks" | "progress" | "calls" | "improve";

/** A draft or scheduled campaign: get it ready. Checks is last because Start follows it. */
export const DRAFT_TABS: readonly CampaignTab[] = ["script", "people", "settings", "checks"];
/** A launched campaign: how it is going first, the set-up after it. */
export const LAUNCHED_TABS: readonly CampaignTab[] = ["progress", "calls", "script", "people", "settings", "improve"];

/**
 * Old `?tab=` values, so a saved link or a link from another screen still opens where its
 * content now lives: Set up became Script (its first section), and Questions to answer is
 * the first section of Improve.
 */
const TAB_ALIASES: Readonly<Record<string, CampaignTab>> = { setup: "script", questions: "improve" };

/**
 * The tab a `?tab=` value opens, or `null` when it names nothing this campaign shows (the
 * page then opens its first tab). A launched-only tab asked of a draft is honoured for
 * Improve alone: test calls on a draft feed it, and the account Improve page links to it.
 */
export function linkedCampaignTab(requested: string | null, launched: boolean): CampaignTab | null {
  if (!requested) return null;
  const tab = (lookup(TAB_ALIASES, requested) ?? requested) as CampaignTab;
  const tabs = launched ? LAUNCHED_TABS : DRAFT_TABS;
  if (tabs.includes(tab)) return tab;
  if (!launched && tab === "improve") return tab;
  return null;
}

/** The element ids the page's sections carry, kept here so the map below cannot drift. */
export function peopleSectionId(campaignId: string): string {
  return `people-${campaignId}`;
}
export function complianceCardId(campaignId: string): string {
  return `compliance-${campaignId}`;
}
export function agentSectionId(campaignId: string): string {
  return `agent-${campaignId}`;
}
export const MAIN_TASK_SECTION = "campaign-main-task";
export const MATERIALS_SECTION = "campaign-materials";
export const SCRIPT_SECTION = "campaign-script";
/** `jobAlertsAnchor("campaign")`, which alert emails and the Alerts screen link to. */
export const ALERTS_SECTION = "campaign-alerts";

/** The tab that holds `sectionId`, or `null` for an id this page does not know. */
export function campaignTabFor(sectionId: string, campaignId: string, launched: boolean): CampaignTab | null {
  if (
    [MAIN_TASK_SECTION, MATERIALS_SECTION, SCRIPT_SECTION, CAMPAIGN_TEST_ANCHOR, agentSectionId(campaignId)].includes(
      sectionId,
    ) ||
    sectionId === `campaign-notes-${campaignId}`
  )
    return "script";
  if (sectionId === peopleSectionId(campaignId)) return "people";
  if (sectionId === ALERTS_SECTION) return "settings";
  // Before launch the checks are their own tab; after it, their record sits in Settings.
  if (sectionId === complianceCardId(campaignId)) return launched ? "settings" : "checks";
  return null;
}

/** How a landed-on section is marked: red for something to fix, the brand ring otherwise. */
export type SectionMark = "problem" | "focus";

const OUTLINE_MS = 12_000;

/** Outline the sections, scroll to the first, and clear the outline once the owner is there. */
export function markSections(ids: readonly string[], mark: SectionMark): void {
  const found = [...new Set(ids)]
    .map((id) => document.getElementById(id))
    .filter((el): el is HTMLElement => el != null);
  const colour = mark === "problem" ? "var(--danger)" : "var(--brand-strong)";
  for (const el of found) {
    el.style.outline = `3px solid ${colour}`;
    el.style.outlineOffset = "6px";
    window.setTimeout(() => {
      el.style.outline = "";
      el.style.outlineOffset = "";
    }, OUTLINE_MS);
  }
  found[0]?.scrollIntoView?.({ block: "start", behavior: "smooth" });
}

export type OpenCampaignSection = (sectionIds: string | readonly string[], mark?: SectionMark) => void;

/** Outside a campaign page (a section reused elsewhere) there are no tabs: scroll only. */
const scrollOnly: OpenCampaignSection = (ids, mark = "focus") => markSections(typeof ids === "string" ? [ids] : ids, mark);

const OpenSection = createContext<OpenCampaignSection>(scrollOnly);

/**
 * Gives the page's sections `openCampaignSection`. `selectTab` switches the page's tab and
 * its `?tab=`; the scroll waits two frames so the panel has been shown and laid out.
 */
export function CampaignSectionsProvider({
  campaignId,
  launched,
  selectTab,
  children,
}: {
  campaignId: string;
  launched: boolean;
  selectTab: (tab: CampaignTab) => void;
  children: ReactNode;
}) {
  const open = useCallback<OpenCampaignSection>(
    (ids, mark = "focus") => {
      const list = typeof ids === "string" ? [ids] : [...ids];
      const tab = list.length > 0 ? campaignTabFor(list[0], campaignId, launched) : null;
      if (tab) selectTab(tab);
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => markSections(list, mark)));
    },
    [campaignId, launched, selectTab],
  );
  return <OpenSection.Provider value={open}>{children}</OpenSection.Provider>;
}

/** `openCampaignSection(id)`: switch to the tab holding the section, then scroll to it. */
export function useOpenCampaignSection(): OpenCampaignSection {
  return useContext(OpenSection);
}
