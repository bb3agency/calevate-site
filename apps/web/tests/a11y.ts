import { readdirSync } from "node:fs";
import { join } from "node:path";

import { relPosix } from "./repoPaths";

import axe, { type AxeResults, type Result, type RunOptions } from "axe-core";
import { expect } from "vitest";

/**
 * The accessibility gate: every screen this suite renders is scanned by axe-core.
 *
 * ## Why this exists
 *
 * 26 source files reach for `aria-*` or `role=`. Nothing verified any of it, which makes
 * every one of those attributes the same shape of defect this repo keeps finding — a
 * claim that type-checks while being false. The console is used daily by SMB staff on
 * low-end Android, with imperfect eyesight, in a second or third language; an unlabelled
 * input here is not a compliance checkbox, it is a form nobody can fill in.
 *
 * ## Why axe-core DIRECTLY, and not a matcher wrapper
 *
 * The two conventional wrappers were both rejected, on the dependency grounds
 * `vitest.config.mts` already argues (and hard rule 9 governs):
 *
 * - **`vitest-axe`** — the obvious pick by name, and dead. Last publish 0.1.0, October
 *   2022; it pins `axe-core@^4.4.2` (three years of rules behind) and drags in
 *   `chalk`, `redent`, `lodash-es`, `aria-query` and `dom-accessibility-api`. An
 *   unmaintained package in the test path is the supply-chain surface hard rule 9 is
 *   about, and a stale axe-core is a gate that misses rules it should catch.
 * - **`jest-axe`** — actively maintained (11.0.0, July 2026) but it is a JEST matcher:
 *   it depends on `jest-matcher-utils`, pulling Jest's diff/pretty-format stack into a
 *   repo that has no Jest, plus `chalk` and `lodash.merge`. This suite deliberately
 *   declined `@testing-library/jest-dom` for matcher sugar; taking Jest's matcher
 *   internals for the same reason would be the larger version of that trade.
 *
 * `axe-core` itself has ZERO dependencies, no install scripts, and ships only JS
 * (MPL-2.0, Deque). It was ALREADY in this lockfile at 4.12.1 as a transitive of
 * `eslint-plugin-jsx-a11y` via `eslint-config-next`; declaring it direct deduped the
 * tree to a single 4.13.0 copy and added no new package at all. The wrapper's whole
 * value was `expect(x).toHaveNoViolations()` — one assertion helper, written below in
 * a dozen lines, which also lets the failure name the SCREEN and print the offending
 * HTML rather than a generic matcher dump.
 *
 * ## What this gate does NOT cover — say it here rather than let a green tick imply it
 *
 * Automated rules catch roughly a third of real barriers (Deque's own figure). This
 * gate cannot see: whether focus order is sane, whether an error moves focus, whether a
 * modal traps focus, whether link text makes sense out of context, or whether colour is
 * the ONLY signal for a state. Those are checked by hand, and a green run here is not a
 * claim about any of them.
 *
 * Two of those blind spots turned out to be hiding real defects, and both now have tests
 * of their own rather than a note in this paragraph — which is what a named blind spot is
 * FOR. `aiQuota.test.tsx` pins the money dialog's focus trap and its restore (it had
 * neither, under `aria-modal="true"`), and `dashboard.test.tsx` pins that the `Skeleton`
 * announces itself (96 sites rendered `<div aria-hidden>` and said nothing at all). Both
 * were green here throughout: axe checks markup that exists, never an announcement that
 * never happens or a Tab that goes somewhere it should not.
 *
 * Three MECHANICAL limits are worth knowing before trusting a green tick:
 *
 * - **`placeholder` satisfies axe's `label` rule.** An input whose only name is its
 *   placeholder PASSES, because the placeholder feeds the accessible-name computation —
 *   even though the text vanishes on typing, which is WCAG 3.3.2's whole complaint. This
 *   was confirmed here: removing a real `aria-label` and leaving the placeholder kept
 *   the gate green. A labelled-looking input is therefore not proof of a labelled input.
 * - **Page-level rules cannot fire.** `region`, `landmark-one-main`,
 *   `page-has-heading-one`, `bypass`, `document-title` and `html-has-lang` are
 *   properties of a DOCUMENT; the sweep scans a detached container, so axe reports them
 *   inapplicable. A skip link and a `<main>` are outside what this can check.
 * - **Pages are scanned without their layouts** (that is how the App Router composes
 *   them, and how the rest of this suite renders them). The two realm shells are swept
 *   as screens of their own so the navigation is covered, but a defect that only appears
 *   when a page sits INSIDE its shell — a duplicated landmark, a heading level that only
 *   skips once composed — is not visible here.
 *
 * All three close the same way: a browser-mode run (`@axe-core/playwright`) against the
 * real composed document. That is a bigger change than this slice, and pretending
 * otherwise in a comment is how a gate comes to be trusted for more than it does.
 */

