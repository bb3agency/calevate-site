import { describe, expect, it } from "vitest";

import { copyUnder } from "./copyScan";

/**
 * THE CLIENT REALM DOES NOT SPEAK IN WIRE NAMES — the console half of the rule
 * `tests/plain_language_guard_test.py` states one tier down.
 *
 * That file guards the API's problem+json (`title` / `detail` / `remediation`) and says
 * in its own header that "the console's own copy is not read … the console has its own
 * sweep". This is that sweep. It exists now because the motion changed underneath the
 * copy: with prepaid the default an account gets, `no_credits` went from a rule almost no
 * client could meet to the most likely reason a campaign of theirs will not start, and the
 * words around it are read by a clinic owner on a phone rather than by anyone who has ever
 * seen the wire.
 *
 * ═══ WHAT IT READS ══════════════════════════════════════════════════════════════════
 *
 * ⚠ The WALK is `tests/copyScan.ts` now — it moved the day a second guard needed the
 * same answer, and the rules below still describe exactly what it takes and skips.
 *
 * Only the client realm (`src/app/c/[slug]`), and inside it only text that reaches a
 * person:
 *
 *  - JSX text — the words between the tags;
 *  - a string in a JSX child expression, including `"…" + "…"` concatenations, which is
 *    how every long sentence in this console is written;
 *  - the value of an object property whose NAME is one a screen renders (`label`, `text`,
 *    `hint`, …) — the shape `BLOCKER_COPY`, `HOLD_RULES` and every other copy table uses;
 *  - the four JSX attributes that are read out loud or shown in a tooltip.
 *
 * Deliberately NOT read, each for a reason:
 *
 *  - **`value:` and every object KEY.** Those are the wire's own vocabulary and SHOULD be
 *    machine-spelled: `{ value: "purchased_list" }` is a form option's stored answer, and
 *    a guard that flagged it would be asking the console to lie to the API.
 *  - **Comparisons.** `{state !== "never_applied" && …}` contains a wire name and renders
 *    nothing; only `+` concatenation is followed into a child expression.
 *  - **`className`, `href`, `id`, query keys, paths.** Not copy.
 *  - **The admin realm.** Operators are supposed to read `spend_cap` and
 *    `pe_registration_not_active`: those are the names they will quote to each other and
 *    grep the logs for. `lib/api/clientHealth.ts` says so where it words them.
 *
 * ═══ WHAT IT BANS ═══════════════════════════════════════════════════════════════════
 *
 * A wire identifier: `snake_case`, the spelling every rule, status, reason and column in
 * this system carries. That is the whole check, and it is narrow ON PURPOSE — the backend
 * guard's own header says a guard that flags legitimate prose is a guard somebody turns
 * off within the week, and English words a client legitimately needs ("endpoint",
 * "webhook", "spreadsheet column") are not banned here any more than they are there.
 *
 * ═══ THE TWO SCREENS THAT ARE EXEMPT ════════════════════════════════════════════════
 *
 * `EXEMPT` is not an amnesty for unswept copy; it is two screens whose reader is
 * demonstrably wiring something, where the identifier IS the subject and a friendlier word
 * would be less accurate:
 *
 *  - `agents/actions` — the client names the action their agent can call, and the field is
 *    labelled "Name (snake_case)" because that is what the engine accepts;
 *  - `lead-sources` — the placeholders are the column headings of the client's own form or
 *    spreadsheet (`phone_number`, `full_name`), quoted so they can be matched by eye.
 *
 * `integrations` is deliberately NOT on this list even though it is the same kind of
 * screen: it turned out to need no exemption, and an exemption nobody needs is a hole
 * somebody's sentence falls through later. Each entry is a PATH, so a new sentence anywhere else in the realm is caught on the day it is
 * written. If one of these screens is ever reworded away from identifiers, delete its line
 * — the list may shrink and may never grow without an argument beside it.
 */

/** The client realm, and the screens whose reader is wiring something (see the header). */
const CLIENT_REALM = ["src/app/c"];
const EXEMPT = ["src/app/c/[slug]/agents/actions", "src/app/c/[slug]/lead-sources"];

/** A wire identifier: two or more lowercase words joined by underscores. */
const WIRE_NAME = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

/**
 * ⚠ THE WALK ITSELF NOW LIVES IN `tests/copyScan.ts`, and this file is the RULE over it.
 * It moved the day a second guard needed the same answer ("what does a person actually see
 * on this screen?"): a copy of ninety lines of AST walking is the shape `sourceScan.ts`
 * already exists to refuse one level down. What is guarded here is unchanged.
 */
function findings(): string[] {
  const out: string[] = [];
  for (const entry of copyUnder(CLIENT_REALM, EXEMPT)) {
    WIRE_NAME.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = WIRE_NAME.exec(entry.text)) !== null) {
      out.push(
        `${entry.file}:${entry.line} — \u201c${match[0]}\u201d in: ${entry.text.trim().slice(0, 120)}`,
      );
    }
  }
  return out;
}

describe("what a client reads is written for a person", () => {
  it("finds the copy it is supposed to be reading", () => {
    // THE PREMISE, first and alone. Every assertion below is worthless if the walk has
    // silently stopped matching — a moved route group, a renamed helper, an AST shape this
    // no longer recognises — and a scan that finds nothing would pass forever.
    const seen = copyUnder(CLIENT_REALM).map((entry) => entry.text);
    expect(seen.length, "the copy scan found almost nothing — has the realm moved?")
      .toBeGreaterThan(500);
    // Three sentences from three different screens, in three different shapes: JSX text,
    // a `+`-joined string in a child expression, and a copy table's `text:`.
    const all = seen.join("\n");
    expect(all).toContain("People calling you still get through");
    expect(all).toContain("Your calling credit has run out");
    expect(all).toContain("nobody on them agreed to hear from you");
  });

  it("never shows a client one of our rule names", () => {
    expect(
      findings(),
      "these are wire identifiers in copy a CLIENT reads. A rule name is how the platform " +
        "talks to itself; a person who sees one has been handed our vocabulary instead of " +
        "an answer. Write the sentence in their words — say what happened, what still " +
        "works, and what to do — and keep the identifier in the key, where the compliance " +
        "gate can still be keyed to it.",
    ).toEqual([]);
  });
});
