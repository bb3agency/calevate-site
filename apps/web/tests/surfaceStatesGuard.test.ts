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
 * ═══ THE SUBJECT ═════════════════════════════════════════════════════════════════════
 *
 * One mechanism, because every one of those defects was the same two characters. A
 * TanStack `UseQueryResult.data` is `T | undefined`, and that `undefined` means exactly
 * one thing: WE HAVE NOT GOT AN ANSWER — the request is in flight, or it failed. Every
 * rule below is a different way of spending that `undefined` as though it were a fact.
 *
 * A MUTATION's `data` is deliberately NOT the subject. There, `undefined` means "the
 * user has not asked yet", which is true, and `{save.data && <notice/>}` is the correct
 * rendering of it — a guard that did not separate the two envelopes would fire on every
 * mutation result in the app and be deleted inside a week.
 *
 * ═══ WHAT IS CHECKED ═════════════════════════════════════════════════════════════════
 *
 * Four rules. The first two are unconditional; the last two are gated, and the gate is
 * what makes them decidable at all — see the next section.
 *
 *  1. **A boolean fallback on an envelope read, anywhere.** `?? false` / `?? true` /
 *     `Boolean(q.data?.flag)`. A boolean has no absent value, so the fallback does not
 *     defer the question, it ANSWERS it — and the screen renders that answer as a state.
 *     This is literally the shape that produced §52's worst instance
 *     (`platform?.outbound_halted ?? false`), and `Boolean(...)` is the same statement
 *     with different punctuation: `Boolean(me.data?.impersonating)` said "you are not
 *     impersonating" over a dead `/v1/me`.
 *  2. **A manufactured literal in a JSX CHILD position.** `{q.data?.count ?? 0}` is the
 *     number, the state or the empty collection printed on the screen as a fact, with no
 *     branch between it and the pixel. `?? 5430` was this.
 *  3. **A manufactured literal ANYWHERE, in a component that never refuses.** `const
 *     rows = agents.data ?? []` feeding a `<select>` whose only other option is "save
 *     leads, don't call".
 *  4. **A positive truthiness test that decides whether a CONTROL is offered, in a
 *     component that never refuses.** `{q.data && <button/>}`, `q.data?.[0] ? … : …`,
 *     and the early-return form where the fall-through is the dangerous branch. This is
 *     the shape that offered an irreversible tenant erasure while stating that none had
 *     been filed.
 *
 * "Manufactured literal" means a number, `true`/`false`, `[]` or `{}` — a value. NOT a
 * string, NOT `null`, NOT `undefined`: `?? "—"` and `?? null` claim absence, which is
 * the truth when we do not know, and banning them would push authors toward inventing
 * something instead.
 *
 * ═══ THE GATE, AND WHY RULES 3 AND 4 NEEDED ONE ══════════════════════════════════════
 *
 * Rules 3 and 4 only fire when the component **never consults that query's failure
 * state** — no `isError`, no `error`, no `status`, anywhere in the function that
 * declared it.
 *
 * That gate is the whole reason they are decidable. `const rows = board.data ?? []` is
 * CORRECT in `admin/health/page.tsx`, where a `ProblemNotice` sits above the table, and
 * it is a LIE on a screen with no error branch — same characters, opposite meaning. What
 * separates them is not the expression, it is whether the failed read has anywhere of
 * its own to go. Asking the component instead of the expression is the one question that
 * distinguishes them without reimplementing branch dominance.
 *
 * THIS FILE PREVIOUSLY REJECTED THAT GATE, and the rejection was right at the time and
 * is worth reading before widening this again. Measured then: flagging every non-boolean
 * literal fallback gave 22 hits of which ~20 were correct code; adding this gate got it
 * to 12 hits of which 2 were correct. 12 hits is a fine rule and a terrible EXEMPT list,
 * and the slice that wrote this guard owned none of those 12 screens — so the honest
 * options were a rule that shipped with ten permanent excuses on it, or a narrower rule
 * that shipped with none. It chose the narrower rule and wrote down exactly what it was
 * giving up. **The treadmill was a property of the backlog, not of the rule**, and Part
 * 10 of the hardening plan is the slice that owns the screens. Measured on the tree the
 * day this widened: 9 hits, 9 of them real, all fixed in the same change, EXEMPT empty.
 *
 * Two further narrowings keep rule 4 at that rate, and both are §52's own line:
 *
 * * **Positive polarity only.** `if (!q.data) return <refusal/>` is the CORRECT spelling
 *   of the same test — the author is asking the §52 question and answering it. So is
 *   `q.data !== undefined && …`, which is how four screens fail closed on a permission
 *   check. Only the positive test treats "we do not know" as "no".
 * * **A control, not a sentence.** A branch that decides whether a `<button>`, `<form>`,
 *   `<select>`, `<input>`, `<label>`, `<a>`/`<Link>` or an `onClick` reaches the DOM is
 *   deciding what the client may DO, and a control that silently vanishes leaves them
 *   unable to act and unable to ask why. A branch that only decides whether a sentence
 *   is printed is a sentence we do not have. `{me.data?.impersonating && <p>…</p>}` is
 *   the second kind and stays out.
 *
 * ═══ WHAT IS **NOT** CHECKED, AND WHY ════════════════════════════════════════════════
 *
 * Stated plainly, because a guard that implies more than it verifies is the §52 defect
 * one level up — a confident claim from something that did not actually read.
 *
 * * **"Loading is a skeleton" is not decidable here.** Whether a component renders a
 *   `<Skeleton>` versus nothing versus a stale number, on which branch, is a rendering
 *   question. Per-screen tests own it (dashboard.test.tsx, ops.test.tsx, campaigns.test.tsx)
 *   — and one of the nine sites in this wave, the dashboard's "Spend this month" tile
 *   rendering `—` forever off `formatINR(usage.data?.…)`, is invisible to every rule
 *   above precisely because `—` is an honest absence marker. Only its test can see it.
 * * **"Failure is a refusal you can act on" is not decidable here.** That a `ProblemNotice`
 *   appears is checkable per screen; that its wording tells an owner what to do is a
 *   judgement no parser makes. The gate above checks that the component ASKED about the
 *   failure, never that it said something useful.
 * * **A component that refuses in one place and lies in another.** The gate is
 *   per-query, per-declaring-function, and it is satisfied by a single `isError` read.
 *   That is the price of not computing branch dominance, and it is why rules 1 and 2
 *   stay ungated: the shapes with no honest reading at all keep firing regardless.
 *
 *   RE-MEASURED, so the next reader inherits the evidence and not the conclusion:
 *   removing the gate on this tree gives **43 hits**, and the reason it is not a
 *   narrowing problem is visible in them — several are the LADDER ITSELF
 *   (`c/[slug]/campaign-review:152 if (hold.error || !hold.data) return <ProblemNotice/>`,
 *   `…/prompt:939 catalogue.error || !catalogue.data ? <ProblemNotice/>`,
 *   `…/[tenantId]:554 agents.isLoading || !agents.data ? <Skeleton/>`). An ungated rule
 *   would flag its own remedy, which is worse than a rule with a known hole. And
 *   "dominance" is the wrong shape of analysis for this codebase's idiom anyway: the
 *   correct spelling here is a `ProblemNotice` rendered as a SIBLING of the data branch,
 *   not before it, so nothing dominates anything and the property to compute would be
 *   mutual exclusion across JSX children — with the refusal frequently living in a child
 *   component the scan cannot follow. What actually closes it is the screen's own test,
 *   which is where D-132 said the two escaping sabotages were caught.
 * * **`if (!data) return null`** — §52 names it, and it is not distinguishable from a
 *   legitimate early return without knowing what the caller renders instead.
 * * **A determined evasion.** Copy `q.data` into an `any`, or into a helper in another
 *   module, and this loses the trail; so does passing the envelope itself to a child,
 *   which the scan treats as "checked elsewhere" rather than guess. Like the wire-lookup
 *   guard beside it, this catches the shape people write by COPYING, which is the shape
 *   that actually recurs.
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
 * Explicit, and generous, for the reason this file already gives about its `beforeAll`:
 * a whole-tree type-aware walk takes seconds, vitest's default `it` timeout is five, and
 * the suite runs its files in parallel — so on a loaded box the honest cost lands on the
 * wrong side of a default nobody chose for THIS test. A guard that fails when the machine
 * is busy is a guard somebody deletes for flakiness, which is a worse outcome than a slow
 * one. Measured here at ~4s alone and ~5.2s under the full parallel suite.
 */
