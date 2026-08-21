import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { relPosix } from "./repoPaths";

import { describe, expect, it } from "vitest";

/**
 * The mobile-layout gate: the rules a responsive sweep established, pinned so they cannot
 * quietly come undone.
 *
 * ## Why these are SOURCE checks and not layout measurements
 *
 * The defects these guard were found by MEASUREMENT, not by reading CSS — a real Chromium
 * laid out all 47 swept screens against the production Tailwind bundle at 320/360/414/1280
 * and reported which elements crossed the viewport, which text painted outside its box,
 * which controls were under 44px and which form fields were under the 16px that makes iOS
 * zoom. That harness found what this file protects: an unwrapped table whose third column
 * was unreachable, a grid column whose 288px min-content sat in a 238px box, a 256px
 * `min-w` floor in a 254px card, and 122 zooming inputs.
 *
 * It is deliberately NOT the gate. Reproducing it needs a browser binary, and the one on
 * this machine is a different build from the one `playwright-core` resolves by default —
 * a gate whose failure mode is "the browser was missing, so nothing ran" is the vacuous
 * pass `tests/a11y.ts` refuses at length, and it would report a confident green on a
 * console nobody measured. So the browser stays the INSTRUMENT, and what it taught is
 * written down here as rules that hold statically and run everywhere the rest of the
 * suite runs.
 *
 * What that trade costs, stated rather than implied: this file cannot catch a NEW screen
 * that overflows for a new reason. It catches the classes of defect that were found and
 * fixed, which is what stops a fix from being undone — not a claim that the console is
 * still measured. Re-measuring is a browser run, and it is what should be repeated when
 * the design changes.
 */

const SRC = join(process.cwd(), "src");

/** Every `.tsx` under `src/`, so a rule cannot be dodged by adding a file. */
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
  // The same floor `routePagesOnDisk` asserts: a wrong cwd would otherwise make every
  // rule below pass by checking nothing at all.
  if (out.length === 0) {
    throw new Error(`no .tsx found under ${SRC} — this gate is looking in the wrong place`);
  }
  return out;
}

const FILES = sourceFiles();
const read = (f: string): string => readFileSync(f, "utf8");
// `relPosix`, for `authnSourceGuards`' reason: these paths are compared and reported
// against forward-slash literals.
const rel = (f: string): string => relPosix(process.cwd(), f);