/**
 * Rules axe cannot evaluate under jsdom, disabled so the gate does not report a
 * confident PASS on a check that never ran.
 *
 * Keyed by rule id with what closes it, in the manner of
 * `scripts/check_redaction_exposure.KNOWN_SAFE_FIELDS`: narrow, reasoned, and a visible
 * diff to change.
 */
export const JSDOM_BLIND_RULES: Record<string, string> = {
  "color-contrast": (
    "jsdom implements no layout and no `document.createRange()`, so axe cannot resolve " +
    "a computed background or measure text — it reports `incomplete`, and forcing it " +
    "makes jsdom log 'HTMLCanvasElement.getContext() not implemented' on every render. " +
    "Deque documents jsdom as unsupported for this rule (dequelabs/axe-core#595) and " +
    "jest-axe disables it for the same reason. CLOSED BY: contrast is a property of the " +
    "Tailwind token palette in `src/app/globals.css`, not of any one screen, so it is " +
    "checked once against the palette rather than per render — either in a browser-mode " +
    "run (`@axe-core/playwright`) if this suite ever gains one, or by hand against the " +
    "tokens. Not closeable inside jsdom at all."
  ),
};

/**
 * Violations accepted for now, keyed `screen::rule-id` — NEVER by screen alone.
 *
 * The reason for the compound key is the one `check_redaction_exposure` gives for
 * exempting `Model.field` rather than `Model`: an exemption written at the coarser
 * grain silently covers the NEXT defect somebody adds to the same screen. A screen
 * exempted from `label` must still fail on `button-name`.
 *
 * Every entry states what it is and WHAT CLOSES IT. An entry with no closing condition
 * is a bug being renamed, and `staleExemptions()` below fails the build when an entry
 * stops matching anything, so this table cannot quietly accumulate dead weight.
 */
export const KNOWN_A11Y_EXEMPTIONS: Record<string, string> = {};

/** axe configuration shared by every scan, so no call site can quietly widen it. */
const RUN_OPTIONS: RunOptions = {
  // Only violations. `incomplete` is axe asking a human to look, which is not something
  // a CI gate can answer, and `passes` is a large object we never read.
  resultTypes: ["violations"],
  rules: Object.fromEntries(
    Object.keys(JSDOM_BLIND_RULES).map((id) => [id, { enabled: false }]),
  ),
};

/** Every `screen::rule` key that fired during this process, for the staleness check. */
const seenKeys = new Set<string>();

export interface A11yFinding {
  key: string;
  rule: string;
  impact: string;
  help: string;
  helpUrl: string;
  nodes: string[];
}

function toFindings(results: AxeResults, screen: string): A11yFinding[] {
  return results.violations.map((v: Result) => ({
    key: `${screen}::${v.id}`,
    rule: v.id,
    impact: v.impact ?? "unknown",
    help: v.help,
    helpUrl: v.helpUrl,
    // `failureSummary` is axe's own "Fix any of the following" prose — the thing that
    // actually tells the next reader what to change, rather than just what is wrong.
    nodes: v.nodes.map((n) => `${n.html}\n      ${n.failureSummary ?? ""}`),
  }));
}

/**
 * Scan a rendered subtree and return the violations that are not exempt.
 *
 * `screen` is a stable label (usually the route path) that keys the exemption table and
 * names the screen in the failure, because a suite-wide gate that fails with only a rule
 * id makes the reader hunt for which of forty screens broke.
 */
export async function findA11yViolations(
  container: Element,
  screen: string,
): Promise<A11yFinding[]> {
  const results = await axe.run(container, RUN_OPTIONS);
  const findings = toFindings(results, screen);
  for (const f of findings) seenKeys.add(f.key);
  return findings.filter((f) => !Object.hasOwn(KNOWN_A11Y_EXEMPTIONS, f.key));
}

