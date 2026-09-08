import { describe, expect, it } from "vitest";

import { copyUnder, type CopyString } from "./copyScan";

/**
 * A CLIENT NEVER READS THE NAME OF THE COMPANY THAT SPEAKS, AND NEVER READS ONE OF OUR
 * SETTINGS — over every surface a stranger or a client can reach, as a property of the
 * SOURCE rather than of one render.
 *
 * ## Why this exists as a sweep and not as another per-screen assertion
 *
 * The rule is the founder's, 7 September 2026, and it has a mechanism behind it: what a
 * client buys is a named voice QUALITY, defined once in `apps/api/billing/rates.py::
 * VOICE_TIER_LABELS` and carried to the browser on the rate card, the pack card, the voice
 * catalogue and the credit lots. Which company synthesises each quality is ours and must
 * be able to change without a client-visible rename — so `sarvam` and `cartesia` key the
 * money, the metering and the lot columns, and reach no screen.
 *
 * Four or five screens already assert this about their own render (`agents.test.tsx`,
 * `agentVoice.test.tsx`, `marketingPages.test.tsx`, `credits.test.tsx`). Each of those is
 * a claim about a component somebody remembered to write a test for, and the failure this
 * guard is built for is the opposite one: a sentence written on a screen NOBODY thought of
 * as a money screen — a glossary entry, an empty state, a tooltip, an `aria-label`, a FAQ
 * answer — where the field name was the handiest word to hand. That is precisely how
 * `cartesia_tier_label` becomes "the Cartesia voice" in copy, and no render test that does
 * not exist can catch it.
 *
 * ## The two rules, and why the second one is scoped away from the client realm
 *
 * 1. **No voice vendor, anywhere a client or a stranger reads.** The list is the two
 *    vendors and the two engines they are sold under (`Bulbul`, `Sonic`), because a
 *    sentence naming the MODEL is the same disclosure as one naming the company.
 * 2. **No wire identifier on the marketing surfaces.** `plainLanguageGuard.test.ts` already
 *    holds that rule over `src/app/c`, and holding it twice would be two spellings of one
 *    thing — so this half runs over the pages the console guard never walked. The failure
 *    it exists for is a marketing page quoting a SETTING (`self_serve_inr_per_min` priced
 *    this card until D-547 and was named in copy on two surfaces) or a wire field
 *    (`bonus_pct`) as though it were a product word.
 *
 * ## What is deliberately NOT scanned
 *
 * - **`src/app/admin` and the ops console.** An operator reading "Cartesia" is the whole
 *   point: they install that key, they read that invoice, and `ModelPricingPanel.tsx` says
 *   so in its own header. The exception is deliberate and is the reason this guard names
 *   its roots rather than scanning `src/`.
 * - **`src/lib/legal`.** The sub-processor register, the DPA and the privacy notice MUST
 *   name every vendor — that is what a disclosure IS, and `legalRegister.test.ts` pins the
 *   register's completeness from the other direction. A guard that banned a vendor's name
 *   there would be a guard against compliance.
 * - **Comments.** `copyScan` parses; a docstring is not a literal in a copy position, which
 *   is the whole reason this is an AST walk and not a grep (`tests/sourceScan.ts` records
 *   the three times that lesson was paid for).
 */

/**
 * The surfaces a person who is not an operator can reach: the client console, both realms'
 * account/sign-in screens, every marketing page and the components they are built from.
 *
 * `src/lib/marketing` is here because the residency paragraph and the four verticals live
 * there rather than in a page — a constant is exactly where a sentence hides from a guard
 * that only reads `src/app`.
 */
const PUBLIC_SURFACES = [
  "src/app/c",
  "src/app/(auth)",
  "src/app/page.tsx",
  "src/app/not-found.tsx",
  "src/app/error.tsx",
  "src/app/global-error.tsx",
  "src/app/pricing",
  "src/app/roi",
  "src/app/resources",
  "src/app/security",
  "src/app/solutions",
  "src/app/industries",
  "src/app/why-calevate",
  "src/app/signup",
  "src/app/invite",
  "src/app/legal",
  // EVERY shared component, not a hand-picked few. The admin console's own panels live
  // under `src/app/admin` and are not here; what is under `src/components` is either
  // client-facing or shared, and a shared component that names a vendor names it to a
  // client on one of its two mounts. `voicePicker.tsx` is the case in point: it is mounted
  // in the admin realm only today, and it still may not print `provider`.
  "src/components",
  "src/lib/marketing",
];

/** Everything above except the console, which `plainLanguageGuard.test.ts` already walks. */
const MARKETING_SURFACES = PUBLIC_SURFACES.filter((root) => root !== "src/app/c");

/**
 * The vendors, and the engines they are sold under. Word-bounded: "sonic" is a word, and a
 * ban that fired on "supersonic" is a ban somebody deletes.
 */
const VOICE_VENDOR = /\b(sarvam|cartesia|bulbul|saaras|sonic)\b/i;

/** A wire identifier: two or more lowercase words joined by underscores. */
const WIRE_NAME = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

function report(entry: CopyString, name: string): string {
  return `${entry.file}:${entry.line} — “${name}” in: ${entry.text.trim().slice(0, 120)}`;
}

describe("what a client reads names no vendor and no setting", () => {
  it("is reading the surfaces it claims to read", () => {
    // THE PREMISE, first and alone (`plainLanguageGuard`'s rule, for its reason): a walk
    // that has silently stopped matching finds nothing and passes for ever. Two sentences
    // from two roots that are NOT the client realm, so a marketing root dropping out of
    // the list is caught here rather than by a green suite.
    const seen = copyUnder(PUBLIC_SURFACES).map((entry) => entry.text);
    expect(seen.length, "the copy scan found almost nothing — have the roots moved?")
      .toBeGreaterThan(700);
    const all = seen.join("\n");
    expect(all).toContain("Evenings, Sundays and festival days");
    expect(all).toContain("Prepaid balance, if your account runs that way");
  });

  it("never names the company that speaks", () => {
    const found = copyUnder(PUBLIC_SURFACES)
      .filter((entry) => VOICE_VENDOR.test(entry.text))
      .map((entry) => report(entry, VOICE_VENDOR.exec(entry.text)?.[0] ?? ""));
    expect(
      found,
      "a client buys a named voice QUALITY, never a vendor. The two names are the " +
        "server's (`billing/rates.py::VOICE_TIER_LABELS`) and travel on the rate card, the " +
        "pack card, the voice catalogue and the lots — read the label the API sent, and " +
        "render nothing when it sent none. The admin console and the legal documents are " +
        "the two deliberate exceptions and are not scanned here.",
    ).toEqual([]);
  });

  it("never quotes one of our settings or wire fields on a marketing page", () => {
    const found: string[] = [];
    for (const entry of copyUnder(MARKETING_SURFACES)) {
      WIRE_NAME.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = WIRE_NAME.exec(entry.text)) !== null) found.push(report(entry, match[0]));
    }
    expect(
      found,
      "these are our own identifiers in copy a stranger reads. A setting name on a " +
        "marketing page is a promise about a control they cannot see and we may rename; " +
        "say the behaviour instead.",
    ).toEqual([]);
  });
});
