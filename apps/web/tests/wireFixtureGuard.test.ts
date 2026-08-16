import { readFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * The optional-on-the-wire trap, made UNREPEATABLE rather than merely swept.
 *
 *     A type assertion onto a generated wire type is an instruction to stop checking the
 *     one thing a fixture exists to get right.
 *
 * ═══ WHAT WENT WRONG, FIVE TIMES ═════════════════════════════════════════════════════
 *
 * Every read in this app is typed from `src/lib/api/schema.d.ts`, generated from the
 * FastAPI OpenAPI snapshot. A test fixture standing in for a response is therefore a
 * claim about the wire, and the compiler can check that claim exactly — unless somebody
 * writes `as`.
 *
 * Five margin fixtures carried `as Margin`. Every one of them was missing a required
 * field, `pnpm typecheck` stayed green through all of it, and the panel threw at runtime
 * in 25 tests. That is the whole defect: the assertion did not make the fixture right, it
 * made the fixture UNCHECKED, and an unchecked fixture drifts from the wire silently
 * because nothing else in the system ever compares the two.
 *
 * The sweep that added this guard removed **106 such assertions across 42 test files**,
 * and the compiler then reported 34 errors that had been sitting behind them. Seven were
 * not cosmetic:
 *
 *  - three `Agent` fixtures had NO `disclosure_line` — hard rule 5's field, on the
 *    outbound agents the campaign screens dial with;
 *  - `CampaignSummary.created_at` was missing from four fixtures, `CampaignProgress`'s
 *    `concurrency`/`launched_at`/`status` from five;
 *  - twelve client-realm `Me` fixtures set `organization.plan_tier`, which `OrganizationOut`
 *    does not have and (`additionalProperties: false`) the server cannot send, while
 *    omitting `status`, which it always does;
 *  - `Dashboard.minutes_used_month` — a decimal-as-string under hard rule 7 — was `null`,
 *    a value its schema forbids.
 *
 * None of those broke a test. That is the point, and it is why review did not catch them:
 * a fixture that lies in the same direction the screen ignores produces a green suite and
 * a wrong belief about what the screen has been shown.
 *
 * ═══ WHAT IS CHECKED ═════════════════════════════════════════════════════════════════
 *
 * One rule, in `tests/` AND in `src/`: **no type assertion whose target resolves to a
 * declaration in `schema.d.ts`.** `as T`, `as unknown as T`, `as T[]`, `as T["field"]`,
 * and the old `<T>expr` form.
 *
 * `src/` is included even though it is clean today. An assertion onto a wire type in a
 * SCREEN is worse than one in a fixture — it is the screen telling the compiler it knows
 * better than the generated client about what the server sends — and a guard that only
 * watches the place the defect happened to appear first is a guard with a known door in
 * it. Measured: zero sites in `src/`, so this costs nothing and closes the door.
 *
 * ═══ WHAT IS ALLOWED, AND WHY EACH ═══════════════════════════════════════════════════
 *
 *  - **`satisfies T`** — the sanctioned replacement where there is no declaration to
 *    annotate, i.e. a value inside a `Routes` map (`Record<string, unknown>`), where the
 *    contextual type checks nothing. `satisfies` demands every required field and rejects
 *    fields the server cannot send, while leaving the value's own type alone. It is a
 *    `SatisfiesExpression`, a different node kind, so it falls out of this scan by
 *    construction rather than by an exception.
 *  - **A type annotation** — `const ME: Me = {…}`. The house spelling, and what 90 of the
 *    106 removed sites already had UNDERNEATH the assertion. Those two had been cancelling
 *    each other out: an assertion makes the initialiser's type `T`, so the annotation it
 *    sits beside then checks nothing at all.
 *  - **A DOM assertion** — `screen.getByRole(…) as HTMLButtonElement`, ~120 sites.
 *    Testing-library returns `HTMLElement` and `.disabled` lives on the subtype. Nothing
 *    about it concerns the wire.
 *  - **A hand-written api type** — `failure as ApiProblem` narrows a caught `unknown` onto
 *    a CLASS in `src/lib/api/client.ts`. Keying on `schema.d.ts` rather than on "types in
 *    src/lib/api" is what keeps this legal, and it is deliberate: a rule that fired on the
 *    normal spelling of error narrowing would be waived inside a week.
 *  - **`as const`**, which narrows a literal rather than silencing a check.
 *  - **A payload that is deliberately OFF-CONTRACT, carried as `unknown`.** Three tests
 *    exist to prove the UI copes with a server newer than this build. The honest spelling
 *    is a plain literal handed to the route map, which takes `unknown`; the spelling they
 *    had was `kind: "x" as AttentionItem["kind"]`, an assertion claiming the union ALREADY
 *    CONTAINS the value whose absence is the premise of the test. That one is worth
 *    stating twice: it would have kept compiling on the day somebody deleted a kind from
 *    the union for real, which is precisely the change the test is meant to survive.
 *
 * ═══ WHAT IS **NOT** CHECKED ═════════════════════════════════════════════════════════
 *
 * Stated plainly, because a guard that implies more than it verifies is the §52 defect one
 * level up.
 *
 *  - **An UNTYPED fixture.** `const PROGRESS = {status: "draft", contacts: {}, total: 0}`
 *    handed to a `Record<string, unknown>` route map is checked by nothing, and this scan
 *    cannot tell it from the deliberate off-contract payload above — they are the same
 *    node. The sweep found 11 of these created by its own strip and annotated every one
 *    by hand; what stops the twelfth is a reviewer, not this file. Deciding it mechanically
 *    would mean inferring which literals are MEANT to be responses, and the only honest
 *    signal for that (does it flow into a route map keyed by a `/v1/…` path?) is dataflow
 *    the checker will not follow through a spread.
 *  - **A fixture that is complete and WRONG.** `status: "live"` on an agent that the test
 *    then treats as paused is a lie the type system cannot see. Per-screen tests own it.
 *  - **A determined evasion** — `JSON.parse`, an `any`, a helper in another module. Like
 *    the two guards beside it, this catches the shape people write by COPYING, which is
 *    the shape that actually recurs: 42 files had it and they are visibly copies of one
 *    another.
 *
 * ═══ WHY A TEST AND NOT A LINT RULE ══════════════════════════════════════════════════
 *
 * The same seam, and the same side of it, as `wireLookupGuard.test.ts` and
 * `surfaceStatesGuard.test.ts` — read either header for the full argument. In short: the
 * rule is not decidable from syntax. `as Margin` and `as HTMLButtonElement` are one
 * selector to ESLint, and telling them apart needs the checker to resolve the target type
 * to its declaring FILE. `eslint.config.mjs` deliberately runs typescript-eslint without a
 * type-aware project service, because turning one on to carry a single rule puts a full
 * program build inside every `pnpm lint`. This is the third type-aware frontend guard and
 * it uses the same mechanism as the other two — `typescript` directly, one program built
 * per file, in the suite `make web-check` already runs. "One way per problem" (CLAUDE.md).
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = "tests/fixtures/wireFixtureShapes.ts";
const SCHEMA = resolve(WEB_ROOT, "src/lib/api/schema.d.ts");

/**
 * Explicit and generous, for the reason the two guards beside it give: a whole-tree
 * type-aware walk takes seconds, vitest's default `it` timeout is five, and the suite runs
 * its files in parallel. A guard that fails when the machine is busy is a guard somebody
 * deletes for flakiness.
 */
const SCAN_TIMEOUT_MS = 60_000;

/**
 * Sites that assert onto a wire type and are NOT this slice's to fix, each with what
 * closes it.
 *
 * Keyed by file AND by the asserted type — never by line, which drifts on the first edit
 * above it. Same doctrine as `surfaceStatesGuard.EXEMPT`. The list may only SHRINK: an
 * entry that no longer matches a real violation fails this suite, so a fixed site cannot
 * leave a permanent excuse behind.
 *
 * EMPTY, and that is the point of the sweep that wrote this guard: all 106 sites were
 * removed in the same change. A rule that shipped with excuses on it would be worth less
 * than no rule, because the excuses are what the next author copies.
 */
const EXEMPT: Record<string, string> = {};

interface Violation {
  file: string;
  line: number;
  type: string;
  /** The literal being asserted, clipped — a label, not the evidence. */
  text: string;
}

/** `{file}  as {type}` — the key `EXEMPT` is written in, and what a failure prints. */
function siteKey(violation: Violation): string {
  return `${violation.file}  as ${violation.type}`;
}

const REMEDY =
  "Delete the assertion. If the value has a declaration, ANNOTATE it (`const ME: Me = " +
  "{…}`) — most of these already had an annotation the assertion was cancelling. If it " +
  "is a value inside a `Routes` map, use `satisfies T`, which checks the same thing and " +
  "leaves the type alone. If the payload is deliberately OFF-CONTRACT (a server newer " +
  "than this build), assert nothing: hand the plain literal to the route map, which takes " +
  "`unknown` — that is what an unrecognised value IS to us.";

/**
 * Does this type resolve to a shape DECLARED in the generated wire schema?
 *
 * By declaring FILE, not by name. Every wire type in this app is an alias —
 * `type Me = Schemas["MeOut"]`, `type Margin = Schemas["MarginOut"]` — and the aliases
 * live in five different modules (`src/lib/api/*.ts`, and `AdminMe` in
 * `src/app/admin/access.ts`, which a "types under src/lib/api" test would have missed
 * entirely; 20 of the 106 sites were `as AdminMe`). What they have in common is that the
 * checker resolves every one of them to an object type whose symbol was declared in
 * `schema.d.ts`. That is the property worth keying on, and it needs no maintenance when
 * somebody adds the sixth module.
 *
 * The recursion covers `T[]` and `T["field"]`: an array's element type and a union's
 * members are reached through type arguments and `types` respectively. Depth is capped at
 * three because the shapes people write are shallow, and an uncapped walk over a
 * recursive generated type does not terminate usefully.
 */
function isWireType(checker: ts.TypeChecker, type: ts.Type | undefined, depth = 0): boolean {
  if (!type || depth > 3) return false;
  if (type.isUnionOrIntersection()) {
    return type.types.some((part) => isWireType(checker, part, depth + 1));
  }
  const declarations = type.getSymbol()?.declarations ?? type.aliasSymbol?.declarations ?? [];
  if (declarations.some((declaration) => declaration.getSourceFile().fileName === SCHEMA)) {
    return true;
  }
  if (
    (checker.getTypeArguments?.(type as ts.TypeReference) ?? []).some((argument) =>
      isWireType(checker, argument, depth + 1),
    )
  ) {
    return true;
  }
  /*
   * `aliasTypeArguments` — where a MAPPED type keeps what it was applied to.
   *
   * `getTypeArguments` above only answers for a type REFERENCE, and `Partial<Me>` is not
   * one: it resolves to an anonymous mapped type whose own symbol is declared nowhere
   * near `schema.d.ts` and whose `aliasSymbol` is `Partial`, in `lib.es5.d.ts`. The first
   * version of this guard therefore waved through `as Partial<Me>` and
   * `as unknown as Partial<CallDetail>` — and behind one of those, a transcript fixture
   * was missing `TranscriptTurnOut.redacted`, a REQUIRED field, with `pnpm typecheck`
   * green. One line, and it closes every generic wrapper at once (`Partial`, `Readonly`,
   * `Required`, `Pick`, `Omit`, `Record<string, Me>`) rather than the one that was found.
   */
  return (type.aliasTypeArguments ?? []).some((argument) =>
    isWireType(checker, argument, depth + 1),
  );
}

/**
 * Does this type NODE name a wire type — resolved, or reached through an indexed access?
 *
 * The syntactic half exists because `CallSummary["status"]` resolves to bare `string`, and
 * `AttentionItem["kind"]` to a union of string literals: neither carries a symbol declared
 * in `schema.d.ts`, so `isWireType` alone cannot see either, and both were live sites.
 * That shape is the one that does the most damage per instance — `"number_suspended" as
 * AttentionItem["kind"]` asserts that a closed union already contains the value whose
 * ABSENCE is the premise of the test around it — so it is worth the extra branch rather
 * than a paragraph in "not checked".
 *
 * Asking the NODE is exact here: the objectType of the indexed access is written out in
 * the source, and it resolves to the wire type by the ordinary rule.
 */
function targetsWireType(checker: ts.TypeChecker, typeNode: ts.TypeNode): boolean {
  if (isWireType(checker, checker.getTypeFromTypeNode(typeNode))) return true;
  if (ts.isIndexedAccessTypeNode(typeNode)) return targetsWireType(checker, typeNode.objectType);
  if (ts.isArrayTypeNode(typeNode)) return targetsWireType(checker, typeNode.elementType);
  /*
   * The written form of the same mapped-type hole. `isWireType`'s `aliasTypeArguments`
   * branch answers for `Partial<Me>`, and this answers for the cases where the checker
   * hands back something with no alias at all — a type argument that is itself indexed
   * (`Partial<CallDetail["transcript"]>`), or a wrapper whose instantiation the checker
   * has already eagerly resolved. Asking the NODE is exact: the argument is written out
   * in the source, so there is nothing to infer.
   */
  if (ts.isTypeReferenceNode(typeNode)) {
    return (typeNode.typeArguments ?? []).some((argument) => targetsWireType(checker, argument));
  }
  return false;
}

function findViolations(program: ts.Program, sourceFile: ts.SourceFile): Violation[] {
  const checker = program.getTypeChecker();
  const found: Violation[] = [];

  const visit = (node: ts.Node): void => {
    // `ts.isTypeAssertionExpression` is the old `<T>expr` form. It is illegal in `.tsx`
    // and legal in the `.ts` half of this tree, so it is covered rather than assumed away.
    if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
      if (targetsWireType(checker, node.type)) {
        const text = node.expression.getText().replace(/\s+/g, " ");
        found.push({
          file: relative(WEB_ROOT, sourceFile.fileName),
          // The TYPE node, not the expression: on a multi-line fixture the expression
          // starts at `return {` and the `as` is thirteen lines further down, which is
          // the line whoever has to delete it needs.
          line: sourceFile.getLineAndCharacterOfPosition(node.type.getStart()).line + 1,
          type: node.type.getText(),
          text: text.length <= 60 ? text : `${text.slice(0, 60)}…`,
        });
        // Do not descend: an inner `as unknown` is part of THIS violation, and reporting
        // it twice would make the count disagree with the number of edits needed.
        return;
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return found;
}

/** The line a fixture marker sits on, so expectations survive edits to the fixture. */
function fixtureLine(marker: string): number {
  const lines = readFileSync(resolve(WEB_ROOT, FIXTURE), "utf8").split("\n");
  const index = lines.findIndex(
    (line) => line.startsWith(`export function ${marker}`) || line.startsWith(`export const ${marker}`),
  );
  expect(index, `fixture is missing \`${marker}\``).toBeGreaterThan(-1);
  return index + 1;
}

describe("the wire-fixture guard: a type assertion onto a generated schema type", () => {
  let program: ts.Program;

  beforeAll(() => {
    // The REAL tsconfig, so the scan sees what `pnpm typecheck` sees. A whole-program
    // build, paid once, with an explicit and generous timeout for the same reason the two
    // guards beside this one have one.
    const configPath = resolve(WEB_ROOT, "tsconfig.json");
    const config = ts.readConfigFile(configPath, ts.sys.readFile);
    expect(config.error, "tsconfig.json did not parse").toBeUndefined();
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, WEB_ROOT);
    program = ts.createProgram(parsed.fileNames, { ...parsed.options, noEmit: true });
  }, 120_000);

  // ── negative control: it fires on the planted defects ──────────────────────────────

  it("flags every banned assertion in the fixture, and only those", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE));
    expect(fixture, `${FIXTURE} is not in the tsconfig program`).toBeDefined();

    const found = findViolations(program, fixture!);
    // Each offending expression sits a fixed distance below its marker. Spelled per
    // marker rather than assumed, because the multi-line literals are the realistic shape.
    expect(found.map((violation) => `${violation.line} ${violation.type}`)).toEqual([
      `${fixtureLine("bannedSingleAssertion") + 13} TenantSummary`,
      `${fixtureLine("bannedDoubleAssertion") + 8} Me`,
      `${fixtureLine("bannedArrayAssertion") + 1} CallSummary[]`,
      `${fixtureLine("bannedIndexedAccessAssertion") + 1} CallSummary["status"]`,
      `${fixtureLine("bannedPartialAssertion") + 1} Partial<Me>`,
    ]);
  }, SCAN_TIMEOUT_MS);

  it("sees through a mapped type to the wire type it was applied to", () => {
    // Called out on its own because this is the hole the guard shipped with: `Partial<T>`
    // resolves to an anonymous mapped type, so every mechanism the first version had —
    // the declaring file of the type's symbol, `getTypeArguments`, the indexed-access
    // branch — answered "not a wire type" for it. Three live sites passed, and one of
    // them was hiding a missing REQUIRED field. If this ever goes green the other way,
    // `as unknown as Partial<Anything>` is an unchecked fixture again.
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = findViolations(program, fixture).map((violation) => violation.line);
    expect(flagged).toContain(fixtureLine("bannedPartialAssertion") + 1);
  }, SCAN_TIMEOUT_MS);

  it("stays silent on the six safe look-alikes", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = new Set(findViolations(program, fixture).map((violation) => violation.line));

    // Every one of these is a real spelling this suite uses. If any appears here the guard
    // has become the noisy rule its header exists to avoid — and the noisy rule is the one
    // that gets waived until it protects nothing.
    for (const safe of [
      "safeSatisfies",
      "safeAnnotation",
      "safeOffContractPayload",
      "safeDomAssertion",
      "safeNonWireAssertion",
      "safeAsConst",
    ]) {
      const start = fixtureLine(safe);
      const lines = [...flagged].filter((line) => line >= start && line <= start + 16);
      expect(lines, `${safe} must not be flagged`).toEqual([]);
    }
  }, SCAN_TIMEOUT_MS);

  it("distinguishes a wire type from a hand-written one and from the DOM", () => {
    // The single most important property, called out on its own: getting it wrong in the
    // tolerant direction makes the guard useless, and getting it wrong in the strict
    // direction makes it unusable. `safeDomAssertion` even contains `as unknown as X` —
    // the exact double-assertion shape that is banned for `Me` — and it is CORRECT there,
    // because `HTMLButtonElement` is not on the wire. Only the target type separates them.
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = findViolations(program, fixture).map((violation) => violation.line);
    expect(flagged).toContain(fixtureLine("bannedDoubleAssertion") + 8);
    expect(flagged).not.toContain(fixtureLine("safeDomAssertion") + 1);
    expect(flagged).not.toContain(fixtureLine("safeNonWireAssertion") + 1);
  }, SCAN_TIMEOUT_MS);

  // ── the tree ───────────────────────────────────────────────────────────────────────

  it("finds no unexempted assertion anywhere in tests/ or src/", () => {
    const sources = program.getSourceFiles().filter(
      (file) =>
        (file.fileName.startsWith(resolve(WEB_ROOT, "src") + "/") ||
          file.fileName.startsWith(resolve(WEB_ROOT, "tests") + "/")) &&
        // Generated from OpenAPI; it DECLARES the wire types rather than asserting onto
        // them, and it is not hand-edited.
        file.fileName !== SCHEMA &&
        // The negative control, whose whole job is to contain violations.
        file.fileName !== resolve(WEB_ROOT, FIXTURE),
    );
    // A premise check: if the glob ever stops matching, "no violations" becomes true for
    // the wrong reason and this whole file silently stops testing anything.
    expect(
      sources.length,
      "no src/ or tests/ files in the program — the scan is looking nowhere",
    ).toBeGreaterThan(100);

    const violations = sources
      .flatMap((file) => findViolations(program, file))
      // `Object.hasOwn`, not `in`: the site key is built from file paths and source text,
      // so `in` would let a site named `constructor` exempt itself off `Object.prototype`
      // (src/lib/lookup.ts, and the ESLint ban that enforces it).
      .filter((violation) => !Object.hasOwn(EXEMPT, siteKey(violation)));

    expect(
      violations.map(
        (violation) => `${violation.file}:${violation.line}  ${violation.text} as ${violation.type}`,
      ),
      "A fixture standing in for a response is a CLAIM ABOUT THE WIRE, and `as` is an " +
        `instruction to stop checking it. ${REMEDY}`,
    ).toEqual([]);
  }, SCAN_TIMEOUT_MS);

  it("keeps no exemption that is not still a live violation", () => {
    // A stale exemption is a hole with a comment on it (check_wiring.stale_baseline). The
    // list may only shrink, and only by somebody fixing the site.
    const live = new Set(
      program
        .getSourceFiles()
        .filter(
          (file) =>
            (file.fileName.startsWith(resolve(WEB_ROOT, "src") + "/") ||
              file.fileName.startsWith(resolve(WEB_ROOT, "tests") + "/")) &&
            file.fileName !== SCHEMA &&
            file.fileName !== resolve(WEB_ROOT, FIXTURE),
        )
        .flatMap((file) => findViolations(program, file))
        .map(siteKey),
    );

    expect(
      Object.keys(EXEMPT).filter((key) => !live.has(key)),
      "these EXEMPT entries no longer match a violation — delete them",
    ).toEqual([]);
  }, SCAN_TIMEOUT_MS);
});
