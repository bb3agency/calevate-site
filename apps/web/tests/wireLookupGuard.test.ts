import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import { posixDirPrefix, relPosix } from "./repoPaths";
import { fileURLToPath } from "node:url";

import { ESLint } from "eslint";
import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * The wire-lookup defect class, made UNREPEATABLE rather than merely fixed.
 *
 * `src/lib/lookup.ts` records what went wrong: a wire string indexed into a copy table
 * reaches `Object.prototype`, so `"constructor"` is present-but-wrong and the screen
 * either blanks mid-render or prints `function Object() { [native code] }` into a
 * `className`. Six sites in three disguises, one of them accidentally correct. The fix
 * landed; nothing stopped the seventh. D-29's doctrine is that a rule depending on human
 * vigilance is violated exactly when the codebase grows fastest, and `scripts/check_wiring.py`
 * is the backend's answer to the same problem. This is the frontend's.
 *
 * ## Two instruments, because the defect has two halves and they are not equally visible
 *
 * The GUARD half (`value in TABLE`) is decidable from syntax alone: a dynamic key with
 * `in` is wrong against any object, so `eslint.config.mjs` bans it outright and the
 * narrowing idiom `"field" in obj` stays legal. That is a lint rule, and it belongs in
 * lint — it fires in the editor, at the moment the line is typed.
 *
 * The READ half (`TABLE[value]`) is NOT decidable from syntax. `HOLD_RULES[rule]` is the
 * bug and `KYC_STATUS_COPY[status]` is correct, and the only difference is the KEY TYPE:
 * `string` off the wire versus a generated union `tsc` already polices. Without type
 * information a selector can only match "computed read off a table-shaped name", which
 * fires on ~35 sites the sweep correctly left alone — and a rule that cries wolf gets
 * `eslint-disable`d, which is worse than no rule. Turning on type-aware linting to carry
 * one rule would put a full program build inside every `pnpm lint`. So this half is a
 * test that builds the `tsc` program ONCE and asks the checker directly, the same way
 * the backend's `job_registration_test` interrogates the source rather than the runtime.
 *
 * ## Why both are pointed at a fixture as well as at `src/`
 *
 * Asserting "src has zero violations" passes just as well when the detector is broken as
 * when the code is clean. `tests/fixtures/wireLookupShapes.ts` holds both banned shapes
 * and four safe look-alikes transcribed from real call sites, so each instrument is
 * proven to fire on the bug AND to stay silent on the sites it must not touch. Delete
 * the ESLint rule from the config and this file goes red.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = "tests/fixtures/wireLookupShapes.ts";

/** The line a fixture marker sits on, so the expectations survive edits to the fixture. */
function fixtureLine(marker: string): number {
  const lines = readFileSync(resolve(WEB_ROOT, FIXTURE), "utf8").split("\n");
  // The marker names the FUNCTION, not the comment that introduces it: the offending
  // expression is inside the body, one line below the signature.
  const index = lines.findIndex((line) => line.startsWith(`export function ${marker}`));
  expect(index, `fixture is missing \`export function ${marker}\``).toBeGreaterThan(-1);
  return index + 2;
}

// ─────────────────────────────────────────────────────────────────────────────────────
// The GUARD half: `in` with a dynamic key.
// ─────────────────────────────────────────────────────────────────────────────────────

describe("the ESLint ban on `in` with a wire-supplied key", () => {
  let messages: ESLint.LintResult[];

  beforeAll(async () => {
    // `ignore: false` so the fixture is linted despite `eslint.config.mjs` skipping it
    // for `pnpm lint` (https://eslint.org/docs/latest/integrate/nodejs-api). The real
    // project config is loaded — this asserts the rule that actually ships, not a rule
    // re-declared here, which would pass with the config's copy deleted.
    const eslint = new ESLint({ cwd: WEB_ROOT, ignore: false });
    messages = await eslint.lintFiles([FIXTURE]);
  });

  it("flags the dynamic-key `in`, and nothing else in the file", () => {
    const flagged = messages
      .flatMap((r) => r.messages)
      .filter((m) => m.ruleId === "no-restricted-syntax");

    // Exactly one: `bannedIn`. If this ever reads zero the rule is gone from the config;
    // if it reads more than one the rule has started firing on a safe look-alike, which
    // is the failure mode that ends in `eslint-disable`.
    expect(flagged.map((m) => m.line)).toEqual([fixtureLine("bannedIn")]);
    expect(flagged[0]?.message).toContain("prototype chain");
    expect(flagged[0]?.severity, "must be an error, not a warning").toBe(2);
  });

  it("says what to do instead, by name", () => {
    // An operator-facing failure that names the remedy. A bare "restricted syntax" would
    // send the next author to the config to read a selector.
    const message = messages.flatMap((r) => r.messages).find((m) => m.ruleId === "no-restricted-syntax")
      ?.message;
    expect(message).toContain("hasKey");
    expect(message).toContain("lookup");
    expect(message).toContain("src/lib/lookup.ts");
  });
});

