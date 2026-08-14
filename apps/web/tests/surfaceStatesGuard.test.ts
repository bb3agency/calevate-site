import { readFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * BUILD-LOG §52, made executable — the half of it a machine can decide.
 *
 *     loading is a skeleton, failure is a refusal, and neither is a number, a state,
 *     or an empty state.
 *
 * §52 is the most-cited UI rule in this repo and, until this file, the only major one
 * with no executable guard: it was held up by review and by per-screen tests somebody
 * remembered to write. D-29's whole argument is that a rule enforced by memory is
 * violated exactly when the codebase grows fastest, and §52 has already been violated
 * nine times in one wave — the ops screen reporting "Outbound calling: running" off a
 * read that FAILED, the campaigns screen saying "no campaigns yet" over a 503, a
 * dashboard showing 5,430 calls to a client whose calls had stopped.
 *
 * ═══ WHAT IS CHECKED ═════════════════════════════════════════════════════════════════
 *
 * One mechanism, because every one of those nine defects was the same two characters.
 * A TanStack `UseQueryResult.data` is `T | undefined`, and that `undefined` means
 * exactly one thing: WE HAVE NOT GOT AN ANSWER — the request is in flight, or it failed.
 * A fallback applied to it converts our ignorance into a value the screen then states.
 * So the subject is: **a `??`/`||` fallback whose left side reads the query envelope**.
 * Two shapes of it are decidable without knowing which branch renders the result:
 *
 *  1. **A boolean fallback, anywhere.** `?? false` / `?? true` on an envelope read is
 *     never honest. A boolean has no absent value, so the fallback does not defer the
 *     question, it answers it — and the screen renders that answer as a state. This is
 *     literally the shape that produced §52's worst instance
 *     (`platform?.outbound_halted ?? false`).
 *  2. **A manufactured literal in a JSX CHILD position.** `{q.data?.count ?? 0}` is the
 *     number, the state or the empty collection printed on the screen as a fact, with
 *     no branch between it and the pixel. `?? 5430` was this.
 *
 * "Manufactured literal" means a number, `true`/`false`, `[]` or `{}` — a value. NOT a
 * string, NOT `null`, NOT `undefined`: `?? "—"` and `?? null` claim absence, which is
 * the truth when we do not know, and banning them would push authors toward inventing
 * something instead.
 *
 * ═══ WHAT IS **NOT** CHECKED, AND WHY ════════════════════════════════════════════════
 *
 * Stated plainly, because a guard that implies more than it verifies is the §52 defect
 * one level up — a confident claim from something that did not actually read.
 *
 * * **"Loading is a skeleton" is not decidable here.** Whether a component renders a
 *   `<Skeleton>` versus nothing versus a stale number, on which branch, is a rendering
 *   question. Per-screen tests own it (dashboard.test.tsx, ops.test.tsx, campaigns.test.tsx).
 * * **"Failure is a refusal you can act on" is not decidable here.** That a `ProblemNotice`
 *   appears is checkable per screen; that its wording tells an owner what to do is a
 *   judgement no parser makes.
 * * **`?? []` outside a JSX child is deliberately out of scope**, and this is the
 *   narrowing that mattered most. `const rows = board.data ?? []` is CORRECT in
 *   `admin/health/page.tsx` — the render below it is a `isLoading ? skeleton : error ?
 *   refusal : rows.length === 0 ? empty` ladder, so the `[]` never reaches a pixel — and
 *   it is a LIE on a screen with no error branch. The difference is branch dominance,
 *   which this scan cannot compute. Measured on the tree the day this landed: flagging
 *   every non-boolean literal fallback on an envelope read gives 22 hits of which ~20
 *   are correct code, and adding a "does the component consult this query's error
 *   state?" heuristic only gets that to 12/2. Both are exemption treadmills, and a rule
 *   at those rates gets waived until it means nothing.
 * * **`if (!data) return null`** — §52 names it, and it is not distinguishable from a
 *   legitimate early return without knowing what the caller renders instead.
 * * **A determined evasion.** Copy `q.data` into an `any`, or into a helper in another
 *   module, and this loses the trail. Like the wire-lookup guard beside it, this catches
 *   the shape people write by COPYING, which is the shape that actually recurs.
 *
 * ═══ WHY THIS IS A TEST AND NOT `scripts/check_surface_states.py` ════════════════════
 *
 * The house pattern for executable governance is `scripts/check_*.py` in `make
 * guardrails`, and it is the wrong home here, for the reason the repo already
 * discovered once:
 *
 * * The rule is NOT decidable from syntax. `board.data ?? []` (envelope, in scope) and
 *   `verify.data.first_bad_entry_id ?? "…"` (payload null, correct, and the refusal
 *   doing its job) are the same shape to a regex and to a bare AST. Telling them apart
 *   needs the TYPE at the site — specifically whether `X.data` still includes
 *   `undefined`, which is how the checker records that no `isPending`/`isError` guard
 *   has narrowed it. A `.tsx` regex from Python would have to reimplement TypeScript's
 *   control-flow narrowing to get that right, and would get it wrong quietly.
 * * A custom **ESLint rule** was the other candidate and is rejected on the repo's own
 *   recorded grounds. `eslint.config.mjs` deliberately runs typescript-eslint WITHOUT a
 *   type-aware project service, because turning one on to carry a single rule puts a
 *   full program build inside every `pnpm lint`; the wire-lookup guard split along
 *   exactly this seam and left its type-dependent half here, in a test that builds the
 *   `tsc` program once. This is the same seam and the same side of it. Two type-aware
 *   frontend guards, one mechanism: "one way per problem" (CLAUDE.md).
 * * It still runs on every PR: `make web-check` → `pnpm -C apps/web test`, and CI runs
 *   the same target. The `tsc` program is shared with `wireLookupGuard.test.ts`'s build
 *   in the same suite process, so the marginal cost is the walk, not the build.
 *
 * Research, so the next reader inherits the evidence: `eslint-plugin-react-hooks` and
 * `@tanstack/eslint-plugin-query` were both checked first — the TanStack plugin ships
 * `no-rest-destructuring`, `exhaustive-deps`, `stable-query-client` and
 * `no-unstable-deps`, none of which is about what a fallback claims, and adding a plugin
 * would mean touching `apps/web/package.json`. `ts-morph` was considered as a friendlier
 * wrapper over the compiler API and rejected as a second way to do what
 * `wireLookupGuard.test.ts` already does with `typescript` directly.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURE = "tests/fixtures/surfaceStateShapes.tsx";

/**
 * Sites that violate the rule and are NOT this slice's to fix, each with what closes it.
 *
 * Keyed by file AND by the offending expression's text — never by file alone, which
 * would exempt the next fallback somebody adds to the same screen, and never by line,
 * which drifts on the first edit above it. Same doctrine as
 * `check_redaction_exposure.KNOWN_SAFE_FIELDS`. The list may only SHRINK: an entry that
 * no longer matches a real violation fails this suite, so a fixed site cannot leave a
 * permanent excuse behind.
 */
const EXEMPT: Record<string, string> = {
  'src/app/c/[slug]/integrations/page.tsx  me.data?.permissions?.includes("calls:read_raw") ?? false':
    "the same defect as the Leads export, in a file another slice owns this wave. On a " +
    "failed `/v1/me` the payload offer disappears and the screen implies a refusal it " +
    "never received. Closes by moving to `useWriteAccess` (lib/api/hooks.ts), which " +
    'answers "We could not check whether you can …" for exactly this case.',
};

interface Violation {
  file: string;
  line: number;
  text: string;
  claim: string;
}

/** `{file}  {text}` — the key `EXEMPT` is written in, and what a failure prints. */
function siteKey(violation: Violation): string {
  return `${violation.file}  ${violation.text}`;
}

/**
 * Is this the result object of a TanStack query or mutation?
 *
 * Structural, not by type NAME. Every read in this app goes through a wrapper hook in
 * `src/lib/api/*` declared as `UseQueryResult<T>`, but a hook that returned a narrowed
 * or re-wrapped result would still carry these members, and a name test would miss it.
 * `data` + `isError` + `isPending` + (`refetch` | `mutate`) is the envelope and nothing
 * else in this tree has that shape.
 */
function isServerEnvelope(checker: ts.TypeChecker, type: ts.Type): boolean {
  const names = new Set(checker.getPropertiesOfType(type).map((property) => property.getName()));
  return (
    names.has("data") &&
    names.has("isError") &&
    names.has("isPending") &&
    (names.has("refetch") || names.has("mutate"))
  );
}

function includesUndefined(type: ts.Type): boolean {
  const parts = type.isUnion() ? type.types : [type];
  return parts.some((part) => (part.flags & ts.TypeFlags.Undefined) !== 0);
}

/**
 * Does this expression read an UNNARROWED query envelope?
 *
 * Two conditions, and the second is the one that makes the guard usable at all:
 *
 *  - the value comes from `X.data` where `X` is an envelope (directly, or through a
 *    `const { data } = useThing()` destructure — otherwise the commonest React spelling
 *    of the bug would be invisible); and
 *  - `X.data`'s type AT THIS SITE still includes `undefined`.
 *
 * The second condition IS the §52 question, asked of the type checker. TanStack v5's
 * result type is a discriminated union, so `if (q.isPending) return <Skeleton/>; if
 * (q.isError) return <Refusal/>;` narrows `q.data` to `T`. A screen that has refused
 * properly therefore has no undefined left to coalesce, and any `??` below those guards
 * is catching a null the SERVER SENT — a fact about the world, which is exactly what
 * `?? "—"` is for. Without this condition the guard reads the ops screen's
 * `verify.data.first_bad_entry_id ?? "an entry it did not name"` — the refusal doing its
 * job — as a violation.
 */
function readsUnnarrowedEnvelope(checker: ts.TypeChecker, node: ts.Node): boolean {
  let found = false;

  const visit = (child: ts.Node): void => {
    if (found) return;

    if (ts.isPropertyAccessExpression(child) && child.name.text === "data") {
      if (
        isServerEnvelope(checker, checker.getTypeAtLocation(child.expression)) &&
        includesUndefined(checker.getTypeAtLocation(child))
      ) {
        found = true;
        return;
      }
    }

    if (ts.isIdentifier(child) && isDestructuredData(checker, child)) {
      if (includesUndefined(checker.getTypeAtLocation(child))) {
        found = true;
        return;
      }
    }

    ts.forEachChild(child, visit);
  };

  visit(node);
  return found;
}

/** `const { data } = useThing()` — the same envelope read, spelled the other way. */
function isDestructuredData(checker: ts.TypeChecker, identifier: ts.Identifier): boolean {
  const declaration = checker.getSymbolAtLocation(identifier)?.declarations?.[0];
  if (!declaration || !ts.isBindingElement(declaration)) return false;

  const pattern = declaration.parent;
  if (!ts.isObjectBindingPattern(pattern) || !ts.isVariableDeclaration(pattern.parent)) return false;

  const initializer = pattern.parent.initializer;
  if (!initializer || !isServerEnvelope(checker, checker.getTypeAtLocation(initializer))) return false;

  const property = declaration.propertyName ?? declaration.name;
  return ts.isIdentifier(property) && property.text === "data";
}

/**
 * A value invented to stand in for an answer we do not have — and what the screen then
 * claims with it, in §52's own three words.
 */
function manufacturedClaim(node: ts.Expression): string | null {
  if (ts.isNumericLiteral(node)) return "a number";
  if (node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword) {
    return "a state";
  }
  if (ts.isArrayLiteralExpression(node) && node.elements.length === 0) return "an empty state";
  if (ts.isObjectLiteralExpression(node) && node.properties.length === 0) return "an empty state";
  // A string, `null` and `undefined` are absence MARKERS. They claim nothing, and they
  // are what an honest screen falls back to while it does not know.
  return null;
}

/** Is this expression rendered straight into the document, with no branch in between? */
function isJsxChild(node: ts.Node): boolean {
  const parent = node.parent;
  return (
    ts.isJsxExpression(parent) &&
    (ts.isJsxElement(parent.parent) || ts.isJsxFragment(parent.parent))
  );
}

function findViolations(program: ts.Program, sourceFile: ts.SourceFile): Violation[] {
  const checker = program.getTypeChecker();
  const found: Violation[] = [];

  const visit = (node: ts.Node): void => {
    if (
      ts.isBinaryExpression(node) &&
      (node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken ||
        node.operatorToken.kind === ts.SyntaxKind.BarBarToken)
    ) {
      const claim = manufacturedClaim(node.right);
      // A boolean is always in scope; anything else only when it is the pixel itself.
      const inScope = claim === "a state" || isJsxChild(node);
      if (claim && inScope && readsUnnarrowedEnvelope(checker, node.left)) {
        found.push({
          file: relative(WEB_ROOT, sourceFile.fileName),
          line: sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1,
          text: node.getText().replace(/\s+/g, " "),
          claim,
        });
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
  const index = lines.findIndex((line) => line.startsWith(`export function ${marker}`));
  expect(index, `fixture is missing \`export function ${marker}\``).toBeGreaterThan(-1);
  return index + 1;
}

describe("the §52 guard: a fallback on a query envelope", () => {
  let program: ts.Program;

  beforeAll(() => {
    // The REAL tsconfig, so the scan sees what `pnpm typecheck` sees. A whole-program
    // build, paid once, with an explicit and generous timeout for the same reason
    // wireLookupGuard.test.ts has one: a guard that fails on a busy machine is a guard
    // somebody deletes.
    const configPath = resolve(WEB_ROOT, "tsconfig.json");
    const config = ts.readConfigFile(configPath, ts.sys.readFile);
    expect(config.error, "tsconfig.json did not parse").toBeUndefined();
    const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, WEB_ROOT);
    program = ts.createProgram(parsed.fileNames, { ...parsed.options, noEmit: true });
  }, 120_000);

  // ── negative control: it fires on the planted defects ─────────────────────────────

  it("flags every banned shape in the fixture, and only those", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE));
    expect(fixture, `${FIXTURE} is not in the tsconfig program`).toBeDefined();

    const found = findViolations(program, fixture!);

    // Each offending expression sits on the line after its `export function` signature
    // — except the destructured one, which needs a line for the `const { data } = …`.
    expect(found.map((violation) => `${violation.line} ${violation.claim}`)).toEqual([
      `${fixtureLine("bannedBooleanFallback") + 2} a state`,
      `${fixtureLine("bannedBooleanFallbackDestructured") + 2} a state`,
      `${fixtureLine("bannedRenderedCount") + 2} a number`,
    ]);
  });

  it("stays silent on the five safe look-alikes", () => {
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = new Set(findViolations(program, fixture).map((violation) => violation.line));

    // Every one of these is a real site the sweep left alone, and every one of them was
    // flagged by some earlier draft of this rule. If any appears here the guard has
    // become the noisy rule this file exists to avoid — and the noisy rule is the one
    // that gets waived until it protects nothing.
    for (const safe of [
      "safePayloadNull",
      "safeFormDefault",
      "safeLocalConstant",
      "safeGuardedListFallback",
      "safeAbsenceMarker",
    ]) {
      const start = fixtureLine(safe);
      const lines = [...flagged].filter((line) => line >= start && line <= start + 4);
      expect(lines, `${safe} must not be flagged`).toEqual([]);
    }
  });

  it("distinguishes a payload null from an envelope undefined", () => {
    // The single most important property, called out on its own because getting it wrong
    // in the tolerant direction makes the guard useless and getting it wrong in the
    // strict direction makes it unusable. `safePayloadNull` and `bannedRenderedCount`
    // are the SAME `??` against the same query — the only difference is whether the
    // screen refused first.
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = findViolations(program, fixture).map((violation) => violation.line);
    expect(flagged).toContain(fixtureLine("bannedRenderedCount") + 2);
    expect(flagged).not.toContain(fixtureLine("safePayloadNull") + 4);
  });

  // ── the tree ──────────────────────────────────────────────────────────────────────

  it("finds no unexempted violation anywhere in src/", () => {
    const sources = program
      .getSourceFiles()
      .filter(
        (file) =>
          file.fileName.startsWith(resolve(WEB_ROOT, "src") + "/") &&
          // Generated from OpenAPI; it declares types and renders nothing.
          !file.fileName.endsWith("schema.d.ts"),
      );
    // A premise check: if the glob ever stops matching, "no violations" becomes true for
    // the wrong reason and this whole file silently stops testing anything.
    expect(
      sources.length,
      "no src files in the program — the scan is looking nowhere",
    ).toBeGreaterThan(40);

    const violations = sources
      .flatMap((file) => findViolations(program, file))
      // `Object.hasOwn`, not `in`: the site key is built from file paths and source
      // text, so `in` would let a site named `constructor` exempt itself off
      // `Object.prototype` (src/lib/lookup.ts, and the ESLint ban that enforces it).
      .filter((violation) => !Object.hasOwn(EXEMPT, siteKey(violation)));

    expect(
      violations.map(
        (violation) =>
          `${violation.file}:${violation.line}  ${violation.text}  → renders ${violation.claim} ` +
          "the server never sent",
      ),
      "BUILD-LOG §52: loading is a skeleton, failure is a refusal, and neither is a " +
        "number, a state, or an empty state. `query.data` is undefined while the read is " +
        "in flight OR after it failed, so a literal fallback on it states something we do " +
        "not know. Render the pending and failed branches explicitly (Skeleton / " +
        "ProblemNotice) — after `if (q.isPending)` and `if (q.isError)` the checker " +
        "narrows `q.data` and the fallback is no longer needed. For a gated control, use " +
        "`useWriteAccess` (src/lib/api/hooks.ts), which already says \"We could not check\" " +
        "for the failed case.",
    ).toEqual([]);
  });

  it("keeps no exemption that is not still a live violation", () => {
    // A stale exemption is a hole with a comment on it (check_wiring.stale_baseline).
    // The list may only shrink, and only by somebody fixing the site.
    const live = new Set(
      program
        .getSourceFiles()
        .filter((file) => file.fileName.startsWith(resolve(WEB_ROOT, "src") + "/"))
        .flatMap((file) => findViolations(program, file))
        .map(siteKey),
    );

    expect(
      Object.keys(EXEMPT).filter((key) => !live.has(key)),
      "these EXEMPT entries no longer match a violation — delete them",
    ).toEqual([]);
  });
});
