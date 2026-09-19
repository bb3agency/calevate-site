import { describe, expect, it } from "vitest";

import { copyUnder } from "./copyScan";

/**
 * WHO CHANGES AN AGENT'S VOICE, ASSERTED OVER EVERY SENTENCE THAT ANSWERS THE QUESTION.
 *
 * ## The defect
 *
 * Three client-facing surfaces told a paying client that changing an agent's voice was
 * ours to do and that they should ask a person for it:
 *
 *   - `src/app/pricing/page.tsx` — "tell your account manager which voice each agent
 *     should speak with", on the PUBLIC pricing page;
 *   - `src/app/c/[slug]/billing/WhatCallsCost.tsx` — "Tell your account manager which
 *     voice you want an agent to speak with and we set it";
 *   - `src/app/c/[slug]/billing/TopUp.tsx` — the same sentence, in the same register, on
 *     the Credits tab.
 *
 * Each cited D-21 and each was written against it. **D-586 (11 Sep 2026) supersedes D-21
 * for the `live` lane of `agents/publishing.LANES`**: `PATCH /v1/agents/{agent_id}/voice`
 * is a CLIENT-realm door with no tenant in it, `agents:write` joined
 * `ROLE_PERMISSIONS["owner"]` and `["staff"]`, and the write re-publishes a live agent in
 * the same transaction. The picker that drives it is mounted at
 * `src/app/c/[slug]/agents/panels/delivery.tsx:165`, inside the card "How it sounds, and
 * how long a call may run" (`AgentWorkspace.tsx:221`) on the client's own agent screen.
 *
 * D-586 shipped with a closing note — "the client console has no picker or cap field on
 * these two doors yet" — and that note is the state all three sentences described. It has
 * since been closed, and the copy did not move with it.
 *
 * ## Why a copy scan rather than three screen tests
 *
 * The three sentences were three copies of ONE fact, which is the defect this repo names
 * in its own words ("two wordings of one rule is how a client comes to believe the more
 * generous one" — `TopUp.tsx`). A per-screen test pins the screen it was written for and
 * says nothing about the fourth copy somebody adds next week, and the register is
 * contagious: two of the three were written by copying the first. So the guard is over
 * the SHAPE, across every client-facing root at once.
 *
 * `copyUnder` is an AST walk over what a person actually reads (`tests/copyScan.ts`) and
 * not a grep, which matters here more than usual: the corrected files each carry a long
 * comment explaining the old sentence and quoting it verbatim, and a grep would report
 * every one of those corrections as the defect it documents.
 *
 * ## What is banned, and what is emphatically not
 *
 * Only the conjunction of the two: a sentence about a VOICE that routes the reader to a
 * PERSON. "Ask your account manager" is correct and common elsewhere in this console —
 * DLT registration, phone numbers, invoiced plans and knowledge review are all genuinely
 * ours — so the account-manager register itself is untouched. What may not return is
 * pointing a client at a person for the one control D-586 handed them.
 */

/** Every root a CLIENT or a buyer reads. The admin console is deliberately absent. */
const CLIENT_FACING = [
  "src/app/c",
  "src/app/pricing",
  "src/app/roi",
  "src/app/page.tsx",
  "src/app/why-calevate",
  "src/app/solutions",
  "src/app/industries",
  "src/app/resources",
  "src/app/security",
  "src/components/marketing",
  "src/lib/marketing",
];

/** Somebody at Calevate, in every spelling these surfaces use for one. */
const A_PERSON =
  /account manager|talk to us|ask us|contact us|we set it|we will set/i;

/** The subject, word-bounded so "invoice" and "voicemail" are not voices. */
const A_VOICE = /\bvoices?\b/i;

/**
 * ⚠ **THE FIRST VERSION OF THIS GUARD TESTED EACH LITERAL ON ITS OWN, AND A FIFTH COPY OF
 * THE DEFECT WALKED STRAIGHT THROUGH IT.**
 *
 * `copyIn` yields one `CopyString` per string literal, and every long sentence in this app
 * is written as a `"…" + "…"` chain. `/resources`' glossary entry split exactly across the
 * seam:
 *
 *     "…It is set " +
 *     "per agent rather than for the whole account, and we set it: tell your account " +
 *     "manager which one an agent should use…"
 *
 * The segment holding "voices" carried no "account manager" and the segment holding
 * "account manager" carried no "voice", so a per-literal filter saw neither. The sentence a
 * person reads is the chain, so the guard has to read the chain.
 *
 * Reassembled by PROXIMITY rather than by re-walking the AST for chain identity: a `+`
 * chain's literals are consecutive lines of one file, so entries in the same file within
 * `GAP` lines of each other are joined. That over-joins slightly — two adjacent short
 * sentences become one window — and over-joining is the safe direction here, because this
 * guard bans a conjunction and a false positive is a sentence somebody reads and rewords.
 */