const SCAN_TIMEOUT_MS = 60_000;

/**
 * Sites that violate the rule and are NOT this slice's to fix, each with what closes it.
 *
 * Keyed by file AND by the offending expression's text — never by file alone, which
 * would exempt the next fallback somebody adds to the same screen, and never by line,
 * which drifts on the first edit above it. Same doctrine as
 * `check_redaction_exposure.KNOWN_SAFE_FIELDS`. The list may only SHRINK: an entry that
 * no longer matches a real violation fails this suite, so a fixed site cannot leave a
 * permanent excuse behind.
 *
 * EMPTY, and that is the point of the wave that widened this guard: the one entry it
 * used to carry (the integrations payload offer, `me.data?.permissions?.includes(…) ??
 * false`) moved to `useWriteAccess`, which already answers "We could not check whether
 * you can …" for exactly that case. A widened rule that shipped with nine new excuses on
 * it would have been worth less than the narrow one it replaced.
 */
const EXEMPT: Record<string, string> = {};

/** Which of the four rules fired, and what the screen claims because of it. */
interface Violation {
  file: string;
  line: number;
  text: string;
  /** §52's own words for the thing being invented, or what goes missing. */
  claim: string;
  /** The sentence printed to whoever broke it — the fix, not the diagnosis. */
  fix: string;
}