// ─────────────────────────────────────────────────────────────────────────────────────
// The READ half: a string-keyed copy table indexed by a wire string.
// ─────────────────────────────────────────────────────────────────────────────────────

/** One offending read, located the way a compiler error is. */
interface UnsafeRead {
  file: string;
  line: number;
  text: string;
}

/**
 * Is this binding declared at MODULE scope?
 *
 * The carve-out that keeps this instrument quiet. A `Record<string, …>` that is a
 * function parameter, a `useState` map or a local `const` built from `{}` is an object
 * THIS CODE BUILT — its keys are ours, and `values[field.key]` over a form's own draft
 * is correct. A module-scope `const` is a copy table, and the only reason to index one
 * with a runtime string is that the string came off the wire. Imports count as module
 * scope, which is what lets this see `HOLD_RULES[rule]` written in a file that merely
 * imports the table.
 */
function isModuleScoped(declaration: ts.Declaration): boolean {
  for (let node: ts.Node = declaration; node.parent; node = node.parent) {
    if (ts.isSourceFile(node.parent)) return true;
    // A body of any kind means the binding is local to a call, not a module constant.
    if (ts.isBlock(node.parent) || ts.isFunctionLike(node.parent)) return false;
  }
  return false;
}

/** Does this type accept an arbitrary `string` as a key? */
function hasStringIndex(checker: ts.TypeChecker, type: ts.Type): boolean {
  return checker.getIndexInfoOfType(type, ts.IndexKind.String) !== undefined;
}

/**
 * Does this identifier name a module-scope copy table — directly, or through a local
 * alias of one?
 *
 * The alias hop is not a refinement, it is the difference between catching the original
 * bug and missing it. `StatusBadge` is the most-reached lookup in the app and its
 * offending line read `styles[value]`, where `styles` is a LOCAL const:
 *
 *     const styles = kind === "lead" ? LEAD_STATUS_STYLES : CALL_STATUS_STYLES;
 *
 * Scope alone calls that a local object and waves it through, so the first draft of this
 * scan passed with the real bug reinstated — which is exactly why the reinstatement is
 * part of the procedure and not a formality. Picking the table by NAME (`SCREAMING_CASE`)
 * would have missed it too, in the other direction.
 *
 * So a local binding is followed one step: if its initialiser mentions a module-scope
 * table, the local IS that table. `useState<Record<string, string>>({})` is unaffected —
 * the only identifier in that initialiser is `useState`, whose type is a function and
 * carries no string index — and so is `const evidence: Record<string, string> = {}`,
 * whose initialiser mentions nothing at all.
 */
function isCopyTable(checker: ts.TypeChecker, identifier: ts.Identifier, depth = 0): boolean {
  const declaration = checker.getSymbolAtLocation(identifier)?.declarations?.[0];
  if (!declaration) return false;
  if (!hasStringIndex(checker, checker.getTypeAtLocation(identifier))) return false;
  if (isModuleScoped(declaration)) return true;

  // One hop. Two would start following the local's local, and the shapes that need it
  // are indistinguishable from ordinary data flow — that is a type checker's job, not a
  // grep's, and the honest limit is stated rather than approximated.
  if (depth > 0) return false;
  if (!ts.isVariableDeclaration(declaration) || !declaration.initializer) return false;

  let aliasesTable = false;
  const walk = (node: ts.Node): void => {
    if (aliasesTable) return;
    if (ts.isIdentifier(node) && isCopyTable(checker, node, depth + 1)) aliasesTable = true;
    else ts.forEachChild(node, walk);
  };
  walk(declaration.initializer);
  return aliasesTable;
}

