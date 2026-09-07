import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * MONEY AND TIME ARE SPELLED ONCE, IN `components/ui.tsx`, AND NOWHERE ELSE.
 *
 * `ui.tsx` owns `formatINR`, `formatRupeeRate`, `formatIST`, `formatISTInput`,
 * `istInputToInstant`, `istDateStamp` and `istDateToInstant`, and each of them carries a
 * long docstring explaining a defect that had already shipped. The defects kept coming
 * back anyway — not by anyone rejecting the argument, but by a screen writing `₹{value}`
 * or `getTimezoneOffset()` without knowing the helper existed. Four instances were found
 * in one sweep (an invoice line, a rate on `/admin/spend`, two on commercial terms) plus
 * two browser-zone round trips, one of them on the control that SHEDS LIVE PLATFORM
 * TRAFFIC (`admin/ops/maintenance`), where an hour of drift schedules an outage at the
 * wrong time.
 *
 * Fixing six instances leaves the seventh writable. This makes the CLASS unwriteable,
 * which is the technique this suite already uses for four other rules
 * (`surfaceStatesGuard`, `responsive`, `contrast`, `plainLanguageGuard`).
 *
 * ═══ THE THREE RULES ════════════════════════════════════════════════════════════════
 *
 * 1. **A rupee sign may not be glued to a bare value.** `₹{item.unit_inr}` prints the
 *    wire's own decimal — `₹7.125` on one line beside `₹7,125.00` on the next, and
 *    `₹1015900.00` ungrouped where a client is checking an invoice against their books.
 *    The interpolation must be a CALL, which is the syntactic shape of "these digits went
 *    through a formatter" — `formatINR` for a total, `formatRupeeRate` for an unrounded
 *    rate (`ui.tsx:1241,1269`). It reads the JSX and the template literals, so both
 *    spellings of the same mistake are caught.
 *
 * 2. **`getTimezoneOffset` is banned outright.** Every appearance of it in this tree has
 *    been half of a naive `datetime-local` round trip through the VIEWER's clock — right
 *    on a laptop set to India and silently wrong on every other one, which under D-22's
 *    "view as client" is a real session rather than a hypothetical.
 *
 * 3. **A date rendered through `toLocale*String` or `Intl.DateTimeFormat` must pin its
 *    zone.** The options object is what says whether the call formats a date or a number:
 *    `(5000).toLocaleString("en-IN")` groups digits and is fine, while any call carrying
 *    `day`/`month`/`hour`/`dateStyle`/… is rendering an INSTANT and must carry `timeZone`
 *    with it. Numbers never pass those keys, so the rule needs no exemption to leave
 *    `formatCount` and the marketing page's counts alone.
 *
 * ═══ THE EXEMPTION LIST ═════════════════════════════════════════════════════════════
 *
 * Two files, for rule 1 only, and both are a DEFINITION of the spelling rather than a use
 * of it: `formatINR`/`formatRupeeRate` in `ui.tsx` and `formatPaiseINR` in `lib/roi.ts`
 * (kept separate on purpose — that module is the marketing calculator's money and has no
 * React dependency). Everything else in the tree goes through one of the three. The list
 * may shrink; it may not grow without the argument written beside it.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(WEB_ROOT, "src");

/** The functions that DEFINE how a rupee is spelled. See the header. */
const RUPEE_DEFINITIONS = ["src/components/ui.tsx", "src/lib/roi.ts"];

/** Option keys that only a DATE or TIME is formatted with. */
const DATE_OPTIONS = new Set([
  "weekday",
  "era",
  "year",
  "month",
  "day",
  "hour",
  "minute",
  "second",
  "dayPeriod",
  "dateStyle",
  "timeStyle",
  "hourCycle",
  "fractionalSecondDigits",
]);

const LOCALE_METHODS = new Set([
  "toLocaleString",
  "toLocaleDateString",
  "toLocaleTimeString",
]);

interface Violation {
  file: string;
  line: number;
  rule: string;
  text: string;
}

function sourceFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...sourceFiles(path));
    else if (path.endsWith(".ts") || path.endsWith(".tsx")) found.push(path);
  }
  return found;
}

const FILES = sourceFiles(SRC);

function parse(path: string): ts.SourceFile {
  return ts.createSourceFile(
    path,
    readFileSync(path, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

/** The options object of a call, if the argument at `index` is written out inline. */
function optionsAt(call: ts.CallExpression | ts.NewExpression, index: number) {
  const arg = call.arguments?.[index];
  return arg && ts.isObjectLiteralExpression(arg) ? arg : null;
}

function propertyNames(options: ts.ObjectLiteralExpression): Set<string> {
  const names = new Set<string>();
  for (const property of options.properties) {
    const name = property.name;
    if (name && (ts.isIdentifier(name) || ts.isStringLiteral(name))) names.add(name.text);
  }
  return names;
}

function violationsIn(path: string): Violation[] {
  const file = parse(path);
  const rel = relPosix(WEB_ROOT, path);
  const found: Violation[] = [];
  const at = (node: ts.Node) =>
    file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
  const report = (node: ts.Node, rule: string, text: string) =>
    found.push({ file: rel, line: at(node), rule, text });

  // A `₹` glued to an interpolation that is not a call. `endsWith` rather than a scan:
  // the defect is the symbol IMMEDIATELY before the value, and a sentence that merely
  // mentions rupees elsewhere in the same text node is prose.
  const rupeeExempt = RUPEE_DEFINITIONS.includes(rel);
  const gluedToBareValue = (before: string, expression: ts.Expression | undefined) =>
    before.endsWith("₹") && expression !== undefined && !ts.isCallExpression(expression);

  const visit = (node: ts.Node): void => {
    if (!rupeeExempt && ts.isTemplateExpression(node)) {
      let head = node.head.text;
      for (const span of node.templateSpans) {
        if (gluedToBareValue(head, span.expression))
          report(span, "rupee glued to a bare value", `₹\${${span.expression.getText(file)}}`);
        head = span.literal.text;
      }
    }

    if (!rupeeExempt && (ts.isJsxElement(node) || ts.isJsxFragment(node))) {
      const children = node.children;
      for (let i = 1; i < children.length; i += 1) {
        const previous = children[i - 1];
        const child = children[i];
        if (!ts.isJsxText(previous) || !ts.isJsxExpression(child)) continue;
        if (gluedToBareValue(previous.text.trimEnd(), child.expression))
          report(child, "rupee glued to a bare value", `₹${child.getText(file)}`);
      }
    }

    if (ts.isPropertyAccessExpression(node) && node.name.text === "getTimezoneOffset")
      report(node, "browser-zone round trip", node.getText(file));

    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const method = node.expression.name.text;
      if (LOCALE_METHODS.has(method)) {
        const options = optionsAt(node, 1);
        const keys = options ? propertyNames(options) : new Set<string>();
        const formatsAnInstant = [...keys].some((key) => DATE_OPTIONS.has(key));
        if (formatsAnInstant && !keys.has("timeZone"))
          report(node, "date rendered in the viewer's zone", `${method}(…)`);
      }
    }

    if (
      ts.isNewExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "DateTimeFormat"
    ) {
      const options = optionsAt(node, 1);
      if (!options || !propertyNames(options).has("timeZone"))
        report(node, "date rendered in the viewer's zone", "new Intl.DateTimeFormat(…)");
    }

    ts.forEachChild(node, visit);
  };

  visit(file);
  return found;
}

describe("money and time go through the shared formatters", () => {
  it("reads the whole of src — a scan that matches nothing looks exactly like a clean tree", () => {
    expect(FILES.length).toBeGreaterThan(100);
  });

  it("finds no screen spelling one of them for itself", () => {
    const found = FILES.flatMap(violationsIn);
    expect(
      found.map((v) => `${v.file}:${v.line} — ${v.rule}: ${v.text}`),
    ).toEqual([]);
  });
});
