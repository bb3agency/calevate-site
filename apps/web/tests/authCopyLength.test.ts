import { describe, expect, it } from "vitest";

import { SHORT_LINE, defaultCopyUnder, longLines, type Hidden } from "./shortCopy";

/**
 * BUTTONS, NOT PARAGRAPHS — the sign-in, sign-up, invitation and password screens show no
 * line of default copy longer than about 60 characters.
 *
 * These are the first screens a new owner or invited colleague meets, usually from a link
 * opened on a phone. A line longer than one phone line is where they stop reading and start
 * guessing; the reason behind a rule belongs behind a tap, not above the button.
 */

const ROOTS = [
  "src/app/(auth)",
  "src/app/signup",
  "src/app/invite",
  "src/components/authn",
] as const;

/** Page metadata (a search-result description), not screen copy. */
const SKIP_FILES = ["src/app/signup/layout.tsx"];

const HIDDEN: Hidden = {
  /** Elements whose CHILDREN are shown only after a tap. */
  elements: new Set(["InfoTip", "Disclosure", "ConfirmDialog", "Popover", "TermGloss"]),
    /** Tooltips, screen-reader names, SVG path data and a confirm dialog's body. */
  attrs: /^(info|infoLabel|aria-label|why|d|everywhereConsequence)$/,
};

describe("auth and sign-up screens: buttons, not paragraphs", () => {
  const copy = defaultCopyUnder(ROOTS, HIDDEN, undefined, SKIP_FILES);

  it("reads copy from every screen it guards", () => {
    for (const root of ROOTS) {
      expect(copy.some((c) => c.file.startsWith(root)), root).toBe(true);
    }
  });

  it(`shows no default line longer than ${SHORT_LINE} characters`, () => {
    expect(longLines(copy)).toEqual([]);
  });
});
