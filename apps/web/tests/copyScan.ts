import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

/**
 * THE ONE READER OF "WHAT DOES A PERSON ACTUALLY SEE ON THIS SCREEN?"
 *
 * ## Why it is a shared module rather than a second copy
 *
 * `plainLanguageGuard.test.ts` built this walk to answer one question — does a client ever
 * read one of our wire identifiers? — and the answer needed an AST rather than a grep,
 * because a `grep` over source cannot tell `{ value: "purchased_list" }` (the answer sent
 * back to the API, and correct) from `{ label: "purchased_list" }` (our vocabulary handed
 * to a clinic owner). `tests/sourceScan.ts` exists because the same lesson was learned
 * three times with comments; this is that lesson one level up, and the moment it was
 * learned again was the second guard needing the same walk.
 *
 * So the walk lives here and the guards live in their own files. A guard is then a set of
 * roots and a rule about the text — which is all a guard should be, and it is what stops
 * the next one from being a grep that reports a docstring as a defect.
 *
 * ## What counts as copy, and what deliberately does not
 *
 * Taken:
 *
 *  - JSX text — the words between the tags;
 *  - a string in a JSX child expression, including the `"…" + "…"` chains every long
 *    sentence in this app is written as, and the literal parts of a template;
 *  - the value of an object property whose NAME is one a screen renders (`label`, `hint`,
 *    `detail`, …) — the shape every copy table here uses;
 *  - the four JSX attributes that are read aloud or shown on hover.
 *
 * Not taken, each for a reason:
 *
 *  - **`value:` and every object KEY.** Those are the wire's own vocabulary and SHOULD be
 *    machine-spelled; flagging them would be asking a screen to lie to the API.
 *  - **Comparisons and other expressions.** `{state !== "no_credits" && …}` contains a
 *    wire name and renders nothing. Only `+` chains and templates are followed.
 *  - **`className`, `href`, `id`, paths, query keys.** Not copy.
 *  - **Comments.** Nothing here reads them: an AST literal cannot be a docstring, which is
 *    the whole reason this is a parse and not a regex.
 */

/** The `apps/web` directory, so a finding can be reported as a repo-relative path. */
export const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * Object properties a screen RENDERS. `value` is absent on purpose — it carries the answer
 * that goes back to the API, not the words beside it.
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
  // `caption` and `legend` are the ROI calculator's own copy-table keys — the two words a
  // buyer reads beside every priced option. They were absent while this walk only read the
  // client realm, which has neither; a marketing guard that skipped them would have been
  // blind to the one table on the site where a name and a price sit together.
  "caption",
  "legend",
  "claim",
  "term",
  "q",
  "a",
]);

/** JSX attributes that are read out loud or shown to the eye. */
const COPY_ATTRS = new Set(["aria-label", "aria-description", "title", "placeholder", "alt"]);

/** One rendered string, and where to go and look at it. */
export interface CopyString {
  /** Path relative to `apps/web`, so a failure message is something to open. */
  readonly file: string;
  readonly line: number;
  readonly text: string;
}

/** Every `.ts`/`.tsx` under a directory, or the file itself when handed one. */
export function tsSources(target: string): string[] {
  const found: string[] = [];
  const walk = (path: string): void => {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      const child = join(path, entry.name);
      if (entry.isDirectory()) walk(child);
      else if (child.endsWith(".tsx") || child.endsWith(".ts")) found.push(child);
    }
  };
  if (target.endsWith(".tsx") || target.endsWith(".ts")) return [target];
  walk(target);
  return found;
}

/** A literal, or the literals of a `+` chain or a template. Nothing else is followed. */
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

/** Every string one file puts in front of a person. */
export function copyIn(file: string): CopyString[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const relative = file.startsWith(WEB_ROOT) ? file.slice(WEB_ROOT.length + 1) : file;
  const found: CopyString[] = [];
  const take = (node: ts.Node, text: string): void => {
    if (!text.trim()) return;
    found.push({
      file: relative,
      line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1,
      text,
    });
  };

  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) take(node, node.text);

    // A string in a JSX child position — `{"…" + "…"}`. An expression in an ATTRIBUTE is
    // handled below.
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
  return found;
}

/** Every rendered string under a set of roots, with the exempt prefixes dropped. */
export function copyUnder(roots: readonly string[], exempt: readonly string[] = []): CopyString[] {
  const out: CopyString[] = [];
  for (const root of roots) {
    for (const file of tsSources(join(WEB_ROOT, root))) {
      const relative = file.slice(WEB_ROOT.length + 1);
      if (exempt.some((prefix) => relative.startsWith(prefix))) continue;
      out.push(...copyIn(file));
    }
  }
  return out;
}