const GAP = 3;

interface Sentence {
  readonly file: string;
  readonly line: number;
  readonly text: string;
}

function sentences(roots: readonly string[]): Sentence[] {
  const out: Sentence[] = [];
  // ⚠ THE GAP IS MEASURED FROM THE LINE JUST APPENDED, NOT FROM THE GROUP'S FIRST LINE,
  // AND MEASURING IT FROM THE FIRST LINE IS A BUG THIS GUARD SHIPPED WITH FOR ONE
  // ITERATION. A group that starts at 233 and grows to 240 is still one chain, but
  // `240 - 233 > GAP` closed it at 237 — splitting the `/resources` sentence into a half
  // holding "voices" and a half holding "account manager", which is precisely the split
  // the reassembly exists to undo. It passed a green suite over the live defect.
  let lastLine = -Infinity;
  let lastFile = "";
  for (const entry of [...copyUnder(roots)].sort((a, b) =>
    a.file === b.file ? a.line - b.line : a.file.localeCompare(b.file),
  )) {
    const text = entry.text.replace(/\s+/g, " ");
    const previous = out.at(-1);
    if (
      previous !== undefined &&
      lastFile === entry.file &&
      entry.line - lastLine <= GAP
    ) {
      out[out.length - 1] = { ...previous, text: `${previous.text}${text}` };
    } else {
      out.push({ file: entry.file, line: entry.line, text });
    }
    lastLine = entry.line;
    lastFile = entry.file;
  }
  return out;
}

function report(entry: Sentence): string {
  return `${entry.file}:${entry.line} — ${entry.text.trim().slice(0, 200)}`;
}

describe("changing an agent's voice is the client's own control (D-586)", () => {
  it("is reading the surfaces it claims to read", () => {
    // THE PREMISE, FIRST AND ALONE — `publicVendorNames` and `plainLanguageGuard` both
    // open this way, for the reason both state: a walk that has silently stopped matching
    // finds nothing and passes for ever, and a guard that cannot fail is worse than none.
    // Two sentences from two DIFFERENT roots, so one root dropping out of the list is
    // caught here rather than by a green suite.
    const seen = sentences(CLIENT_FACING);
    expect(
      seen.length,
      "the copy scan found almost nothing — have the roots moved?",
    ).toBeGreaterThan(400);
    const all = seen.map((entry) => entry.text).join("\n");
    // Three sentences from THREE different roots, so one root dropping out of the list is
    // caught here rather than by a green suite.
    // `src/app/c` — the client console's own billing explainer.
    expect(all).toContain("The voice belongs to the agent, not to the account");
    // `src/app/pricing` — the public page.
    expect(all).toContain(
      "A voice is set per agent rather than for the whole account",
    );
    // `src/app/resources` — the glossary, and the proof the `+` chains are REASSEMBLED:
    // this substring spans a literal boundary and no per-literal scan can see it.
    expect(all).toContain(
      "It is set per agent rather than for the whole account, and you choose it",
    );
  });

  it("never sends a client to a person to change a voice", () => {
    const found = sentences(CLIENT_FACING)
      .filter((entry) => A_VOICE.test(entry.text) && A_PERSON.test(entry.text))
      .map(report);
    expect(
      found,
      "D-586 (11 Sep 2026) supersedes D-21 for the `live` lane: an agent's voice is the " +
        "ACCOUNT's to change. `PATCH /v1/agents/{agent_id}/voice` is a client-realm door, " +
        "`agents:write` is on `owner` and `staff`, and the picker is mounted on the " +
        "client's own agent screen (`app/c/[slug]/agents/panels/delivery.tsx:165`, the " +
        'card "How it sounds, and how long a call may run"). A sentence telling a client ' +
        "to ask a person for it sends a paying owner to a support queue for a control two " +
        "clicks away — and on `/pricing` it sells a self-serve product as a managed one. " +
        "Say where the control is, not who to ask for it.",
    ).toEqual([]);
  });

  it("still says the voice is per agent, which is the half that is true", () => {
    // THE CORRECTION HAS A DIRECTION, AND THE OTHER DITCH IS REAL. The per-agent fact is
    // load-bearing — it is why the rate card prices one voice at a time and why a month is
    // priced from the voice each call actually used — so a rewrite that dropped it while
    // removing the account manager would be the same defect pointing the other way.
    // Whitespace-normalised, because JSX text wraps: the pricing sentence reaches the
    // scan as "…and you choose it\n                yourself on each agent's own screen",
    // and a raw match would fail on correct copy the moment Prettier re-flowed the line.
    const all = sentences(CLIENT_FACING)
      .map((entry) => entry.text)
      .join("\n");
    expect(all).toMatch(/set per agent/i);
    expect(all).toMatch(/you choose it yourself/i);
  });
});
