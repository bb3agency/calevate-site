/**
 * Text limits the server enforces, mirrored once so a field's `maxLength` and its counter
 * agree with the 422 it would otherwise meet. `tests/textLimits.test.ts` reads each from
 * `openapi.json`, so a server change that moves one fails there instead of drifting here.
 */

/** A campaign's or an inbound line's main task (`campaigns/workspace.MAIN_TASK_MAX`). */
export const MAIN_TASK_MAX_CHARS = 4000;

/** What the first agent should do, in the owner's words (`first_run/models.MAX_BRIEF_CHARS`). */
export const BRIEF_MAX_CHARS = 4000;

/** A campaign note, source note or answer to Pip's question (`campaigns/workspace.NOTE_MAX`). */
export const NOTE_MAX_CHARS = 4000;

/**
 * An agent's name. The first-run screens' server bound is 60 and the voice platform shows 60
 * characters of a name (`engine/thinnest.NAME_MAX_CHARS`); the other agent routes accept more,
 * so every screen holds the one 60 rather than letting a name saved on one be refused on another.
 */
export const AGENT_NAME_MAX_CHARS = 60;

/** `1,234 / 4,000`: a counter under a long field. */
export function charCount(used: number, max: number): string {
  return `${used.toLocaleString("en-IN")} / ${max.toLocaleString("en-IN")}`;
}
