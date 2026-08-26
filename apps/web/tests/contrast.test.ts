import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import { relPosix } from "./repoPaths";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * WCAG 1.4.3 Contrast (Minimum), Level AA — checked against the PALETTE, once.
 *
 * `tests/a11y.ts` disables axe's `color-contrast` rule and says exactly why and exactly
 * what closes it:
 *
 *     jsdom implements no layout and no `document.createRange()`, so axe cannot resolve
 *     a computed background or measure text … CLOSED BY: contrast is a property of the
 *     Tailwind token palette in `src/app/globals.css`, not of any one screen, so it is
 *     checked once against the palette rather than per render — either in a browser-mode
 *     run (`@axe-core/playwright`) if this suite ever gains one, or by hand against the
 *     tokens.
 *
 * This is that check, and it is here rather than in a browser run because a browser run
 * cannot be a gate: it needs `next build`, a port and a Chromium binary, none of which
 * `make web-check` has. The arithmetic needs none of them — the ratio is a pure function
 * of two hex values, and the palette is thirty lines of CSS.
 *
 * **The browser run happened anyway, and is what produced this file.** axe-core in real
 * Chromium over the built app reported `color-contrast` on SEVEN of nine documents —
 * every one of them `text-ink-faint`, at `text-xs` or `text-[11px]`, plus the marketing
 * page's two `bg-brand` call-to-action links. Measured: `--text-faint` was `#94a3b8`,
 * which is **2.56:1** on `--surface` and 2.46:1 on `--app`, against a 4.5:1 requirement.
 * That is not a near miss; it is roughly half the required separation on the token this
 * console uses for every hint, caption and secondary label — the text a first-time user
 * reads to work out what a control does, on a low-end Android in daylight (BRD's users).
 *
 * ## What is checked, and what the thresholds are
 *
 * Every INK token against every BACKGROUND it can legally sit on, in BOTH themes, at
 * 4.5:1 — the small-text threshold. Nothing in this app uses these tokens at 24px, or at
 * 18.66px bold, so the 3:1 large-text allowance never applies and is deliberately not
 * offered: an exemption nobody can currently earn is an exemption somebody will
 * eventually claim by accident.
 *
 * `--brand` is checked at 4.5:1 against white for the same reason. It is documented in
 * `components/ui.tsx` as "the medallion and fill colour, not a button", and the marketing
 * page had put white text on it twice — 3.38:1. The rule here is what makes that comment
 * enforceable rather than advisory.
 *
 * ## What is NOT checked
 *
 * Ink on a non-token background — `bg-rose-50`, `bg-emerald-100`, the status badges — is
 * out of scope, because those are Tailwind palette literals chosen per site rather than
 * tokens, and enumerating them here would be a second, drifting copy of the design. The
 * browser run above is what sees those, and it reported none.
 */

const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CSS = readFileSync(resolve(WEB_ROOT, "src/app/globals.css"), "utf8");

/** WCAG 2.x relative luminance — sRGB, the 0.03928/12.92 piecewise transfer. */
function relativeLuminance(hex: string): number {
  const channel = (value: number): number => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const h = hex.replace("#", "");
  const r = Number.parseInt(h.slice(0, 2), 16);
  const g = Number.parseInt(h.slice(2, 4), 16);
  const b = Number.parseInt(h.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio, rounded to two places the way a report quotes it. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const ratio = (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  return Math.round(ratio * 100) / 100;
}

/**
 * One theme's token values, read out of the stylesheet rather than restated here.
 *
 * A copy of the palette in this file would pass forever after somebody edited the real
 * one, which is the failure mode every "pinned constant" test has. The light block is
 * `:root { … }` and the dark block is the `.dark` override; each token is taken from the
 * LAST assignment before the boundary, so the override wins where there is one.
 */
function tokens(theme: "light" | "dark"): Record<string, string> {
  const darkAt = CSS.indexOf(".dark");
  expect(darkAt, "globals.css has no `.dark` block — this test is reading the wrong file")
    .toBeGreaterThan(-1);
  const scope = theme === "light" ? CSS.slice(0, darkAt) : CSS;
  const found: Record<string, string> = {};
  for (const match of scope.matchAll(/--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    found[match[1]] = match[2].toLowerCase();
  }
  return found;
}

/** Text tokens, and every surface each of them is allowed to sit on. */
const INK_ON: Record<string, string[]> = {
  text: ["surface", "app"],
  "text-muted": ["surface", "app"],
  "text-faint": ["surface", "app"],
};

/** The AA threshold for text below 18.66px bold / 24px regular — i.e. all of ours. */
const AA_SMALL_TEXT = 4.5;

/**
 * Files that pair `bg-brand` with `text-white` and are NOT text — keyed by path, with the
 * reason. The list may only shrink; the test below fails on an entry that stops matching.
 */
// EMPTY, AND IT GOT THAT WAY THE RIGHT WAY. Its one entry argued for the client shell's
// 36px brand medallion — `bg-brand` with `text-white` colouring a `<Mic>` glyph, judged
// against WCAG 1.4.11's 3:1 for non-text rather than 1.4.3's 4.5:1. That medallion no
// longer exists: the real logo is dark-green ink on transparency and sits on the surface,
// not in a filled chip (`components/brand.tsx` says why putting it in one would render
// green on green). No fill, no exemption. The staleness check below is what insisted —
// this dict cannot outlive the thing it excuses, which is the whole point of keying it by
// path. Leave the mechanism here for the next argued-for fill.
const BRAND_FILL_EXEMPT: Record<string, string> = {};

/**
 * The ONE `sr-only`-input label still without a focus ring, and why it is not fixed here.
 *
 * Same rule, same waiver discipline as `BRAND_FILL_EXEMPT` above: keyed by path, carrying
 * its reason, and checked below for staleness so it cannot outlive the defect. This is a
 * LIVE WCAG 2.4.7 failure and not an argued-for exception — the only entry that has ever
 * been allowed to mean "not yet".
 */
const SR_ONLY_FOCUS_EXEMPT: Record<string, string> = {
  "src/app/c/[slug]/agents/DirectionChoice.tsx":
    "the inbound/outbound radio cards on the agent screen. Identical F78 failure to the " +
    "five fixed alongside this guard, and the fix is the same class string — but the " +
    "label styles it inline, so it cannot be fixed from a shared constant, and this file " +
    "belongs to a lane editing `agents/**` concurrently. Whoever lands next in that " +
    "directory: add `has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong " +
    "has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app` to the " +
    "<label> className and delete this entry — the staleness test below will insist.",
};

// `relPosix`: `BRAND_FILL_EXEMPT` is keyed on forward slashes, so on Windows every
// argued-for exemption stopped matching and the guard reported settled violations.
function relativeToWeb(file: string): string {
  return relPosix(WEB_ROOT, file);
}

/** Every `.tsx`/`.ts` under `src/`, so the scan cannot quietly miss a new screen. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name) && !entry.name.endsWith("schema.d.ts")) out.push(full);
    }
  };
  walk(resolve(WEB_ROOT, "src"));
  return out;
}

describe("the design tokens meet WCAG 1.4.3 AA", () => {
  it("reads a palette, rather than passing on an empty one", () => {
    // The premise. A renamed file or a changed token syntax would otherwise make every
    // assertion below vacuously true — the "nothing is wrong" versus "nothing is there"
    // distinction `tests/a11y.ts::assertScreenRendered` exists for.
    for (const theme of ["light", "dark"] as const) {
      const palette = tokens(theme);
      for (const name of ["text", "text-muted", "text-faint", "surface", "app", "brand"]) {
        expect(palette[name], `${theme}: --${name} not found in globals.css`).toMatch(
          /^#[0-9a-f]{6}$/,
        );
      }
    }
    // …and the two themes must actually differ, or the "dark" reads are the light ones.
    expect(tokens("light").surface).not.toEqual(tokens("dark").surface);
  });

  it("puts every ink token on every surface it is used on at 4.5:1 or better", () => {
    const failures: string[] = [];
    for (const theme of ["light", "dark"] as const) {
      const palette = tokens(theme);
      for (const [ink, surfaces] of Object.entries(INK_ON)) {
        for (const surface of surfaces) {
          const ratio = contrastRatio(palette[ink], palette[surface]);
          if (ratio < AA_SMALL_TEXT) {
            failures.push(
              `${theme}: --${ink} (${palette[ink]}) on --${surface} (${palette[surface]}) ` +
                `= ${ratio}:1, below ${AA_SMALL_TEXT}:1`,
            );
          }
        }
      }
    }
    expect(
      failures,
      "WCAG 1.4.3 Contrast (Minimum), Level AA. These are the tokens the console writes " +
        "its hints, captions and secondary labels in, at 12px, for SMB staff on low-end " +
        "Android — so the small-text threshold is the one that applies and there is no " +
        "large-text allowance to fall back on. Darken the ink or lighten the surface in " +
        "src/app/globals.css.",
    ).toEqual([]);
  });

  it("keeps the three ink tokens distinguishable from each other", () => {
    // The reason the fix is not "set every ink token to black". Three tokens that all
    // pass and all look the same is a hierarchy the design no longer has, and the next
    // person restores it by picking a lighter grey — reintroducing exactly this defect.
    for (const theme of ["light", "dark"] as const) {
      const palette = tokens(theme);
      for (const [a, b] of [
        ["text", "text-muted"],
        ["text-muted", "text-faint"],
      ] as const) {
        expect(palette[a], `${theme}: --${a} and --${b} are the same colour`).not.toEqual(
          palette[b],
        );
        expect(
          contrastRatio(palette[a], palette[b]),
          `${theme}: --${a} and --${b} are too close to read as a hierarchy`,
        ).toBeGreaterThan(1.2);
      }
    }
  });

  /**
   * The palette rule above, enforced where it is actually broken — at the call site.
   *
   * `--brand` passing or failing is arithmetic; whether a screen PUTS WHITE TEXT ON IT is
   * a fact about fifteen class strings, and that is where the defect lived: four
   * marketing call-to-action links and eleven console buttons rested or hovered on
   * `bg-brand` with `text-white`, at 3.38:1. `components/ui.tsx` had already written the
   * rule in prose above `PRIMARY_BUTTON` — "#16A05D (brand) is the medallion and fill
   * colour, not a button" — and prose is what fifteen call sites had drifted from.
   *
   * A source scan rather than a render check, for the reason `tests/responsive.test.ts`
   * gives about `min-w-`: the class string IS the decision, jsdom cannot compute a
   * background from it, and a browser run cannot be a gate.
   */
  it("puts white text on no unsuffixed --brand background", () => {
    const files = sourceFiles();
    expect(files.length, "no source files — this scan is looking nowhere").toBeGreaterThan(40);
    const offenders: string[] = [];
    for (const file of files) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          if (!/(?<![-\w:])(?:hover:)?bg-brand(?=[ "'`])/.test(line)) return;
          if (!/text-white/.test(line)) return;
          const key = `${relativeToWeb(file)}`;
          if (Object.hasOwn(BRAND_FILL_EXEMPT, key)) return;
          offenders.push(`${key}:${index + 1}`);
        });
    }
    expect(
      offenders,
      "white text on `bg-brand` is 3.38:1 — below WCAG 1.4.3 AA. `bg-brand-strong` is " +
        "6.58:1 and is what `PRIMARY_BUTTON` rests on; `hover:bg-brand-deep` is its " +
        "documented hover. Keep `bg-brand` for fills, bars and medallions, which carry no " +
        "text and are held to 1.4.11's 3:1 instead.",
    ).toEqual([]);
  });

  it("keeps no brand-fill exemption that has stopped applying", () => {
    // A waiver that no longer matches is a hole with a comment on it — the same rule
    // `tests/a11y.ts::staleExemptions` and `check_wiring.stale_baseline` apply.
    const live = new Set(
      sourceFiles()
        .filter((file) =>
          readFileSync(file, "utf8")
            .split("\n")
            .some(
              (line) =>
                /(?<![-\w:])(?:hover:)?bg-brand(?=[ "'`])/.test(line) && /text-white/.test(line),
            ),
        )
        .map(relativeToWeb),
    );
    expect(
      Object.keys(BRAND_FILL_EXEMPT).filter((key) => !live.has(key)),
      "these BRAND_FILL_EXEMPT entries no longer match anything — delete them",
    ).toEqual([]);
  });

  it("puts no text-brand on a bg-brand-soft ground", () => {
    /*
     * The sibling of the `bg-brand` scan above, and it caught a live one.
     *
     * `--brand` on `--brand-soft` is 3.08:1. That pairing was the "completed" pill on the
     * calls screen and one medallion on the client home — small text on the busiest
     * screen the client console has. Thirty other `bg-brand-soft` sites already wrote
     * `text-brand-strong` (6.01:1 on the same ground), so those two were outliers rather
     * than a convention, and the palette-level guard in `contrastTokens.test.ts` could
     * not see them: the tokens are each fine, it is the COMBINATION that is not.
     *
     * Scanned per line, like the `bg-brand` check, because that is where the pairing is
     * written. A className split across lines would slip through — accepted for the same
     * reason it is accepted there: every occurrence in this tree is on one line, and a
     * scan that tried to reassemble JSX would be a parser with its own bugs.
     */
    const files = sourceFiles();
    expect(files.length, "no source files — this scan is looking nowhere").toBeGreaterThan(40);
    const offenders: string[] = [];
    for (const file of files) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          if (!/bg-brand-soft/.test(line)) return;
          if (!/(?<![-\w:])text-brand(?=[ "'`])/.test(line)) return;
          offenders.push(`${relativeToWeb(file)}:${index + 1}`);
        });
    }
    expect(
      offenders,
      "`text-brand` on `bg-brand-soft` is 3.08:1 — below WCAG 1.4.3 AA. Use " +
        "`text-brand-strong` (6.01:1), which is what every other bg-brand-soft site uses.",
    ).toEqual([]);
  });

  /**
   * THE SEAM BETWEEN THIS FILE AND `tests/a11y.ts`, closed at the source.
   *
   * Everything above checks the PALETTE, and `tests/a11y.ts` disables axe's
   * `color-contrast` rule under jsdom and defers to it. Both are right, and between them
   * there was a hole big enough to drive a screen through: a file that writes its ink in
   * RAW TAILWIND LITERALS is in neither test's field of view. The palette check never
   * sees `text-slate-500` because it is not a token; axe never sees it because axe cannot
   * measure contrast without layout. So both gates stayed green while
   * `c/[slug]/integrations/page.tsx` — the one route the design-token migration did not
   * reach — rendered thirty spans of ink at **2.56:1** in light and **3.75:1** in dark
   * (`globals.css:39,88` record both measurements, from the browser axe run that produced
   * this file), including the sentence warning a client that their deliveries are failing.
   *
   * ## The rule, stated precisely
   *
   * Under `src/app/`, a `text-<grey>-<n>` literal is a violation UNLESS the same line also
   * sets a `bg-<grey>-<n>` literal. That exception is not a loophole, it is the boundary
   * of what this guard can honestly claim:
   *
   * - Ink with no background of its own INHERITS the token surface (`--surface`/`--app`),
   *   so the pairing is knowable from this file and the ink token is the answer. That is
   *   the failure class, and it is the whole of `/integrations`'s defect.
   * - Ink that brings its own literal ground is a status badge, and this file's own header
   *   already puts those out of scope by name ("Ink on a non-token background —
   *   `bg-rose-50`, `bg-emerald-100`, the status badges"). Enumerating them here would be
   *   a second, drifting copy of the design, and the browser axe run is what sees them —
   *   it reported none.
   *
   * ## What this deliberately does NOT cover
   *
   * - **Non-grey ink literals** (`text-amber-700`, `text-emerald-800`). They are used as
   *   SEMANTIC colour — a warning, a verdict — for which this palette has no token, and
   *   banning them would push screens back to plain ink and lose the meaning.
   * - **Background, border and divider literals.** Those are 1.4.11 (3:1, non-text) rather
   *   than 1.4.3, and the token migration on `/integrations` moved them anyway.
   * - **A className split across several lines**, for the same reason the two scans above
   *   accept that limit: every occurrence in this tree is on one line, and a scan that
   *   tried to reassemble JSX would be a parser with its own bugs.
   * - **Anything outside `src/app/`.** `components/ui.tsx` holds the `StatusBadge` palette
   *   and `invoiceDocument.tsx` prints on paper; both are argued for where they live.
   */
  it("writes no raw grey ink literal on a token surface under src/app", () => {
    // The families Tailwind ships as neutrals. `slate` is the one this repo drifted into,
    // and the other four are here so the next drift is caught on its first line.
    const GREY_INK = /(?<![-\w:])(?:dark:)?text-(?:slate|gray|zinc|neutral|stone)-\d{2,3}\b/;
    const OWN_GROUND = /(?<![-\w:])(?:dark:)?bg-(?:slate|gray|zinc|neutral|stone)-\d{2,3}\b/;

    const appFiles = sourceFiles().filter((file) =>
      relativeToWeb(file).startsWith("src/app/"),
    );
    // The premise, for the reason every scan in this suite states one: a scan that has
    // stopped matching is indistinguishable from a clean tree.
    expect(appFiles.length, "no files under src/app — this scan is looking nowhere")
      .toBeGreaterThan(20);

    const offenders: string[] = [];
    for (const file of appFiles) {
      readFileSync(file, "utf8")
        .split("\n")
        .forEach((line, index) => {
          if (!GREY_INK.test(line)) return;
          if (OWN_GROUND.test(line)) return;
          offenders.push(`${relativeToWeb(file)}:${index + 1}`);
        });
    }
    expect(
      offenders,
      "WCAG 1.4.3 Contrast (Minimum), Level AA — and a gate blind spot rather than a " +
        "styling preference: the palette check above cannot see a literal, and " +
        "`tests/a11y.ts` disables axe's color-contrast rule under jsdom, so ink written " +
        "this way is measured by nothing. `text-slate-500` is 3.75:1 on --surface in " +
        "dark and `text-slate-400` is 2.56:1 in light (globals.css:39,88). Use the ink " +
        "tokens, which ARE checked in both themes above: `text-ink` for a heading or a " +
        "value, `text-ink-muted` for body copy and secondary labels, `text-ink-faint` " +
        "for a 12px hint or caption. A status badge that brings its own `bg-` literal is " +
        "out of scope and passes — see this test's header for why.",
    ).toEqual([]);
  });

  /**
   * WCAG 2.4.7 Focus Visible (AA), failure technique F78 — guarded at the source, because
   * nothing else in this suite can.
   *
   * An `<input className="sr-only">` inside a styled `<label>` is the custom radio-card
   * idiom, and it deletes the browser's own focus ring. If the label does not draw a
   * replacement, a keyboard user tabbing into the group sees NOTHING move. The two sites
   * in this repo were the AI-model picker (money) and the messaging-consent answer (law),
   * and both shipped with `checked` and `hover` states and no focus treatment at all.
   *
   * Why a source scan and not axe: axe cannot evaluate a focus indicator — it is a
   * property of a computed style in a state jsdom cannot enter — so a render test would
   * pass on the broken markup, which is exactly what `tests/a11y.test.tsx` did.
   *
   * The scan pairs each `sr-only` input with the nearest `<label` above it and reads the
   * text between them, which is where a JSX className sits — plus, where that className
   * interpolates `${SOME_CONSTANT}`, the constant's own text from the same file. Most of
   * these cards share a `CHOICE_CARD` string, so a scan that only read the opening tag
   * would report every one of them as broken however it was fixed. It does NOT follow a
   * constant IMPORTED from another module: chasing identifiers across files is a
   * type-checker, and no call site in this tree does that today.
   */
  it("draws a focus ring on every label that hides its own input", () => {
    const files = sourceFiles();
    const found: string[] = [];
    const offenders: string[] = [];
    const HAS_RING = /has-\[:focus-visible\]|focus-within:/;

    for (const file of files) {
      const text = readFileSync(file, "utf8");
      // File-level (and function-level) class constants, so `${CHOICE_CARD}` can be
      // resolved to the string it actually holds.
      const consts = new Map<string, string>();
      for (const c of text.matchAll(/\bconst\s+(\w+)\s*=\s*([\s\S]*?);/g)) {
        consts.set(c[1], c[2]);
      }
      // Every visually-hidden FORM CONTROL. `sr-only` on a <span> is a text alternative
      // and takes no focus, so it is not this rule's business.
      for (const match of text.matchAll(
        /<input\b[^>]*className=(?:"sr-only"|\{[^}]*sr-only[^}]*\})/g,
      )) {
        const at = match.index;
        const labelAt = text.lastIndexOf("<label", at);
        const key = `${relativeToWeb(file)}:${text.slice(0, at).split("\n").length}`;
        found.push(key);
        if (labelAt === -1) {
          offenders.push(`${key} (no enclosing <label> found)`);
          continue;
        }
        const opening = text.slice(labelAt, at);
        const viaConstant = [...opening.matchAll(/\$\{(\w+)/g)].some((ref) =>
          HAS_RING.test(consts.get(ref[1]) ?? ""),
        );
        if (HAS_RING.test(opening) || viaConstant) continue;
        if (Object.hasOwn(SR_ONLY_FOCUS_EXEMPT, relativeToWeb(file))) continue;
        offenders.push(key);
      }
    }

    // The premise: a scan that has stopped matching is indistinguishable from a clean
    // tree. Six of these cards exist today across the two realms.
    expect(found.length, "no sr-only form inputs found — this scan is looking nowhere")
      .toBeGreaterThanOrEqual(6);
    expect(
      offenders,
      "WCAG 2.4.7 Focus Visible (Level AA), failure technique F78: an `sr-only` input " +
        "removes the browser's focus ring, so its <label> must draw one. Add " +
        "`has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-strong " +
        "has-[:focus-visible]:ring-offset-2 has-[:focus-visible]:ring-offset-app` to the " +
        "label's className — the same ring `components/actionButton.tsx` uses, so this " +
        "console has one focus style and not two. axe cannot catch this: it does not " +
        "evaluate focus indicators, and jsdom has no layout to evaluate them in.",
    ).toEqual([]);
  });

  it("keeps no sr-only focus exemption that has stopped applying", () => {
    // The same rule `BRAND_FILL_EXEMPT` is held to, and it matters more here: this
    // waiver covers a LIVE accessibility failure, so it must disappear the moment the
    // file it names is fixed — otherwise the next `sr-only` input added to that file
    // inherits a hole nobody argued for.
    const HAS_RING = /has-\[:focus-visible\]|focus-within:/;
    const stillBroken = new Set(
      sourceFiles()
        .filter((file) => {
          const text = readFileSync(file, "utf8");
          if (!/<input\b[^>]*className=(?:"sr-only"|\{[^}]*sr-only[^}]*\})/.test(text)) {
            return false;
          }
          return !HAS_RING.test(text);
        })
        .map(relativeToWeb),
    );
    expect(
      Object.keys(SR_ONLY_FOCUS_EXEMPT).filter((key) => !stillBroken.has(key)),
      "these SR_ONLY_FOCUS_EXEMPT entries name a file that now draws a focus ring (or " +
        "no longer hides an input) — delete them, the waiver has done its job",
    ).toEqual([]);
  });

  it("refuses white text on --brand, which is a fill and not a button", () => {
    // `components/ui.tsx` argues this in prose above `PRIMARY_BUTTON`: #16A05D is the
    // medallion and fill colour, #0F6B3D is the button. The marketing page had put white
    // on the fill twice (3.38:1), which is the drift that comment exists to prevent —
    // this is the check that makes it enforceable.
    const light = tokens("light");
    expect(
      contrastRatio("#ffffff", light["brand-strong"]),
      "--brand-strong must carry white text, since PRIMARY_BUTTON does exactly that",
    ).toBeGreaterThanOrEqual(AA_SMALL_TEXT);
    expect(
      contrastRatio("#ffffff", light.brand),
      "--brand does NOT carry white text at AA — use --brand-strong for anything with a " +
        "label on it, and keep --brand for fills, medallions and bars",
    ).toBeLessThan(AA_SMALL_TEXT);
  });
});
