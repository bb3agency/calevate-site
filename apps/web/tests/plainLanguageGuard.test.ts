import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

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

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CLIENT_REALM = join(WEB_ROOT, "src/app/c");

/** Screens whose reader is wiring something; see the header. Paths, not files. */
const EXEMPT = [
  "src/app/c/[slug]/agents/actions",
  "src/app/c/[slug]/lead-sources",
];

/**
 * Object properties a screen RENDERS. `value` is absent on purpose — it carries the
 * answer that goes back to the API, not the words beside it.
 */
const COPY_KEYS = new Set([
  "label",
  "title",
  "hint",
  "text",
  "body",
  "detail",
  "message",
  "reason",
  "meaning",
  "cta",
  "badge",
  "action",
  "note",
  "summary",
  "description",
  "help",
  "placeholder",
  "heading",
]);

/** JSX attributes that are read out loud or shown to the eye. */
const COPY_ATTRS = new Set([
  "aria-label",
  "aria-description",
  "title",
  "placeholder",
  "alt",
]);

/** A wire identifier: two or more lowercase words joined by underscores. */
const WIRE_NAME = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g;

type Finding = { file: string; line: number; name: string; text: string };

function tsxFiles(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) found.push(...tsxFiles(path));
    else if (path.endsWith(".tsx") || path.endsWith(".ts")) found.push(path);
  }
  return found;
}

/** A literal, or the literals of a `+` chain of them. Nothing else is followed. */
function literals(node: ts.Expression): ts.Node[] {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [node];
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    return [...literals(node.left), ...literals(node.right)];
  }
  if (ts.isTemplateExpression(node)) {
    return [node.head, ...node.templateSpans.map((span) => span.literal)];
  }
  return [];
}

function copyIn(file: string): { node: ts.Node; text: string }[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const found: { node: ts.Node; text: string }[] = [];
  const take = (node: ts.Node, text: string): void => {
    if (text.trim()) found.push({ node, text });
  };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) take(node, node.text);

    // A string in a JSX child position — `{"…" + "…"}`, the shape every long sentence in
    // this console is written in. An expression in an ATTRIBUTE is handled below.
    if (
      ts.isJsxExpression(node) &&
      node.expression &&
      node.parent &&
      (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))
    ) {
      for (const literal of literals(node.expression)) {
        take(literal, (literal as ts.LiteralLikeNode).text);
      }
    }

    if (
      ts.isPropertyAssignment(node) &&
      (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
      COPY_KEYS.has(node.name.text)
    ) {
      for (const literal of literals(node.initializer)) {
        take(literal, (literal as ts.LiteralLikeNode).text);
      }
    }

    if (ts.isJsxAttribute(node) && COPY_ATTRS.has(node.name.getText()) && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) take(node.initializer, node.initializer.text);
      else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
        for (const literal of literals(node.initializer.expression)) {
          take(literal, (literal as ts.LiteralLikeNode).text);
        }
      }
    }

    ts.forEachChild(node, visit);
  };
  visit(source);

  return found.map((entry) => ({
    ...entry,
    line: source.getLineAndCharacterOfPosition(entry.node.getStart()).line + 1,
  })) as { node: ts.Node; text: string }[];
}

function findings(): Finding[] {
  const out: Finding[] = [];
  for (const file of tsxFiles(CLIENT_REALM)) {
    const relative = file.slice(WEB_ROOT.length + 1);
    if (EXEMPT.some((prefix) => relative.startsWith(prefix))) continue;
    for (const entry of copyIn(file)) {
      WIRE_NAME.lastIndex = 0;
      let match: RegExpExecArray | null;
      while ((match = WIRE_NAME.exec(entry.text)) !== null) {
        out.push({
          file: relative,
          // `copyIn` attaches it; the cast keeps the helper's return honest.
          line: (entry as unknown as { line: number }).line,
          name: match[0],
          text: entry.text.trim().slice(0, 120),
        });
      }
    }
  }
  return out;
}

describe("what a client reads is written for a person", () => {
  it("finds the copy it is supposed to be reading", () => {
    // THE PREMISE, first and alone. Every assertion below is worthless if the walk has
    // silently stopped matching — a moved route group, a renamed helper, an AST shape this
    // no longer recognises — and a scan that finds nothing would pass forever.
    const seen = tsxFiles(CLIENT_REALM).flatMap((file) => copyIn(file).map((c) => c.text));
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
      findings().map((f) => `${f.file}:${f.line} — “${f.name}” in: ${f.text}`),
      "these are wire identifiers in copy a CLIENT reads. A rule name is how the platform " +
        "talks to itself; a person who sees one has been handed our vocabulary instead of " +
        "an answer. Write the sentence in their words — say what happened, what still " +
        "works, and what to do — and keep the identifier in the key, where the compliance " +
        "gate can still be keyed to it.",
    ).toEqual([]);
  });
});
