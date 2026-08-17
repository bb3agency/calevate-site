import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

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
const rel = (f: string): string => relative(process.cwd(), f);

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
          if (/overflow-x-auto|overflow-auto|overflow-x-scroll/.test(near)) continue;
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
