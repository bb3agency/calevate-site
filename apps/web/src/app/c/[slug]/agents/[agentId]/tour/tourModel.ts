/**
 * THE AGENT PAGE TOUR'S CONTENT, TARGETS AND GEOMETRY (D-855): kept apart from the React
 * component so each piece can be tested without a layout engine.
 *
 * Five steps at most. Tours longer than five finish under half the time and user-started
 * ones finish far more often than ones that start themselves (Chameleon's benchmarks,
 * VENDOR-PUBLISHED, docs/evidence/onboarding-vs-outpero-2026-10-23.md §4 item 4), so the
 * tour only ever opens because the owner asked for it.
 */

import { ASSISTANT_NAME } from "@/lib/copilot/assistantName";

import { AGENT_TABS, AGENT_TABS_LABEL, type AgentTab } from "../sections/agentSections";

/**
 * `?tour=1` on the agent page opens the tour once, as if "Show me around" had been
 * pressed; the parameter is then removed so a reload does not reopen it. It is for a link
 * the owner clicks (the first-call result screen), never for opening it unasked.
 */
export const TOUR_PARAM = "tour";

/** The "Try it" link in the agent header carries this, so the tour can point at it. */
export const TRY_IT_ANCHOR = "try-it";

export type TourStep = {
  id: "script" | "pip" | "try" | "teach" | "voice";
  title: string;
  body: string;
  /** The element the step points at, or null when it is not on screen. */
  target: (doc: Document) => HTMLElement | null;
};

/**
 * A tab of the agent page. The tab buttons are drawn by `SettingsLayout` from the
 * interior tabs kit, whose ids end in `-tab-<section id>`; scoping to the agent page's
 * own tab list keeps another tab list on the page from answering.
 */
function agentTab(id: AgentTab) {
  return (doc: Document) =>
    doc.querySelector<HTMLElement>(
      `[role="tablist"][aria-label="${AGENT_TABS_LABEL}"] [role="tab"][id$="-tab-${id}"]`,
    );
}

/**
 * Pip's launcher is in the console header (`CopilotDock`), on every screen of the client
 * realm; its accessible name is its stable handle. The Script tab's own Pip panel is not
 * used because it exists only while that tab is open, and the tour never switches tabs:
 * a switch could stop on the unsaved-edits guard halfway through a step.
 */
function pipLauncher(doc: Document) {
  return doc.querySelector<HTMLElement>(`button[aria-label="Ask ${ASSISTANT_NAME}"]`);
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    id: "script",
    title: "Read its script",
    body: `Everything it says on a call. Open ${AGENT_TABS.script} to change a line.`,
    target: agentTab("script"),
  },
  {
    id: "pip",
    title: `Ask ${ASSISTANT_NAME} to change it`,
    body: "Say what to change. You check it before callers hear it.",
    target: pipLauncher,
  },
  {
    id: "try",
    title: "Try it before callers do",
    body: "Chat with it, or hear it on a real call.",
    target: (doc) => doc.querySelector<HTMLElement>(`[data-tour="${TRY_IT_ANCHOR}"]`),
  },
  {
    id: "teach",
    title: "Teach it facts",
    body: `Prices, hours, bookings. Add them in ${AGENT_TABS.training}.`,
    target: agentTab("training"),
  },
  {
    id: "voice",
    title: "Choose its voice",
    body: `Play the voices in ${AGENT_TABS.voice} and pick the one your callers hear.`,
    target: agentTab("voice"),
  },
];

/** Below this width the card is a sheet on the bottom edge, where the thumb is (`sm`). */
export const SHEET_BELOW_PX = 640;
const GUTTER = 16;
const GAP = 12;

export type Box = { top: number; left: number; width: number; height: number };

export type Placement =
  | { mode: "sheet" }
  | { mode: "float"; top: number; left: number; origin: string };

/**
 * Where the card goes. On a phone it is always the sheet. On a wider screen it sits under
 * the target, or over it when there is no room below, clamped inside the viewport, and
 * scales in from the side that faces the target. With no target it is centred.
 */
export function placeCard(
  target: Box | null,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
): Placement {
  if (viewport.width < SHEET_BELOW_PX) return { mode: "sheet" };
  const maxLeft = Math.max(GUTTER, viewport.width - card.width - GUTTER);
  if (target === null) {
    return {
      mode: "float",
      top: Math.max(GUTTER, (viewport.height - card.height) / 2),
      left: Math.min(maxLeft, Math.max(GUTTER, (viewport.width - card.width) / 2)),
      origin: "center",
    };
  }
  const centre = target.left + target.width / 2;
  const left = Math.min(maxLeft, Math.max(GUTTER, centre - card.width / 2));
  const below = target.top + target.height + GAP;
  const above = target.top - GAP - card.height;
  const fitsBelow = below + card.height <= viewport.height - GUTTER;
  const top = fitsBelow || above < GUTTER ? Math.min(below, viewport.height - card.height - GUTTER) : above;
  const originX = Math.min(card.width, Math.max(0, centre - left));
  return { mode: "float", top: Math.max(GUTTER, top), left, origin: `${originX}px ${top >= target.top ? "0" : "100%"}` };
}

/** Per person, per browser: there is no server-side store of a person's UI preferences. */
export function seenKey(userId: string): string {
  return `calevate:agent-tour-seen:${userId}`;
}

export function readSeen(userId: string): boolean {
  try {
    return window.localStorage.getItem(seenKey(userId)) === "1";
  } catch {
    return false;
  }
}

export function writeSeen(userId: string): void {
  try {
    window.localStorage.setItem(seenKey(userId), "1");
  } catch {
    // Storage blocked (private window, site data off): the button stays prominent.
  }
}