/** `{file}  {text}` — the key `EXEMPT` is written in, and what a failure prints. */
function siteKey(violation: Violation): string {
  return `${violation.file}  ${violation.text}`;
}

const REFUSE_FIRST =
  "Render the failed branch explicitly (ProblemNotice / a sentence naming what could " +
  "not be read) — after `if (q.isPending)` and `if (q.isError)` the checker narrows " +
  "`q.data` and the fallback is no longer needed. For a gated control, use " +
  '`useWriteAccess` (src/lib/api/hooks.ts), which already says "We could not check".';

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

/**
 * A QUERY specifically — a read, not a write.
 *
 * `refetch` without `mutate`. The distinction carries the whole difference between "we
 * have not got an answer" and "the user has not asked yet"; see the header.
 */
function isQueryEnvelope(checker: ts.TypeChecker, type: ts.Type): boolean {
  const names = new Set(checker.getPropertiesOfType(type).map((property) => property.getName()));
  return (
    names.has("data") && names.has("isError") && names.has("isPending") && names.has("refetch") &&
    !names.has("mutate")
  );
}

function includesUndefined(type: ts.Type): boolean {
  const parts = type.isUnion() ? type.types : [type];
  return parts.some((part) => (part.flags & ts.TypeFlags.Undefined) !== 0);
}

