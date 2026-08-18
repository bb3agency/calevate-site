import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every text token clears WCAG 2.2 SC 1.4.3 on every surface it is painted on (D-341).
 *
 * ═══ WHY THIS FILE EXISTS AT ALL ═══
 *
 * `tests/a11y.ts` disables axe's `color-contrast` rule, with a correct reason: jsdom has
 * no layout, so axe cannot resolve a computed colour and the rule can only report
 * "incomplete". The consequence is that the ONE accessibility failure that is purely
 * arithmetic — two hex values and a formula — was the one the whole 1148-test gate could
 * not see, while it shipped on every route in the product. Driving Chromium found it;
 * this file is what keeps it found, because a browser is not in `make web-check` and the
 * next person to pick a lighter grey will not be running one.
 *
 * The ratio is computed from the SOURCE OF TRUTH — the custom properties in
 * `globals.css`, parsed here — rather than from a list of hexes copied into a test. A
 * copied palette passes forever after somebody edits the stylesheet, which is the exact
 * defect class `check_openapi_fresh` and `wireFixtureGuard` exist for.
 *
 * ═══ WHAT IS AND IS NOT ASSERTED ═══
 *
 * 4.5:1 for every text tier against every surface it actually appears on, which is the
 * Level AA threshold for text below 18.66px / 14pt-bold. Nothing in this product's small
 * type qualifies for the 3:1 large-text allowance, so the stricter number is the only one
 * worth encoding — an exception list here would be a place to hide a regression.
 *
 * Non-text contrast (SC 1.4.11, 3:1 for borders and control boundaries) is NOT checked:
 * `--line` is a hairline between two neutrals and is decorative by the SC's own
 * definition, and asserting 3:1 on it would force a border darker than the design without
 * an accessibility argument behind it.
 */

const CSS = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");

/** The value of one custom property inside a given block. */
function token(block: string, name: string): string {
  const scope = CSS.slice(CSS.indexOf(block));
  const match = scope.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!match) throw new Error(`--${name} not found after "${block}" in globals.css`);
  return match[1].toLowerCase();
}

/** sRGB relative luminance, WCAG 2.x §relative-luminance. */
function luminance(hex: string): number {
  const n = Number.parseInt(hex.slice(1), 16);
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  );
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** WCAG 2.2 SC 1.4.3, Level AA, for text under 18.66px (or 14pt bold). */
/** SC 1.4.11: borders, icons and other non-text that still has to be perceivable. */
const AA_NON_TEXT = 3;

const AA_NORMAL_TEXT = 4.5;

/**
 * The parchment the legal documents are printed on.
 *
 * A literal, and the one value here that is not read from `globals.css`, because it is not
 * a token: `lib/legal/document.tsx` sets it inline as the paper colour for the printed
 * documents. It is included because those are the pages with the most small type in the
 * product and the ones a regulator reads.
 */
const LEGAL_PAPER = "#fdfbef";

describe("the light palette", () => {
  const surfaces = {
    surface: token(":root {", "surface"),
    app: token(":root {", "app"),
    "legal paper": LEGAL_PAPER,
  };
  const inks = {
    ink: token(":root {", "text"),
    "ink-muted": token(":root {", "text-muted"),
    "ink-faint": token(":root {", "text-faint"),
  };

  for (const [inkName, ink] of Object.entries(inks)) {
    for (const [surfaceName, surface] of Object.entries(surfaces)) {
      it(`renders ${inkName} on ${surfaceName} at AA`, () => {
        expect(contrast(ink, surface)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
      });
    }
  }

  /**
   * `--brand` IS A FILL, AND THE AA THRESHOLD IS NOT THE ONE THAT APPLIES TO IT.
   *
   * This assertion originally demanded 4.5:1 of `--brand` itself, on the premise that
   * "`bg-brand` + `text-white` is every primary button in the product". That was true of
   * the branch it was written on and is not true here: `PRIMARY_BUTTON` rests on
   * `--brand-strong` (6.58:1 under white), `tests/contrast.test.ts` REFUSES white text on
   * an unsuffixed `bg-brand`, and what `--brand` is actually used for is medallions,
   * bars, icons and hairlines — non-text, which WCAG 2.2 holds to SC 1.4.11's 3:1.
   *
   * Raising the token to satisfy a threshold that does not govern it would have darkened
   * the brand across ~104 sites to fix a failure the guard next door already prevents.
   * So this asserts what each token is actually for, and the two files divide the work:
   * that one scans SOURCE for the wrong pairing, this one scans the PALETTE for a value
   * that could not be right whoever used it.
   */
  it("keeps --brand above the 3:1 that governs a non-text fill", () => {
    expect(contrast(token(":root {", "brand"), token(":root {", "surface"))).toBeGreaterThanOrEqual(
      AA_NON_TEXT,
    );
  });

  it("carries white on the text-bearing brand at AA", () => {
    expect(contrast("#ffffff", token(":root {", "brand-strong"))).toBeGreaterThanOrEqual(
      AA_NORMAL_TEXT,
    );
  });

  /**
   * The pairing this file was written to catch, and it caught a live one.
   *
   * `bg-brand-soft` + `text-brand` is 3.08:1 and was the "completed" pill on the calls
   * screen — small text, on the busiest screen in the client console. Thirty other
   * `bg-brand-soft` sites already used `text-brand-strong` (6.01:1); those two were the
   * outliers, not the convention. Asserting the PAIR rather than the site is what stops
   * the thirty-third from being written the wrong way.
   */
  it("carries the text-bearing brand on the soft brand ground at AA", () => {
    expect(
      contrast(token(":root {", "brand-strong"), token(":root {", "brand-soft")),
    ).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
  });
});

describe("the dark palette", () => {
  // Nothing toggles `.dark` yet (globals.css records why), so these are the tests that
  // stop the toggle landing on top of a contrast failure nobody could see beforehand.
  const surfaces = {
    surface: token(".dark {", "surface"),
    app: token(".dark {", "app"),
  };
  const inks = {
    ink: token(".dark {", "text"),
    "ink-muted": token(".dark {", "text-muted"),
    "ink-faint": token(".dark {", "text-faint"),
  };

  for (const [inkName, ink] of Object.entries(inks)) {
    for (const [surfaceName, surface] of Object.entries(surfaces)) {
      it(`renders ${inkName} on ${surfaceName} at AA`, () => {
        expect(contrast(ink, surface)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
      });
    }
  }
});
