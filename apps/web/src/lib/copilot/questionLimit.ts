/**
 * How long a message to Pip may be, and what the ask box says about it.
 *
 * The server refuses a longer question outright (`CopilotAskIn.question`,
 * `apps/api/copilot/schemas.py::MAX_QUESTION_CHARS`), so the box blocks Send and says by how
 * much rather than letting a long paste fail or be cut. Counted in code points, as Python's
 * `len` counts them: `String.length` counts UTF-16 units and would call an emoji two.
 */
export const MAX_QUESTION_CHARS = 8_000;

/** The count appears once a message is this long, so it is there before it matters. */
export const QUESTION_COUNT_FROM = MAX_QUESTION_CHARS - 1_000;

export function questionLength(text: string): number {
  return Array.from(text).length;
}

/** How many characters past the limit `text` is; 0 when it fits. */
export function questionOverBy(text: string): number {
  return Math.max(0, questionLength(text) - MAX_QUESTION_CHARS);
}

export function tooLongLine(over: number): string {
  return `Too long by ${over.toLocaleString("en-IN")} ${over === 1 ? "character" : "characters"} — shorten it or attach it as a file.`;
}
