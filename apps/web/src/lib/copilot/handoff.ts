/**
 * Where a confirmed Pip action's result is waiting, for the one link its outcome card offers.
 *
 * Some actions finish somewhere else: Pip queues the fixes for an agent's failed tests, and
 * they arrive on that agent's Training tab a minute or two later. The outcome says so in the
 * server's words; this adds the way there, so the person is not left with a sentence and a
 * button that only closes the card. Keyed by the wire's tool name and read through `lookup`;
 * a tool not listed here gets no link, which is every action whose result is already on the
 * screen it was asked from.
 */

import { lookup } from "@/lib/lookup";

/** The Practice callers card on an agent's Training tab: where suggested fixes are reviewed. */
export const PRACTICE_CALLERS_ANCHOR = "practice-callers";

interface Handoff {
  label: string;
  /** The console path for the object the action produced or changed. */
  path: (slug: string, objectId: string) => string;
}

const HANDOFF: Record<string, Handoff> = {
  agent_tests_fix: {
    label: "Go to the fixes",
    path: (slug, id) => `/c/${slug}/agents/${id}?section=training#${PRACTICE_CALLERS_ANCHOR}`,
  },
  agent_script_suggest: {
    label: "Go to the script",
    path: (slug, id) => `/c/${slug}/agents/${id}?section=script`,
  },
};

/** The link for a confirmed action's outcome, or null when its result is already on screen. */
export function handoffFor(
  tool: string,
  slug: string,
  objectId: string,
): { label: string; path: string } | null {
  const entry = lookup(HANDOFF, tool);
  if (entry === undefined || objectId === "") return null;
  return { label: entry.label, path: entry.path(slug, objectId) };
}
