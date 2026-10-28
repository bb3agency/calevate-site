import { describe, expect, it } from "vitest";

import { SHORT_LINE, defaultCopyUnder, longLines, type Hidden } from "./shortCopy";

/**
 * BUTTONS, NOT PARAGRAPHS — the client Settings, Phone number and Verify your business
 * screens show no line of default copy longer than about 60 characters.
 *
 * Our clients read these screens on a phone, often in their second language; a setting is
 * a short label, its control and at most a one-line hint, and the explanation sits behind
 * a tap. This walks the source with `shortCopy` (the one reader of "what does a person see")
 * and drops what is NOT shown by default: an ⓘ tip's body, a disclosure's or a dialog's
 * contents, a notice's `info`, the assistant's screen declaration, and the panels that only
 * render inside an accordion. What is left is the default view, line by line.
 *
 * A source walk rather than a render because a render shows one state per fixture, and the
 * long sentence is usually in the state nobody wrote a fixture for (the refusal, the
 * suspended approval, the trial that ended).
 */

const ROOTS = [
  "src/app/c/[slug]/settings",
  "src/app/c/[slug]/phone-number",
  "src/app/c/[slug]/verify-business",
] as const;

/** About 8 words: the bar a line of default copy must stay under. */
const MAX = SHORT_LINE;

/** Files that are not screen copy: the assistant's declaration of the screen. */
const SKIP_FILES = ["src/app/c/[slug]/verify-business/copilot.ts"];

const HIDDEN: Hidden = {
  /** Elements whose CHILDREN are shown only after a tap. Their own props still count. */
  elements: new Set(["InfoTip", "Disclosure", "ConfirmDialog", "Popover"]),
  /** Props that are explanations behind an ⓘ, never shown by default. */
  attrs: /^(info|infoLabel|aria-label|why)$/,
  calls: new Set(["useCopilotSurface"]),
  /**
   * Components that only ever render behind a tap: the "About verification" accordion's
   * panels and the campaign-registration details, which mount inside a closed disclosure.
   */
  functions: new Set([
    "WhatWeKeep",
    "WhatItAffects",
    "Affected",
    "PhoneNumbers",
    "OnFile",
    "DltStatuses",
    "CalevateTelemarketerId",
    "DltOnFile",
  ]),
  /** Constants rendered only inside an ⓘ. */
  constants: /^OWNER_SENTENCE$/,
};

/**
 * Kept verbatim and in view on purpose: the words a person ticks to accept the
 * no-cold-calls pledge on the business's behalf. It is a legal declaration (D-692), so it
 * is not shortened to fit a guard.
 */
const KEPT_VERBATIM = new Set([
  "I have read the pledge and the disclosure, and accept them on behalf of the business.",
]);

describe("client settings, phone number and verification screens: buttons, not paragraphs", () => {
  const copy = defaultCopyUnder(ROOTS, HIDDEN, undefined, SKIP_FILES);

  it("reads copy from every screen it guards", () => {
    // A walk that found nothing would pass for the wrong reason.
    for (const root of ROOTS) {
      expect(copy.some((c) => c.file.startsWith(root)), root).toBe(true);
    }
  });

  it(`shows no default line longer than ${MAX} characters`, () => {
    expect(longLines(copy, (text) => KEPT_VERBATIM.has(text))).toEqual([]);
  });
});
