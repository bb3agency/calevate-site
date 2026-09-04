import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";
import { blankComments } from "./sourceScan";

/**
 * SENTENCES MUST READ AS SENTENCES — the flex-item defect, pinned so it cannot come back.
 *
 * ## The defect
 *
 * A flex (or grid) container lays out EVERY child as its own item, and a bare text node is
 * a child. So this, which looks like one paragraph with a link in it:
 *
 * ```tsx
 * <li className="flex gap-2">
 *   <Icon />
 *   What you are billed is on the{" "}
 *   <Link href={...}>Usage tab of Credits &amp; billing</Link>
 *   .
 * </li>
 * ```
 *
 * is FOUR flex items: the icon, the run of text, the link, and the full stop. The link
 * gets `gap-2` on both sides of it and is laid out as a ragged column of its own rather
 * than flowing in the line. The founder screenshotted exactly that on the AI-model screen:
 * "Usage tab of Credits & billing" in a column, "Agents" adrift mid-line with a gap either
 * side. Nothing errors, no test fails, and the text simply reads as broken.
 *
 * The fix is structural, not stylistic: give the flex row exactly two children — the icon,
 * and one `<span>`/`<p>` wrapping the whole sentence including its links — after which the
 * link is inline text again and `gap-2` does the one job it was written for.
 *
 * ## Why this is an AST rule and not a regex
 *
 * A regex over JSX cannot tell a legitimate flex row from a broken one, and the difference
 * is not in the characters — it is in which nodes are CHILDREN of the flex box:
 *
 *   - `<button className="flex gap-2"><Save />Save model</button>` — icon plus a label. Two
 *     items, one gap, entirely correct, and by far the most common shape in this console.
 *   - `<div className="flex gap-2"><Link>a</Link><Link>b</Link></div>` — a row of buttons.
 *     Also correct: there is no sentence to break.
 *   - `<span className="flex gap-1"><Dot />Live</span>` — a badge. Correct.
 *
 * All three contain the strings a text search would key on. What separates them from the
 * defect is that in the defect a run of PROSE is followed, inside the same flex box, by an
 * element that belongs to that prose. That is a question about the child list, so the guard
 * asks the parser instead of guessing, and the brief's fallback rule ("no `<Link>` as a
 * direct child of a `flex` element") is deliberately NOT what is enforced — it fires on
 * every button row in the tree, and a guard people learn to disbelieve is worse than none.
 *
 * ## What it catches, and what it does not
 *
 * CATCHES: any element declaring a flex/grid display box (including responsive variants
 * like `md:flex`, and class lists built inside a template literal or a `clsx()` call, since
 * those spellings are read as raw text) whose children include a run of prose followed by
 * an inline, sentence-level element — `Link`, `a`, `strong`, `em`, `code`, `span`, and the
 * rest of INLINE below.
 *
 * DOES NOT CATCH, stated rather than implied:
 *   - A className that is a bare identifier (`className={FIELD_HINT}`), where the class list
 *     lives in another binding. No such constant in this tree declares a display class today
 *     — that was checked, not assumed — but a future one would be invisible here.
 *   - A sentence split across flex items where the second half is an EXPRESSION rather than
 *     an element (`{name}`), which is a legitimate shape (icon + interpolated label) far more
 *     often than it is a defect.
 *   - The reverse mistake, `flex` on a link that sits INSIDE prose, which turns the link into
 *     a block and breaks the line. Every flexed link in this tree is `inline-flex` — an
 *     atomic inline that flows correctly — or stands alone as a nav row or button, so there
 *     is nothing to pin and a rule against it would only guess at intent. It is written down
 *     here so the next reader knows it was looked at.
 *   - Anything a browser would have measured. This is a structural tripwire, not a layout
 *     proof; `responsive.test.ts` explains at length why the browser is the instrument and
 *     the rules are what is kept.
 *
 * Comments cannot defeat it and cannot trip it: the source is parsed with every comment line
 * blanked (`sourceScan.blankComments`, which keeps the line count so the reported line number
 * is still the real one), and a JSX comment is not a child node in the first place.
 */

const SRC = join(process.cwd(), "src");

/** A Tailwind token that makes the element a flex/grid CONTAINER. */
const DISPLAY = /^(?:[a-z0-9-]+:)*(?:inline-)?(?:flex|grid)$/;

/**
 * Sentence-level elements — the ones whose appearance mid-paragraph means the prose was
 * split. Block containers (`div`, `p`, `li`, `ul`, `section`) are absent on purpose: a flex
 * container holding text and a block sibling is a different shape with a different fix.
 */