/** Format findings the way a person fixing them needs to read them. */
export function formatFindings(findings: A11yFinding[], screen: string): string {
  const body = findings
    .map(
      (f) =>
        `  [${f.impact}] ${f.rule} — ${f.help}\n` +
        `    ${f.helpUrl}\n` +
        f.nodes.map((n) => `    ${n}`).join("\n"),
    )
    .join("\n\n");
  return (
    `${findings.length} accessibility violation(s) on ${screen}:\n\n${body}\n\n` +
    `Fix the markup, or — if this is genuinely a false positive or a deferred, ` +
    `understood gap — add "${findings[0]?.key}" to KNOWN_A11Y_EXEMPTIONS in ` +
    `tests/a11y.ts with a reason and what closes it.`
  );
}

/**
 * Exemption keys that no longer match anything the suite rendered.
 *
 * A waiver that has stopped firing is either fixed (delete it) or pointing at a screen
 * that no longer exists (delete it) — and either way, leaving it teaches the next reader
 * that the table is decorative. Same role as `check_coverage_ratchet.stale_waivers`.
 * Only meaningful after a FULL suite run, so the assertion lives in a test that the
 * whole run reaches, and it reads `seenKeys` accumulated across this process.
 */
export function staleExemptions(): string[] {
  return Object.keys(KNOWN_A11Y_EXEMPTIONS).filter((key) => !seenKeys.has(key));
}

export function observedKeys(): ReadonlySet<string> {
  return seenKeys;
}

/**
 * Scan a rendered subtree and FAIL the test if anything non-exempt is wrong.
 *
 * The one assertion every screen in `tests/a11y.test.tsx` goes through. Takes an
 * `Element` rather than a `RenderResult` so it can be pointed at a dialog, a panel or a
 * table that only exists after an interaction — axe scans the subtree it is given, and
 * several of the defects worth catching (an error summary, an opened confirm panel)
 * are not on screen at first paint.
 */
export async function expectNoA11yViolations(container: Element, screen: string): Promise<void> {
  assertScreenRendered(container, screen);
  const findings = await findA11yViolations(container, screen);
  expect(findings, findings.length ? formatFindings(findings, screen) : screen).toEqual([]);
}

/**
 * Refuse to scan a screen that did not actually render.
 *
 * THE failure mode of an accessibility suite, and the reason this function exists
 * rather than a comment asking people to be careful. `axe.run` on an empty container
 * returns zero violations and the test goes green — so a screen whose fixture is wrong,
 * whose query 503'd, or which is still showing its skeleton reports PERFECT
 * ACCESSIBILITY. Seven of the screens in the first draft of the sweep did exactly that.
 * A gate that cannot tell "nothing is wrong" from "nothing is there" licenses precisely
 * the claim this repo keeps catching.
 *
 * The floor is deliberately crude — real text, and something a person can operate or
 * navigate by. It is not a content assertion (the other 43 test files do that job
 * properly); it only has to be strong enough that an empty, skeleton or refusal render
 * cannot pass for a screen.
 *
 * §52 note: loading is a skeleton and failure is a refusal, and BOTH are legitimate
 * screens with their own accessibility. They are simply not what the sweep is scanning,
 * because a refusal's markup is one `role="alert"` that the same component renders
 * everywhere; the barriers live in the populated state.
 */
export function assertScreenRendered(container: Element, screen: string): void {
  // NON-EMPTY `alt` COUNTS AS TEXT, and that is a correction to what this measures
  // rather than a relaxation of the floor.
  //
  // The auth frame used to render the product name as the literal string "Calevate";
  // it now renders the wordmark image, whose `alt` is that same string. Nothing on
  // `invite/page.tsx` or `c/page.tsx` became less perceivable — a screen reader
  // announces exactly what it did before — but `textContent` stopped seeing it, and both
  // screens dropped under the 40-character floor and failed. A guard that treats a
  // labelled image as "nothing is there" is measuring the DOM's text nodes, not the
  // thing it exists to detect.
  //
  // It cannot be gamed into vacuity: `alt=""` is how a DECORATIVE image declares itself
  // and contributes nothing here, so a skeleton full of unlabelled placeholders still
  // fails, and the `operable === 0` half of the floor is untouched.
  const alts = Array.from(container.querySelectorAll("img[alt]"))
    .map((img) => img.getAttribute("alt") ?? "")
    .filter((alt) => alt.trim().length > 0)
    .join(" ");
  const text = `${container.textContent ?? ""} ${alts}`.replace(/\s+/g, " ").trim();
  const operable = container.querySelectorAll(
    "a[href], button, input, select, textarea, table, h1, h2, h3",
  ).length;
  if (text.length < 40 || operable === 0) {
    throw new Error(
      `${screen} rendered nothing to scan (${text.length} chars of text, ${operable} ` +
        `operable/landmark elements). axe reports zero violations on an empty container, ` +
        `so this would have passed VACUOUSLY. Fix the screen's route fixture in ` +
        `tests/a11y.test.tsx so it renders its populated state.`,
    );
  }
  // The generic network refusal means the fixture missed a route the screen needs; the
  // screen is then rendering `ProblemNotice`, not itself.
  if (text.includes("Something went wrong.")) {
    throw new Error(
      `${screen} rendered the generic failure notice instead of the screen — a route in ` +
        `its fixture is missing or wrong, so the scan would cover an error panel rather ` +
        `than the screen. Fix the fixture in tests/a11y.test.tsx.`,
    );
  }
}

