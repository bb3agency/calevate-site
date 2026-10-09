import type { CopilotFact, CopilotSurface } from "./types";

/**
 * WHAT THE PERSON HAS SELECTED, as a fact the assistant can act on ("summarise these leads").
 *
 * IDS, NEVER A ROW'S CONTENTS. An id names a record to the read and write tools, which look
 * it up under the person's own session; it tells the model nothing about the person behind
 * it, so the screen's rule — nothing about a row is declared — still holds.
 *
 * Bounded at `MAX_SELECTED_IDS`: a whole page of leads is 50, and a fact value is a short
 * string on the wire. "Every lead the filters match" is said in words instead, because the
 * ids are not on the page to send.
 */
export const MAX_SELECTED_IDS = 50;

/** The fact's key. `leadsCopilotSurface.ts` has declared it under this key since D-501. */
export const SELECTION_KEY = "selection";

export function selectionFact(
  label: string,
  ids: readonly string[],
  wholeQuery: boolean,
): CopilotFact {
  if (wholeQuery) {
    return { key: SELECTION_KEY, label, value: "every row the filters match" };
  }
  const sent = ids.slice(0, MAX_SELECTED_IDS);
  const value =
    sent.length === 0
      ? "0"
      : `${ids.length} selected${ids.length > sent.length ? ` (first ${sent.length})` : ""}: ${sent.join(", ")}`;
  return { key: SELECTION_KEY, label, value };
}

/** How the panel names the selection in its header, or null when nothing is selected. */
export function selectionSummary(surface: CopilotSurface): string | null {
  const fact = surface.facts?.find((candidate) => candidate.key === SELECTION_KEY);
  if (fact === undefined || fact.value === "0" || fact.value === "") return null;
  if (fact.value === "every row the filters match") return "Everything these filters match";
  const count = Number.parseInt(fact.value, 10);
  if (!Number.isFinite(count) || count <= 0) return null;
  return `${count} selected`;
}