/** Is this key an unconstrained `string`, rather than a union `tsc` already polices? */
function isWireString(type: ts.Type): boolean {
  const parts = type.isUnion() ? type.types : [type];
  // `StringLiteral` is deliberately NOT included: a literal key is one the author wrote.
  return parts.some((part) => (part.flags & ts.TypeFlags.String) !== 0);
}

function findUnsafeReads(program: ts.Program, sourceFile: ts.SourceFile): UnsafeRead[] {
  const checker = program.getTypeChecker();
  const found: UnsafeRead[] = [];

  const visit = (node: ts.Node): void => {
    // Only a plain identifier is inspected. `(table as Record<string, V>)[key]` — the
    // ONE sanctioned read, inside `lookup` itself — is a parenthesised assertion, not an
    // identifier, and falls out here rather than needing an allow-list. That also means
    // this instrument catches the ACCIDENT, not a determined evasion; a local alias of a
    // module table would slip past, and no source-level check can fix that. The lint
    // rule and this test are both about the shape people write by copying.
    if (ts.isElementAccessExpression(node) && ts.isIdentifier(node.expression)) {
      if (
        isCopyTable(checker, node.expression) &&
        isWireString(checker.getTypeAtLocation(node.argumentExpression))
      ) {
        found.push({
          file: relPosix(WEB_ROOT, sourceFile.fileName),
          line: sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          text: node.getText().replace(/\s+/g, " "),
        });
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return found;
}

describe("the type-aware ban on reading a copy table with a wire string", () => {
  let program: ts.Program;

  beforeAll(() => {
    // The REAL tsconfig, so the scan sees what `pnpm typecheck` sees. Paid once for the
    // file — a few seconds on an idle machine, but it is a whole-program build and it
    // grows with the tree, so the timeout is explicit and generous rather than left at
    // vitest's 10s default. It hit that default the first time this repo added a route
    // group and a test suite in the same afternoon, and a guard that fails on a busy
    // machine is a guard somebody deletes.
    const configPath = resolve(WEB_ROOT, "tsconfig.json");
    const config = ts.readConfigFile(configPath, ts.sys.readFile);
    expect(config.error, "tsconfig.json did not parse").toBeUndefined();
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, WEB_ROOT);
    program = ts.createProgram(parsed.fileNames, { ...parsed.options, noEmit: true });
  }, 120_000);

  it("flags the fixture's banned reads — including the one behind a local alias", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE));
    expect(fixture, `${FIXTURE} is not in the tsconfig program`).toBeDefined();

    const found = findUnsafeReads(program, fixture!);
    // The alias case is `StatusBadge`'s actual line. An earlier draft of this scan
    // reported only the direct read and therefore passed with that bug reinstated.
    expect(found.map((r) => r.line)).toEqual([
      fixtureLine("bannedRead"),
      fixtureLine("bannedAliasedRead") + 1,
    ]);
    expect(found.map((r) => r.text)).toEqual(["WIRE_KEYED[wireValue]", "styles[wireValue]"]);
  });

  it("stays silent on the four safe look-alikes", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flaggedLines = new Set(findUnsafeReads(program, fixture).map((r) => r.line));

    // Each of these indexes something with a computed key on the line after its
    // signature. If any appears here the instrument has become the noisy rule this file
    // exists to avoid — and the noisy rule is the one that ends in `eslint-disable`.
    for (const safe of ["safeUnionRead", "safeOwnKeysRead", "safeLocalRead"]) {
      expect(flaggedLines.has(fixtureLine(safe)), `${safe} must not be flagged`).toBe(false);
    }
  });

  it("finds no such read anywhere in src/", () => {
    const sources = program
      .getSourceFiles()
      .filter(
        (file) =>
          file.fileName.startsWith(posixDirPrefix(WEB_ROOT, "src")) &&
          // Generated from OpenAPI; it declares types, it does not read tables.
          !file.fileName.endsWith("schema.d.ts"),
      );
    // A premise check: if the glob ever stops matching, "no violations" becomes true for
    // the wrong reason and this whole describe block silently stops testing anything.
    expect(sources.length, "no src files in the program — the scan is looking nowhere").toBeGreaterThan(40);

    const violations = sources.flatMap((file) => findUnsafeReads(program, file));
    expect(
      violations.map((v) => `${v.file}:${v.line}  ${v.text}`),
      "read the copy table through `lookup()` (src/lib/lookup.ts) — a wire string " +
        "indexed straight into a table resolves `constructor` to the `Object` function",
    ).toEqual([]);
  });
});