const INLINE = new Set([
  "Link",
  "a",
  "abbr",
  "b",
  "code",
  "em",
  "i",
  "kbd",
  "mark",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "u",
]);

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx")) out.push(full);
    }
  };
  walk(SRC);
  return out;
}

type Opening = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

function opening(node: ts.JsxElement | ts.JsxSelfClosingElement): Opening {
  return ts.isJsxElement(node) ? node.openingElement : node;
}

function tagOf(node: ts.JsxElement | ts.JsxSelfClosingElement): string {
  return opening(node).tagName.getText();
}

/**
 * The className as TEXT. A string literal gives its value; any expression gives its raw
 * source, which is what makes a template literal or a `clsx("flex", ...)` call readable
 * without evaluating anything. An expression that names no class at all simply matches
 * nothing, which is the safe direction for a tripwire.
 */
function classNameOf(node: ts.JsxElement | ts.JsxSelfClosingElement): string {
  for (const attr of opening(node).attributes.properties) {
    if (!ts.isJsxAttribute(attr) || attr.name.getText() !== "className") continue;
    const init = attr.initializer;
    if (!init) return "";
    return ts.isStringLiteral(init) ? init.text : init.getText();
  }
  return "";
}

function isFlexContainer(className: string): boolean {
  return className.split(/[\s"'`{}()+,]+/).some((token) => DISPLAY.test(token));
}

type Child = { kind: "text" | "element" | "expression"; tag: string };

/** The children a flex box actually lays out as ITEMS: whitespace and comments are neither. */
function layoutChildren(node: ts.JsxElement): Child[] {
  const out: Child[] = [];
  for (const child of node.children) {
    if (ts.isJsxText(child)) {
      if (child.text.trim()) out.push({ kind: "text", tag: "" });
    } else if (ts.isJsxElement(child) || ts.isJsxSelfClosingElement(child)) {
      out.push({ kind: "element", tag: tagOf(child) });
    } else if (ts.isJsxExpression(child)) {
      const inner = child.expression;
      // `{/* comment */}` has no expression; `{" "}` is a spacer, not an item.
      if (!inner) continue;
      if (ts.isStringLiteral(inner) && !inner.text.trim()) continue;
      out.push({ kind: "expression", tag: "" });
    }
  }
  return out;
}

type Finding = { where: string; tag: string; split: string };

const findings: Finding[] = [];
let filesScanned = 0;
let containersInspected = 0;
/** Containers that hold an inline element at all — the classifier's own liveness check. */
let containersWithInlineChild = 0;

for (const file of sourceFiles()) {
  filesScanned += 1;
  const source = blankComments(readFileSync(file, "utf8").split("\n")).join("\n");
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

  const visit = (node: ts.Node): void => {
    if (ts.isJsxElement(node) && isFlexContainer(classNameOf(node))) {
      containersInspected += 1;
      const kids = layoutChildren(node);
      if (kids.some((k) => k.kind === "element" && INLINE.has(k.tag))) {
        containersWithInlineChild += 1;
      }
      const firstText = kids.findIndex((k) => k.kind === "text");
      const split =
        firstText === -1
          ? undefined
          : kids.slice(firstText + 1).find((k) => k.kind === "element" && INLINE.has(k.tag));
      if (split) {
        const line = sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
        findings.push({
          where: `${relPosix(process.cwd(), file)}:${line}`,
          tag: tagOf(node),
          split: split.tag,
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
}

describe("prose inside a flex container", () => {
  it("is scanning a real tree — the floors that stop a silent no-op passing", () => {
    // Every one of these was well above its floor when written (203 files, 1163 containers,
    // 178 of them holding an inline element). The floors are deliberately far below that:
    // they are here to catch a scan that stopped matching — a wrong cwd, a parser that no
    // longer reads this dialect, a className shape the reader stopped recognising — not to
    // pin a count that legitimate work moves.
    expect(filesScanned).toBeGreaterThan(120);
    expect(containersInspected).toBeGreaterThan(600);
    expect(containersWithInlineChild).toBeGreaterThan(60);
  });

  it("never splits a sentence across flex items", () => {
    const report = findings.map((f) => `  ${f.where}  <${f.tag}> … <${f.split}>`).join("\n");
    expect(
      findings,
      findings.length === 0
        ? ""
        : `A flex/grid container holds loose sentence text AND an inline element, so the ` +
            `element is laid out as its own flex ITEM with the container's gap on both ` +
            `sides of it instead of flowing in the line.\n\n${report}\n\n` +
            `Fix: give the container exactly two children — the icon, and ONE <span> ` +
            `wrapping the whole sentence including its links.`,
    ).toEqual([]);
  });
});
