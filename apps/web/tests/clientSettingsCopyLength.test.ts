import { readFileSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { WEB_ROOT, copyIn, tsSources, type CopyString } from "./copyScan";

/**
 * BUTTONS, NOT PARAGRAPHS — the client Settings, Phone number and Verify your business
 * screens show no line of default copy longer than about 60 characters.
 *
 * Our clients read these screens on a phone, often in their second language; a setting is
 * a short label, its control and at most a one-line hint, and the explanation sits behind
 * a tap. This walks the source with `copyScan` (the one reader of "what does a person see")
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
const MAX = 60;

/** Files that are not screen copy: the assistant's declaration of the screen. */
const SKIP_FILES = ["src/app/c/[slug]/verify-business/copilot.ts"];

/**
 * Components that only ever render behind a tap: the "About verification" accordion's
 * panels and the campaign-registration details, which mount inside a closed disclosure.
 */
const TAP_ONLY_COMPONENTS = new Set([
  "WhatWeKeep",
  "WhatItAffects",
  "Affected",
  "PhoneNumbers",
  "OnFile",
  "DltStatuses",
  "CalevateTelemarketerId",
  "DltOnFile",
]);

/** Elements whose CHILDREN are shown only after a tap. Their own props still count. */
const TAP_ONLY_ELEMENTS = new Set(["InfoTip", "Disclosure", "ConfirmDialog", "Popover"]);

/** Props that are explanations behind an ⓘ, never shown by default. */
const TAP_ONLY_PROPS = new Set(["info", "infoLabel", "aria-label", "why"]);

/** Constants rendered only inside an ⓘ. */
const TAP_ONLY_CONSTANTS = new Set(["OWNER_SENTENCE"]);

/**
 * A Tailwind class list caught by the wide walk (a `className` ternary is not followed by
 * its attribute filter): lower-case tokens, at least one with a `-` or a `:`.
 */
function isClassList(text: string): boolean {
  const tokens = text.trim().split(/\s+/);
  return (
    tokens.every((token) => /^[a-z0-9:\-[\]/.()&*>%#=_!]+$/.test(token)) &&
    tokens.some((token) => token.includes("-") || token.includes(":"))
  );
}

/**
 * Kept verbatim and in view on purpose: the words a person ticks to accept the
 * no-cold-calls pledge on the business's behalf. It is a legal declaration (D-692), so it
 * is not shortened to fit a guard.
 */
const KEPT_VERBATIM = new Set([
  "I have read the pledge and the disclosure, and accept them on behalf of the business.",
]);

type Range = { from: number; to: number };

/** The line ranges of a file that are shown only after a tap. */
function tapOnlyLines(file: string): Range[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const line = (pos: number) => source.getLineAndCharacterOfPosition(pos).line + 1;
  const ranges: Range[] = [];
  const add = (node: ts.Node) => ranges.push({ from: line(node.getStart()), to: line(node.getEnd()) });
  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node) && TAP_ONLY_ELEMENTS.has(node.openingElement.tagName.getText())) {
      for (const child of node.children) add(child);
    }
    if (ts.isJsxAttribute(node) && TAP_ONLY_PROPS.has(node.name.getText())) add(node);
    if (ts.isCallExpression(node) && node.expression.getText() === "useCopilotSurface") add(node);
    if (ts.isFunctionDeclaration(node) && node.name && TAP_ONLY_COMPONENTS.has(node.name.text)) add(node);
    if (ts.isVariableDeclaration(node) && TAP_ONLY_CONSTANTS.has(node.name.getText())) add(node);
    ts.forEachChild(node, visit);
  };
  visit(source);
  return ranges;
}

function defaultCopy(): CopyString[] {
  const out: CopyString[] = [];
  for (const root of ROOTS) {
    for (const file of tsSources(join(WEB_ROOT, root))) {
      const found = copyIn(file, { wide: true });
      if (found.length === 0 || SKIP_FILES.includes(found[0].file)) continue;
      const hidden = tapOnlyLines(file);
      out.push(...found.filter((copy) => !hidden.some((r) => copy.line >= r.from && copy.line <= r.to)));
    }
  }
  return out;
}

const collapse = (text: string) => text.replace(/\s+/g, " ").trim();

describe("client settings, phone number and verification screens: buttons, not paragraphs", () => {
  const copy = defaultCopy();

  it("reads copy from every screen it guards", () => {
    // A walk that found nothing would pass for the wrong reason.
    for (const root of ROOTS) {
      expect(copy.some((c) => c.file.startsWith(root)), root).toBe(true);
    }
  });

  it(`shows no default line longer than ${MAX} characters`, () => {
    const long = copy
      .map((c) => ({ ...c, text: collapse(c.text) }))
      .filter((c) => c.text.length > MAX && !KEPT_VERBATIM.has(c.text) && !isClassList(c.text))
      .map((c) => `${c.file}:${c.line} (${c.text.length}) ${c.text}`);
    expect(long).toEqual([]);
  });
});