describe("form controls do not trigger the iOS zoom", () => {
  /**
   * Mobile Safari zooms the viewport when a text control under 16px takes focus and does
   * not zoom back out on blur. 122 controls across the console were at 12–14px, because
   * `text-sm`/`text-xs` is a desktop density. The fix is one base rule rather than a
   * utility on each control — see the comment on it in `globals.css` for why, including
   * why it has to be UNLAYERED to beat Tailwind's `text-sm`.
   */
  const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");

  it("globals.css raises text-entry controls to 16px on a coarse pointer", () => {
    const block = /@media \(pointer: coarse\) \{[\s\S]*?\n\}/.exec(css)?.[0] ?? "";
    expect(block, "no `@media (pointer: coarse)` block in globals.css").not.toEqual("");
    expect(block).toMatch(/input:not\(\[type="checkbox"\]\):not\(\[type="radio"\]\)/);
    expect(block).toMatch(/font-size:\s*16px/);
  });

  it("keeps that rule out of a cascade layer, where `text-sm` would beat it", () => {
    // `@layer base { … }` would lose to every Tailwind utility regardless of specificity,
    // and the rule would be decorative. Unlayered declarations win over layered ones.
    const layered = /@layer[^{]*\{[\s\S]*@media \(pointer: coarse\)/.test(css);
    expect(layered, "the coarse-pointer rule was moved inside an @layer, which silently disables it").toBe(false);
  });

  it("gives checkbox and radio a 24px box instead", () => {
    const block = /@media \(pointer: coarse\) \{[\s\S]*?\n\}/.exec(css)?.[0] ?? "";
    expect(block).toMatch(/input\[type="checkbox"\]/);
    expect(block).toMatch(/min-width:\s*24px/);
    expect(block).toMatch(/min-height:\s*24px/);
  });
});

describe("tap targets", () => {
  /**
   * Measured at 26–36px across the console — above WCAG 2.2 AA's 24px floor (2.5.8) and
   * below the 44px an actual finger wants (2.5.5 / Apple HIG). Every field-class constant
   * carries the raise, because these files each define their OWN rather than importing
   * the shared `FIELD` — pre-existing drift that this sweep did not restyle, but a tap
   * target is not a matter of taste, so the one rule applies to all of them.
   */
  const FIELD_CONSTANT = /^const (FIELD|FIELD_BASE)\s*=\s*$\n\s*("(?:[^"\\]|\\.)*")/gm;

  it("every field-class constant carries the touch minimum height", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      for (const [, name, literal] of read(file).matchAll(FIELD_CONSTANT)) {
        if (!literal.includes("touch:min-h-11")) offenders.push(`${rel(file)} — ${name}`);
      }
    }
    expect(
      offenders,
      `these field classes are missing \`touch:min-h-11\`, so on a phone they render ` +
        `under the 44px tap target:\n  ${offenders.join("\n  ")}\n` +
        `Add it to the class string. \`touch:\` is the \`pointer: coarse\` variant declared ` +
        `in globals.css, so desktop density is unaffected.`,
    ).toEqual([]);
  });

  /**
   * The narrowest control shape, which neither rule above reaches.
   *
   * The two rules above check the NAMED constants — `FIELD`, `PRIMARY_BUTTON` and their
   * siblings. The leads table's inline status and owner selects are neither: they carried
   * their own literal, `px-1 py-0.5 text-xs`, which is 12px text in a 16px line box plus
   * 2px each side — about 20px, under SC 2.5.8's 24px AA floor. Both are WRITES, and a
   * mis-tap on the status select moves a lead to a stage nobody chose; `RowFailure` only
   * speaks after a FAILED edit, never after a wrong one.
   *
   * `py-0.5` and no lower, deliberately: `py-1` computes to exactly the 24px minimum, and
   * a rule that also failed the controls which pass is one people learn to widen rather
   * than obey.
   */
  const HAIRLINE_CONTROL = /text-xs/;
  const THIN_PADDING = /\bpy-0\.5\b/;
  const HAS_FLOOR = /min-h-|\bh-\d/;

  it("no pressable control is text-xs with hairline padding and no height floor", () => {
    const cramped: string[] = [];
    for (const file of FILES) {
      const source = read(file).split("\n");
      source.forEach((line, i) => {
        // `className=` on an element, or the body of a shared class constant — the leads
        // one is a constant, so a check that only read JSX would have missed the exact
        // control the finding named.
        if (!/className|^\s*["`]/.test(line)) return;
        if (!HAIRLINE_CONTROL.test(line) || !THIN_PADDING.test(line)) return;
        if (HAS_FLOOR.test(line)) return;
        const above = source.slice(Math.max(0, i - 3), i + 1).join(" ");
        const isControl =
          /<(select|button|input|a)\b|Select\b/.test(above) ||
          /^(export )?const [A-Z][A-Z0-9_]* =/.test(source[Math.max(0, i - 1)]) ||
          /^(export )?const [A-Z][A-Z0-9_]* =/.test(line);
        // A `<span>` badge at this size is text, not a target; SC 2.5.8 is about targets.
        if (isControl) cramped.push(`${rel(file)}:${i + 1} — ${line.trim()}`);
      });
    }
    expect(
      cramped,
      `these pressable controls render around 20px tall, under WCAG 2.2 SC 2.5.8's 24px ` +
        `minimum:\n  ${cramped.join("\n  ")}\n` +
        `Add \`touch:min-h-11\` (the coarse-pointer variant in globals.css) or widen the ` +
        `vertical padding.`,
    ).toEqual([]);
  });

  it("the shared button classes carry it too", () => {
    const ui = read(join(SRC, "components", "ui.tsx"));
    for (const name of [
      "PRIMARY_BUTTON",
      "PRIMARY_BUTTON_SM",
      "SECONDARY_BUTTON",
      "SECONDARY_BUTTON_SM",
      "DANGER_BUTTON",
      "FIELD",
    ]) {
      const literal = new RegExp(`export const ${name} =\\s*\\n?\\s*"([^"]*)"`).exec(ui)?.[1] ?? "";
      expect(literal, `${name} not found in components/ui.tsx`).not.toEqual("");
      expect(literal, `${name} lost its touch tap-target minimum`).toContain("touch:min-h-11");
    }
  });
});


/**
 * Blank every comment line, keeping the array length so indices stay meaningful.
 *
 * Handles the two shapes this codebase uses: `//` line comments (including the
 * `// eslint-disable-next-line` directives that sit between a wrapper and its child) and
 * `/* ... *\/` blocks, whether one line or many. Deliberately NOT a parser — a regex that
 * understood JSX would be a bigger thing to trust than the rule it serves.
 */
function blankComments(lines: string[]): string[] {
  let inBlock = false;
  return lines.map((line) => {
    const trimmed = line.trim();
    if (inBlock) {
      if (trimmed.includes("*/")) inBlock = false;
      return "";
    }
    if (trimmed.startsWith("/*") || trimmed.startsWith("{/*")) {
      if (!trimmed.includes("*/")) inBlock = true;
      return "";
    }
    if (trimmed.startsWith("//")) return "";
    return line;
  });
}

/** The nearest `count` non-blank lines above `index`, closest first. */
function previousCodeLines(code: string[], index: number, count: number): string[] {
  const out: string[] = [];
  for (let i = index - 1; i >= 0 && out.length < count; i -= 1) {
    if (code[i].trim() !== "") out.push(code[i]);
  }
  return out;
}

describe("nothing is pinned wider than the narrowest phone", () => {
  /**
   * `min-w-[16rem]` is 256px, and at 320px the content box inside a card is 254px. Every
   * OTHER `min-w-[…]` in this app sits inside an `overflow-x-auto` wrapper, where a
   * minimum is the entire point: the table keeps its shape and the wrapper scrolls. The
   * three that did not were form controls in a `flex-wrap` row, so the floor had nothing
   * to scroll and simply pushed the row past the card.
   *
   * The rule is therefore not "no minimums" but "a minimum either scrolls or waits for a
   * breakpoint that can honour it".
   *
   * `<ScrollRegion>` counts as a scroll container because it IS one — it is the component
   * every table wrapper in the console was moved onto, and it carries `overflow-x-auto`
   * plus the focusability that a bare wrapper was missing (see the keyboard rule below).
   * Matching only the raw utility would have flagged every correct table the moment the
   * shape was hoisted into a component, which is the reading-its-own-fix-as-a-violation
   * failure the comment below already guards against once.
   */
  it("every min-w- utility either scrolls or is gated behind a breakpoint", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      const lines = read(file).split("\n");
      const code = blankComments(lines);
      lines.forEach((line, i) => {
        for (const match of line.matchAll(/(^|[\s"'`])(min-w-\[[^\]]+\])/g)) {
          // A responsive prefix (`sm:min-w-[…]`) is the fix, and shows up as the char
          // before the utility being `:` rather than whitespace or a quote.
          const prefixed = /[a-z0-9]:$/.test(line.slice(0, match.index! + match[1].length));
          if (prefixed) continue;
          // A scroll container on this line, or on one of the few CODE lines above it,
          // is the other legitimate case.
          //
          // "The line above" was too literal, and the legal documents proved it: their
          // table wrapper carries `overflow-x-auto` on line 116 and the `min-w-[36rem]`
          // lands on line 130, with a twelve-line accessibility comment in between
          // explaining the focusable-region waiver. Correct markup, flagged as an
          // overflow, because a comment sat where the guard expected code.
          //
          // Comments are blanked IN PLACE rather than stripped, so reported line numbers
          // still point at the real line — the same trade-off, for the same reason, as
          // `_code_only()` in tests/shared_state_assertion_guard_test.py, which exists
          // because that guard once flagged the prose of a comment explaining a fix it
          // had itself prompted. A check that reads its own documentation as a violation
          // is a check people turn off.
          const near = [code[i], ...previousCodeLines(code, i, 6)].join(" ");
          if (/overflow-x-auto|overflow-auto|overflow-x-scroll|<ScrollRegion\b/.test(near)) continue;
          offenders.push(`${rel(file)}:${i + 1} — ${match[2]}`);
        }
      });
    }
    expect(
      offenders,
      `these fixed minimum widths are neither inside a horizontal scroll container nor ` +
        `gated behind a breakpoint, so they overflow a 320px screen:\n  ` +
        `${offenders.join("\n  ")}\n` +
        `Either wrap the element in \`overflow-x-auto\` (the pattern every table here ` +
        `uses) or prefix the utility, e.g. \`sm:min-w-[16rem]\`.`,
    ).toEqual([]);
  });
});

describe("card padding leaves a phone something to read", () => {
  /**
   * At 320px a flat `p-6` spent 48px of a 288px strip on whitespace, and it is what
   * pushed `/admin/tenants/[tenantId]`'s inner grid past the viewport. The default is now
   * `p-4 sm:p-6`; the rule below is what keeps a call site from reintroducing the flat
   * one through `bodyClassName`, which overrides the default entirely.
   */
  it("Card defaults to 16px of padding on a phone", () => {
    const ui = read(join(SRC, "components", "ui.tsx"));
    expect(ui, "Card's default body padding is no longer responsive").toContain('bodyClassName ?? "p-4 sm:p-6"');
  });

  it("no bodyClassName sets more than 16px of horizontal padding on a phone", () => {
    const offenders: string[] = [];
    for (const file of FILES) {
      const lines = read(file).split("\n");
      lines.forEach((line, i) => {
        const value = /bodyClassName=(?:"([^"]*)"|\{"([^"]*)"\})/.exec(line);
        if (!value) return;
        const classes = (value[1] ?? value[2] ?? "").split(/\s+/).filter(Boolean);
        for (const c of classes) {
          // Unprefixed `p-5`/`p-6`/`px-5`/`px-6` and up: 20px or more per side.
          const m = /^p[x]?-(\d+)$/.exec(c);
          if (m && Number(m[1]) >= 5) offenders.push(`${rel(file)}:${i + 1} — ${c}`);
        }
      });
    }
    expect(
      offenders,
      `these Card bodies pad by 20px or more per side at every width, which on a 320px ` +
        `screen spends an eighth of the viewport before any content:\n  ` +
        `${offenders.join("\n  ")}\n` +
        `Use the responsive form the default uses, e.g. \`p-4 sm:p-6\`.`,
    ).toEqual([]);
  });
});

describe("the mobile drawer is a drawer at every width", () => {
  /**
   * `isCollapsed` is a DESKTOP control — it is set by a button that is `lg:flex` — but it
   * is component state that survives a resize, so `isCollapsed ? "lg:w-[72px]" : …` gave
   * the panel no base width at all below `lg`: the overlay drawer shrink-wrapped its
   * content instead of being a 255px drawer. Both shells had the identical expression,
   * which is why this is checked for both rather than fixed in one.
   */
  it("both shells give the drawer a width that does not depend on a breakpoint", () => {
    for (const shell of ["app/c/[slug]/layout.tsx", "app/admin/layout.tsx"]) {
      const source = read(join(SRC, shell));
      const expression = /className=\{isCollapsed \? "([^"]*)" : "([^"]*)"\}/.exec(source);
      expect(expression, `${shell} no longer sets the NavDrawer width the expected way`).not.toBeNull();
      for (const arm of [expression![1], expression![2]]) {
        expect(
          arm.split(/\s+/).some((c) => /^w-/.test(c)),
          `${shell}: the drawer width "${arm}" is only set behind a breakpoint, so below ` +
            `lg the overlay drawer has no width of its own`,
        ).toBe(true);
      }
    }
  });
});


describe("every scroll container can be reached from a keyboard", () => {
  /**
   * There is no key that scrolls a non-focusable element.
   *
   * A wide table inside a bare `overflow-x-auto` div is content a keyboard-only user
   * cannot read the right-hand side of — on the credit ledger and the invoice that is the
   * money columns. Seventeen of the console's eighteen scroll containers were exactly
   * that; the eighteenth (`lib/legal/document.tsx`) had argued the case inline and been
   * copied by none of them. `ScrollRegion` is that shape hoisted, and every one of the
   * eighteen now uses it.
   *
   * THE A11Y SWEEP CANNOT SEE THIS, which is why the rule lives here rather than there.
   * axe's `scrollable-region-focusable` needs to know that an element actually scrolls,
   * and jsdom implements no layout, so the rule never fires and the gate was green on all
   * eighteen. A source check is what can go red.
   */
  const NOT_A_SCROLL_REGION: Record<string, string> = {
    "components/ui.tsx": "`ScrollRegion` itself — this is the definition.",
    "app/c/[slug]/integrations/page.tsx":
      "The delivered-payload `<pre>` scrolls VERTICALLY (`max-h-80`), which `ScrollRegion` " +
      "does not model — it hardcodes `overflow-x-auto`. It carries the same `role=region` " +
      "+ `aria-label` + `tabIndex={0}` inline, and the assertion checks that rather than " +
      "waiving it. (The screen's delivery-log table IS a `ScrollRegion`.)",
  };

  it("is a ScrollRegion, or is focusable in its own right", () => {
    const unreachable: string[] = [];
    for (const file of FILES) {
      const source = read(file).split("\n");
      source.forEach((line, i) => {
        if (!/overflow-x-auto|overflow-auto|overflow-x-scroll/.test(line)) return;
        // Only an element wearing the utility as a class is a container; the doc comments
        // that explain the rule mention it too.
        if (!/className/.test(line)) return;
        const key = rel(file).replace(/^src\//, "");
        if (!Object.hasOwn(NOT_A_SCROLL_REGION, key)) {
          unreachable.push(`${rel(file)}:${i + 1} — ${line.trim()}`);
          return;
        }
        // An exemption is from the COMPONENT, never from the rule: the site still has to
        // take focus. The attributes sit in the same element, within a few lines.
        const near = source.slice(Math.max(0, i - 8), i + 8).join(" ");
        if (key !== "components/ui.tsx" && !/tabIndex=\{0\}/.test(near)) {
          unreachable.push(`${rel(file)}:${i + 1} — exempted from ScrollRegion but not focusable`);
        }
      });
    }
    expect(
      unreachable,
      `these scroll containers cannot be scrolled by a keyboard:\n  ` +
        `${unreachable.join("\n  ")}\n` +
        `Wrap the content in \`<ScrollRegion label="…">\` (components/ui.tsx), which ` +
        `carries role=region + tabIndex=0 + the accessible name.`,
    ).toEqual([]);
  });

  it("carries an accessible name wherever it is used", () => {
    // A `role="region"` with no name is not exposed as a landmark at all, so an unnamed
    // one buys a screen-reader user a focus stop and nothing else. `label` is required by
    // `ScrollRegion`'s type; this is the check that nobody passes an empty one.
    const unnamed: string[] = [];
    for (const file of FILES) {
      const source = read(file).split("\n");
      source.forEach((line, i) => {
        if (!/<ScrollRegion\b/.test(line)) return;
        const element = source.slice(i, i + 4).join(" ");
        if (!/label=\{?["`{]/.test(element) || /label=""/.test(element)) {
          unnamed.push(`${rel(file)}:${i + 1}`);
        }
      });
    }
    expect(unnamed, "ScrollRegion with no usable label").toEqual([]);
  });
});


/**
 * WCAG 2.2 SC 2.5.8 Target Size (Minimum), for the link lists a browser measured under it.
 *
 * Chromium + axe over the eleven public routes reported `target-size` on 78 nodes, all of
 * one shape: an anchor that is the whole content of an `<li>` in a navigation list, so its
 * box is exactly its line box — 11px in the marketing footer, 17px in a legal document's
 * table of contents. The SC's "inline" exception does not reach them: that exception is for
 * a link inside a sentence of running prose, and a list of policy links is navigation.
 *
 * The fix is `inline-block` plus vertical padding, which turns a 17px line box into a 28px
 * target without moving anything (the lists' existing `space-y` gaps absorb it). This rule
 * is the static half — the browser is the instrument, per this file's header — and it is
 * written as "these four anchors carry the padding" rather than as a general rule, because
 * a general one would need layout to tell an anchor that is inline in prose from one that
 * is a list row of its own. The list below is the one a browser actually measured.
 */
describe("a navigation link's tap target", () => {
  const LEGAL_LINK_LISTS: [string, RegExp][] = [
    ["lib/legal/document.tsx", /href=\{`#\$\{section\.id\}`\}/],
    ["lib/legal/document.tsx", /href=\{`#\$\{sub\.id\}`\}/],
    ["lib/legal/document.tsx", /href=\{`\/legal\/\$\{other\.slug\}`\}/],
    ["app/page.tsx", /href=\{`\/legal\/\$\{doc\.slug\}`\}/],
  ];

  it("is at least 24px tall in every legal navigation list", () => {
    const flat: string[] = [];
    for (const [file, anchor] of LEGAL_LINK_LISTS) {
      const source = readFileSync(join(SRC, file), "utf8").split("\n");
      const at = source.findIndex((line) => anchor.test(line));
      expect(
        at,
        `${file}: no line matching ${anchor} — has the link list moved?`,
      ).toBeGreaterThan(-1);
      // The padding has to be on the ANCHOR and not on the `<li>`: SC 2.5.8 measures the
      // target, and a padded parent leaves the clickable box exactly where it was.
      const element = source.slice(at, at + 12).join(" ");
      if (!/className="[^"]*inline-block[^"]*py-1/.test(element)) {
        flat.push(`${file}:${at + 1}`);
      }
    }
    expect(
      flat,
      `these navigation links are only their line box tall, under SC 2.5.8's 24px:\n  ` +
        `${flat.join("\n  ")}\n` +
        `Add \`inline-block py-1\` to the anchor's own className.`,
    ).toEqual([]);
  });
});