/**
 * Route screens deliberately NOT swept, with the reason — the coverage guard's waiver
 * list, keyed by the route path exactly as `routePagesOnDisk()` reports it.
 *
 * Same discipline as the violation exemptions: an entry names one screen and says what
 * closes it. This is the list that stops the sweep from silently falling behind the
 * router, which is the failure mode a hand-written sweep always has.
 */
export const UNSWEPT_SCREENS: Record<string, string> = {
  ...Object.fromEntries(
    ["credits", "usage", "spend", "invoice"].map((retired) => [
      `c/[slug]/${retired}/page.tsx`,
      // D-525 folded the four money screens into `c/[slug]/billing` and left these four
      // files as SERVER REDIRECTS (`lib/billingRedirect.ts`) so that every link already
      // in the world still lands on the tab it meant. A redirect renders no markup at
      // all — `redirect()` answers the request — so there is no subtree for axe to scan,
      // and rendering one under jsdom throws `NEXT_REDIRECT` rather than producing a
      // page. What they redirect TO is swept: `c/[slug]/billing/page.tsx`.
      // CLOSED BY: deleting these files, which is a decision about old links and not
      // about accessibility.
      "a server redirect into c/[slug]/billing (D-525) — it renders no markup to scan",
    ]),
  ),
  "layout.tsx": (
    "the ROOT layout renders `<html lang=\"en\">` and `<body>`, which React Testing " +
    "Library cannot mount into a container div — there is no subtree for axe to scan. " +
    "What it carries that matters (`lang`, and the document title from Next metadata) " +
    "are DOCUMENT-level properties that jsdom cannot see from a detached render either. " +
    "CLOSED BY: a browser-mode or Playwright run, which would evaluate `html-has-lang`, " +
    "`document-title`, `bypass` and `region` against a real document. Until then the " +
    "`lang` attribute is held by src/app/layout.tsx and reviewed by eye."
  ),
};

/**
 * Every route file the App Router will actually render — `page.tsx` AND `layout.tsx`.
 *
 * Layouts are included because they are not decoration: the two realm shells carry the
 * navigation, the sidebar collapse and the mobile drawer, which is where the keyboard
 * and screen-reader barriers on EVERY screen live. A sweep of pages alone would report
 * green on a console whose only nav was unreachable.
 *
 * Read off DISK rather than listed by hand, because the whole point of the guard is to
 * notice a file nobody remembered to add. Route groups (`(auth)`) and dynamic segments
 * are kept verbatim so the key a developer sees in a failure is the path they can find
 * in the tree.
 */
export function routePagesOnDisk(appDir: string = join(process.cwd(), "src", "app")): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name === "page.tsx" || entry.name === "layout.tsx")
        // `relPosix`: these become route paths compared against the screen list.
        out.push(relPosix(appDir, full));
    }
  };
  walk(appDir);
  // An empty walk is the vacuous pass this guard exists to avoid: a wrong cwd would
  // report "no unswept screens" forever while covering nothing. `import.meta.url` was
  // the first attempt and is not a file URL under jsdom, which is exactly how a path
  // bug gets in here — so the floor is asserted rather than assumed.
  if (out.length === 0) {
    throw new Error(
      `no page.tsx found under ${appDir} — the a11y coverage guard is looking in the ` +
        `wrong place and would pass without checking anything`,
    );
  }
  return out.sort();
}
