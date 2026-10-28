import { describe, expect, it } from "vitest";

import { SHORT_LINE, defaultCopyUnder, longLines } from "./shortCopy";

/**
 * BUTTONS, NOT PARAGRAPHS — on the leads, calls and call-backs screens (founder, Oct 2026).
 *
 * The people reading these screens are small-business owners and staff, often on a phone
 * and often reading English as a second language. Every line they see by default is short;
 * a next step is a button, and an explanation sits behind a tap. This guard holds the
 * "short" half: no string these screens put in front of a person runs past about 60
 * characters, so a paragraph cannot creep back in one edit at a time.
 *
 * It reads the same walk every copy guard uses (`shortCopy.ts`), so comments, class names
 * and wire values are not counted. Nothing is treated as behind a tap here: every string
 * these screens hold is measured.
 */

const SCREENS = [
  "src/app/c/[slug]/leads",
  "src/app/c/[slug]/calls",
  "src/app/c/[slug]/callbacks",
];

/** About one line on a 375px phone at body size. */
const MAX = SHORT_LINE;

/** Strings no person reads on the screen, each with the reason. */
const EXEMPT: ReadonlyArray<{ text: RegExp; reason: string }> = [
  {
    text: /^(Saves immediately — this control has no separate Save button\.|Captured detail names on file \(the field names, never their values\))$/,
    reason: "declared to Pip by the lead page's useCopilotSurface, never rendered",
  },
];

/** The copilot surface module is the assistant's declaration of the leads screen. */
const EXEMPT_FILES = ["src/app/c/[slug]/leads/leadsCopilotSurface.ts"];

describe("the leads, calls and call-backs screens speak in short lines", () => {
  const strings = defaultCopyUnder(SCREENS, {}, { chains: true }, EXEMPT_FILES);

  it("reads the screens at all", () => {
    // A walk that found nothing would pass the rule below on an empty list.
    expect(strings.length).toBeGreaterThan(100);
    expect(strings.some((found) => found.text === "Call off")).toBe(true);
  });

  it(`keeps every visible line to about ${MAX} characters`, () => {
    expect(longLines(strings, (text) => EXEMPT.some((rule) => rule.text.test(text)))).toEqual([]);
  });
});