function includesBoolean(type: ts.Type): boolean {
  const parts = type.isUnion() ? type.types : [type];
  return parts.some((part) => (part.flags & ts.TypeFlags.BooleanLike) !== 0);
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

// ─── the gate: does the component ever ask whether this read FAILED? ─────────────────

/** Every member of the envelope that answers "did this fail, and how". */
const FAILURE_MEMBERS = new Set([
  "isError",
  "error",
  "status",
  "failureReason",
  "isLoadingError",
  "isRefetchError",
]);

/** The nearest function that owns a declaration — the component, in practice. */
function owningFunction(node: ts.Node): ts.Node | null {
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (
      ts.isFunctionDeclaration(current) ||
      ts.isFunctionExpression(current) ||
      ts.isArrowFunction(current) ||
      ts.isMethodDeclaration(current) ||
      ts.isSourceFile(current)
    ) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

/**
 * Does the function that declared `query` ever consult its failure — or hand the whole
 * envelope to somebody who might?
 *
 * "Hand it on" counts as refused ON PURPOSE. `<FacetPanel error={facets.error} …/>` and
 * `applyState(state)` both put the envelope somewhere this scan cannot follow, and a
 * guard that guessed in the strict direction there would be demanding a refusal the
 * child already renders. Guessing in the tolerant direction costs a missed site; the
 * other way costs the rule its credibility, which is the more expensive of the two.
 */
/**
 * Memoised per declaration, and not as an optimisation flourish: the answer is a property
 * of the declaring function, every `X.data` in a screen asks for the same one, and
 * without this the walk is quadratic in the size of a component. Measured on the 1.8k-line
 * campaigns page it took the whole-tree scan from ~13s to under 2s — and a guard slow
 * enough to time out on a loaded CI box is a guard that gets deleted for flakiness.
 */
const REFUSAL_CACHE = new WeakMap<ts.VariableDeclaration, boolean>();

function refusesSomewhere(checker: ts.TypeChecker, declaration: ts.VariableDeclaration): boolean {
  const cached = REFUSAL_CACHE.get(declaration);
  if (cached !== undefined) return cached;
  const answer = computeRefusesSomewhere(checker, declaration);
  REFUSAL_CACHE.set(declaration, answer);
  return answer;
}

function computeRefusesSomewhere(
  checker: ts.TypeChecker,
  declaration: ts.VariableDeclaration,
): boolean {
  const scope = owningFunction(declaration);
  if (!scope || !ts.isIdentifier(declaration.name)) return true;
  const symbol = checker.getSymbolAtLocation(declaration.name);
  if (!symbol) return true;

  let refuses = false;
  const visit = (node: ts.Node): void => {
    if (refuses) return;
    if (
      ts.isPropertyAccessExpression(node) &&
      ts.isIdentifier(node.expression) &&
      checker.getSymbolAtLocation(node.expression) === symbol
    ) {
      if (FAILURE_MEMBERS.has(node.name.text)) refuses = true;
      // Do not descend into the property name; do walk the rest of the expression.
      ts.forEachChild(node, visit);
      return;
    }
    if (
      ts.isIdentifier(node) &&
      node !== declaration.name &&
      checker.getSymbolAtLocation(node) === symbol
    ) {
      const parent = node.parent;
      const isReceiver = ts.isPropertyAccessExpression(parent) && parent.expression === node;
      if (!isReceiver) refuses = true; // handed on — see the docstring
    }
    ts.forEachChild(node, visit);
  };
  visit(scope);
  return refuses;
}

/**
 * The first unnarrowed read of a query whose component never refuses, inside `node`.
 *
 * Returns the variable's name so the failure message can say WHICH read to ladder,
 * which is the one thing the author needs and the expression text does not always show.
 */
function unrefusedQueryRead(checker: ts.TypeChecker, node: ts.Node): string | null {
  let found: string | null = null;

  const visit = (child: ts.Node): void => {
    if (found !== null) return;
    if (
      ts.isPropertyAccessExpression(child) &&
      child.name.text === "data" &&
      ts.isIdentifier(child.expression) &&
      isQueryEnvelope(checker, checker.getTypeAtLocation(child.expression)) &&
      includesUndefined(checker.getTypeAtLocation(child))
    ) {
      const declaration = checker.getSymbolAtLocation(child.expression)?.declarations?.[0];
      if (
        declaration &&
        ts.isVariableDeclaration(declaration) &&
        !refusesSomewhere(checker, declaration)
      ) {
        found = child.expression.text;
        return;
      }
    }
    ts.forEachChild(child, visit);
  };

  visit(node);
  return found;
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

// ─── rule 4: a branch that decides whether a CONTROL is offered ──────────────────────

/** Elements a client ACTS through. A branch over these decides what they may do. */
const CONTROL_TAGS = new Set([
  "button",
  "input",
  "select",
  "textarea",
  "form",
  "a",
  "label",
  "Link",
]);

/**
 * …and the handler props, because half this app's controls are wrapped
 * (`<FilterChip onClick={…}/>`, `<CallControl onCall={…}/>`). A capitalised component is
 * opaque to this scan, so the prop is the only visible evidence that the thing inside
 * the branch is pressable. `onCall`-style names are missed, deliberately: guessing from
 * a naming convention is how a guard starts being wrong in ways nobody can predict.
 */
const CONTROL_HANDLERS = new Set(["onClick", "onChange", "onSubmit", "onInput", "onKeyDown"]);

function offersAControl(nodes: readonly (ts.Node | undefined)[]): boolean {
  let found = false;
  const visit = (node: ts.Node): void => {
    if (found) return;
    if (
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      CONTROL_TAGS.has(node.tagName.getText())
    ) {
      found = true;
      return;
    }
    if (ts.isJsxAttribute(node) && ts.isIdentifier(node.name) && CONTROL_HANDLERS.has(node.name.text)) {
      found = true;
      return;
    }
    ts.forEachChild(node, visit);
  };
  for (const node of nodes) if (node) visit(node);
  return found;
}

/**
 * The statements after an early-returning `if` — its implicit else.
 *
 * Without this the lifecycle screen reads as harmless: `if (existing) return <Card/>` has
 * no else clause at all, and the erasure FORM it falls through to is a sibling statement
 * rather than a branch. The fall-through is the branch; it is just spelled with a return.
 */
function fallThroughOf(statement: ts.IfStatement): readonly ts.Statement[] {
  const block = statement.parent;
  if (!ts.isBlock(block)) return [];
  const index = block.statements.indexOf(statement);
  return index < 0 ? [] : block.statements.slice(index + 1);
}

/**
 * The condition of a branch whose arms differ in what the client may DO, or null.
 *
 * Positive polarity only: `!q.data` and `q.data !== undefined` are the author asking the
 * §52 question, and four screens fail closed on exactly that spelling.
 */
function controlDecidingCondition(node: ts.Node): ts.Expression | null {
  let condition: ts.Expression | null = null;
  let arms: readonly (ts.Node | undefined)[] = [];

  if (ts.isIfStatement(node)) {
    condition = node.expression;
    arms = [node.thenStatement, node.elseStatement, ...fallThroughOf(node)];
  } else if (ts.isConditionalExpression(node)) {
    condition = node.condition;
    arms = [node.whenTrue, node.whenFalse];
  } else if (
    ts.isBinaryExpression(node) &&
    node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
  ) {
    condition = node.left;
    arms = [node.right];
  }
  if (!condition || !offersAControl(arms)) return null;

  let subject: ts.Expression = condition;
  while (ts.isParenthesizedExpression(subject)) subject = subject.expression;
  if (ts.isPrefixUnaryExpression(subject) && subject.operator === ts.SyntaxKind.ExclamationToken) {
    return null;
  }
  if (
    ts.isBinaryExpression(subject) &&
    (subject.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsEqualsToken ||
      subject.operatorToken.kind === ts.SyntaxKind.EqualsEqualsEqualsToken ||
      subject.operatorToken.kind === ts.SyntaxKind.ExclamationEqualsToken ||
      subject.operatorToken.kind === ts.SyntaxKind.EqualsEqualsToken)
  ) {
    return null;
  }
  return subject;
}

/**
 * `const existing = filed.data?.[0]` — one hop, and only one.
 *
 * The `?.[0]` blind spot is almost always spelled across two lines, because the value
 * needs a name before it can be branched on. Following the initializer of a local whose
 * type STILL CARRIES `undefined` keeps that hop honest: `const refused = me.data !==
 * undefined && …` is a boolean and does not propagate, which is what keeps the four
 * fail-closed permission screens out of this rule. Two hops are not followed — at that
 * point it is dataflow analysis, and the shape people copy is one hop.
 */
function derivedFromUnrefusedQuery(
  checker: ts.TypeChecker,
  sourceFile: ts.SourceFile,
): Map<ts.Symbol, string> {
  const carried = new Map<ts.Symbol, string>();
  const visit = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      const type = checker.getTypeAtLocation(node.name);
      if (!isServerEnvelope(checker, type) && includesUndefined(type)) {
        const query = unrefusedQueryRead(checker, node.initializer);
        const symbol = checker.getSymbolAtLocation(node.name);
        if (query !== null && symbol) carried.set(symbol, query);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return carried;
}

function findViolations(program: ts.Program, sourceFile: ts.SourceFile): Violation[] {
  const checker = program.getTypeChecker();
  const found: Violation[] = [];
  const carried = derivedFromUnrefusedQuery(checker, sourceFile);

  // Rule 4's node can be a whole `<Card>`, so the quoted text is clipped. It is a
  // LABEL, not the evidence — the file and line are the evidence — and an EXEMPT key
  // holding four hundred characters of JSX is a key nobody can type or diff.
  const quote = (node: ts.Node): string => {
    const text = node.getText().replace(/\s+/g, " ");
    return text.length <= 100 ? text : `${text.slice(0, 100)}…`;
  };

  const record = (node: ts.Node, claim: string, fix: string): void => {
    found.push({
      file: relative(WEB_ROOT, sourceFile.fileName),
      line: sourceFile.getLineAndCharacterOfPosition(node.getStart()).line + 1,
      text: quote(node),
      claim,
      fix,
    });
  };

  const visit = (node: ts.Node): void => {
    // ── rules 1 and 2: a fallback that manufactures a value ──────────────────────────
    if (
      ts.isBinaryExpression(node) &&
      (node.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken ||
        node.operatorToken.kind === ts.SyntaxKind.BarBarToken)
    ) {
      const claim = manufacturedClaim(node.right);
      // A boolean is always in scope; anything else only when it is the pixel itself.
      const unconditional = claim === "a state" || isJsxChild(node);
      if (claim && unconditional && readsUnnarrowedEnvelope(checker, node.left)) {
        record(node, claim, `renders ${claim} the server never sent. ${REFUSE_FIRST}`);
      } else if (claim && !unconditional) {
        // ── rule 3: the same literal, off a pixel, in a screen that never refuses ────
        const query = unrefusedQueryRead(checker, node.left);
        if (query !== null) {
          record(
            node,
            claim,
            `substitutes ${claim} for a read that may have failed, and nothing in this ` +
              `component ever consults \`${query}.isError\`. ${REFUSE_FIRST}`,
          );
        }
      }
    }

    // ── rule 1, second spelling: Boolean(q.data?.flag) is `?? false` ─────────────────
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "Boolean" &&
      node.arguments.length === 1
    ) {
      const argument = node.arguments[0];
      const type = checker.getTypeAtLocation(argument);
      // The FLAG, not the envelope: `Boolean(q.data)` asks whether the answer arrived,
      // which is the honest question and this repo's settled spelling for it.
      if (includesBoolean(type) && includesUndefined(type) && readsUnnarrowedEnvelope(checker, argument)) {
        record(
          node,
          "a state",
          "renders a state the server never sent — `Boolean(x)` maps our ignorance onto " +
            `\`false\` exactly as \`?? false\` does. ${REFUSE_FIRST}`,
        );
      }
    }

    // ── rule 4: a branch deciding whether a control is offered ───────────────────────
    const condition = controlDecidingCondition(node);
    if (condition) {
      let query: string | null = null;
      if (ts.isIdentifier(condition)) {
        const symbol = checker.getSymbolAtLocation(condition);
        query = (symbol && carried.get(symbol)) ?? null;
      } else {
        query = unrefusedQueryRead(checker, condition);
      }
      if (query !== null) {
        record(
          node,
          "an absent control",
          `withdraws a control on a read that may have failed, and nothing in this ` +
            `component ever consults \`${query}.isError\` — so the client is offered ` +
            `neither the action nor a reason. ${REFUSE_FIRST}`,
        );
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

    // Each offending expression sits a fixed distance below its `export function`
    // signature — the offset is spelled per marker rather than assumed, because the
    // two-line shapes (`const first = …` then `if (first)`) are the point of the rule.
    expect(found.map((violation) => `${violation.line} ${violation.claim}`)).toEqual([
      `${fixtureLine("bannedBooleanFallback") + 2} a state`,
      `${fixtureLine("bannedBooleanFallbackDestructured") + 2} a state`,
      `${fixtureLine("bannedRenderedCount") + 2} a number`,
      `${fixtureLine("bannedBooleanCoercion") + 2} a state`,
      `${fixtureLine("bannedUnrefusedListFallback") + 2} an empty state`,
      `${fixtureLine("bannedVanishingControl") + 2} an absent control`,
      `${fixtureLine("bannedFirstRowFallthrough") + 3} an absent control`,
    ]);
  }, SCAN_TIMEOUT_MS);

  it("stays silent on the eleven safe look-alikes", () => {
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
      "safePresenceTest",
      "safeNegativeGuard",
      "safeMutationNotYetRun",
      "safeProseWithoutControl",
      "safeFailClosedPermissionCheck",
      "safeRefusedControl",
    ]) {
      const start = fixtureLine(safe);
      const lines = [...flagged].filter((line) => line >= start && line <= start + 8);
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

  it("distinguishes a component that refuses from one that does not", () => {
    // The gate, on its own, for the same reason: `safeGuardedListFallback` and
    // `bannedUnrefusedListFallback` are the SAME `?? []` against the same query, and the
    // only difference is whether anything in the component reads `board.error`. Rules 3
    // and 4 are worth nothing if this pair ever collapses into one answer.
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = findViolations(program, fixture).map((violation) => violation.line);
    expect(flagged).toContain(fixtureLine("bannedUnrefusedListFallback") + 2);
    expect(flagged).not.toContain(fixtureLine("safeGuardedListFallback") + 2);
  });

  it("distinguishes a withdrawn control from a sentence we do not have", () => {
    // `bannedVanishingControl` and `safeProseWithoutControl` are the same `&&` on the
    // same query; only the contents of the branch differ. If this pair collapses, rule 4
    // either loses the defect it was written for or starts demanding a refusal for every
    // conditional sentence in the app.
    const fixture = program.getSourceFile(resolve(WEB_ROOT, FIXTURE))!;
    const flagged = findViolations(program, fixture).map((violation) => violation.line);
    expect(flagged).toContain(fixtureLine("bannedVanishingControl") + 2);
    expect(flagged).not.toContain(fixtureLine("safeProseWithoutControl") + 2);
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
        (violation) => `${violation.file}:${violation.line}  ${violation.text}  → ${violation.fix}`,
      ),
      "BUILD-LOG §52: loading is a skeleton, failure is a refusal, and neither is a " +
        "number, a state, or an empty state. `query.data` is undefined while the read is " +
        "in flight OR after it failed, so anything a screen states or withdraws on the " +
        "strength of it is a claim we did not earn.",
    ).toEqual([]);
  }, SCAN_TIMEOUT_MS);

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
  }, SCAN_TIMEOUT_MS);
});
