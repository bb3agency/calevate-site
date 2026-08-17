import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The mobile surface, guarded — the test this suite did not have.
 *
 * Nothing in `apps/web/tests/` rendered at a viewport width, set `window.innerWidth`, or
 * inspected a `min-w-` class, so fifteen fixed-minimum-width blocks and eighteen
 * horizontal scroll containers shipped with no regression protection at all. The visible
 * consequence of that gap: seventeen of the eighteen scroll containers could not be
 * reached by a keyboard, and the two controls a client touches most on the leads table
 * were roughly a 20px tap target.
 *
 * ## Why this is a source scan and not a render
 *
 * jsdom implements NO LAYOUT. `getBoundingClientRect()` returns zeroes, nothing overflows,
 * nothing scrolls, and no computed width exists — which is exactly why axe's
 * `scrollable-region-focusable` never fires under the a11y sweep and why that sweep was
 * green on all eighteen containers (`tests/a11y.ts` says so in its own words). A test that
 * rendered these screens and measured them would measure zero and pass forever: a guard
 * that cannot fail.
 *
 * What CAN be checked without layout is the thing the defect actually is — the class
 * strings and the nesting a developer wrote. Every assertion below is over the source, and
 * every one of them fails against the tree as it was before this change. That is the bar:
 * a check that can go red, not a rule that no-ops.
 *
 * ## Closed by a browser run, not by this
 *
 * The real answers — does this table overflow at 320px, is that select 44px tall on a
 * phone, does SC 2.5.8's spacing exception apply — need a browser. `@axe-core/playwright`
 * against the composed document is what closes them, the same escape hatch `tests/a11y.ts`
 * names for its own three blind spots. This is the part that can be enforced today, and it
 * says so rather than implying it is the whole check.
 */

/** `process.cwd()`, not `import.meta.url`: the latter is not a file URL under jsdom. */
const SRC = join(process.cwd(), "src") + "/";

/**
 * The narrowest viewport this product supports.
 *
 * 320 CSS px is the floor WCAG 1.4.10 Reflow measures against (content must reflow to
 * 320px without two-dimensional scrolling), and it is what a 360px-wide budget Android in
 * portrait leaves after the browser chrome — which is the device most of these clients are
 * on. A `min-w-` at or below it needs no scroll container, because it already fits.
 */
const NARROWEST_VIEWPORT_PX = 320;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...sourceFiles(full));
    else if (/\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

interface Line {
  file: string;
  no: number;
  indent: number;
  text: string;
}

function lines(file: string): Line[] {
  return readFileSync(file, "utf8")
    .split("\n")
    .map((text, i) => ({
      file: file.slice(SRC.length),
      no: i + 1,
      indent: text.length - text.trimStart().length,
      text,
    }));
}

/** `min-w-[960px]` / `min-w-[36rem]` → CSS pixels. `rem` is 16px in this app. */
function minWidthPx(text: string): number | null {
  const m = /min-w-\[(\d+(?:\.\d+)?)(px|rem)\]/.exec(text);
  if (!m) return null;
  return m[2] === "rem" ? Number(m[1]) * 16 : Number(m[1]);
}

/**
 * The JSX elements enclosing one line, outermost last.
 *
 * Indentation, not a parser, and the reason it is trustworthy here is that Prettier owns
 * the formatting of every file in this tree — an element's opening tag is always the
 * nearest preceding line at a strictly smaller indent. A hand-formatted file would break
 * it, which is why the assertions below quote the file and line: a wrong answer reads as
 * "this site has no scroll container", which sends a developer straight to the site.
 */
function ancestorsOf(all: Line[], at: number): Line[] {
  const out: Line[] = [];
  let indent = all[at].indent;
  for (let i = at - 1; i >= 0; i -= 1) {
    const line = all[i];
    if (line.text.trim() === "") continue;
    if (line.indent < indent && /^\s*<[A-Za-z]/.test(line.text)) {
      out.push(line);
      indent = line.indent;
      if (indent === 0) break;
    }
  }
  return out;
}

describe("content wider than a phone", () => {
  const files = sourceFiles(SRC);

  it("scans a tree it actually found", () => {
    // The vacuous pass this whole file exists to avoid.
    expect(files.length).toBeGreaterThan(50);
    const wide = files
      .flatMap(lines)
      .filter((l) => (minWidthPx(l.text) ?? 0) > NARROWEST_VIEWPORT_PX);
    expect(wide.length, "no min-w- sites found — the scan is looking in the wrong place")
      .toBeGreaterThan(5);
  });

  it("sits inside a scroll container, on every screen that has any", () => {
    const stranded: string[] = [];
    for (const file of files) {
      const all = lines(file);
      for (let i = 0; i < all.length; i += 1) {
        const width = minWidthPx(all[i].text);
        if (width === null || width <= NARROWEST_VIEWPORT_PX) continue;
        const chain = [all[i], ...ancestorsOf(all, i)];
        if (!chain.some((l) => /ScrollRegion|overflow-x-auto|overflow-auto/.test(l.text))) {
          stranded.push(`${all[i].file}:${all[i].no} — ${all[i].text.trim()}`);
        }
      }
    }

    expect(
      stranded,
      `content with a fixed minimum wider than ${NARROWEST_VIEWPORT_PX}px and nothing ` +
        "to scroll it: at that viewport the right-hand side is unreachable by anyone",
    ).toEqual([]);
  });
});

describe("every scroll container", () => {
  const files = sourceFiles(SRC);

  /**
   * Containers that scroll but are not `ScrollRegion`, with what makes each one correct.
   *
   * Compound `file:line-ish` keys with a stated reason, the shape `tests/a11y.ts` uses for
   * its own exemptions — an exemption written per FILE would silently cover the next
   * container somebody adds to the same screen.
   */
  const NOT_A_SCROLL_REGION: Record<string, string> = {
    "components/ui.tsx": "`ScrollRegion` itself — this is the definition.",
    "app/c/[slug]/integrations/page.tsx":
      "The delivered-payload `<pre>` scrolls VERTICALLY (`max-h-80`), which `ScrollRegion` " +
      "does not model — it hardcodes `overflow-x-auto`. It carries the same `role=region` " +
      "+ `aria-label` + `tabIndex={0}` inline, and the assertion below checks that rather " +
      "than waiving it. (The screen's delivery-log table IS a `ScrollRegion`.)",
  };

  it("is reachable from a keyboard", () => {
    const unreachable: string[] = [];
    for (const file of files) {
      const all = lines(file);
      for (let i = 0; i < all.length; i += 1) {
        if (!/overflow-x-auto|overflow-auto/.test(all[i].text)) continue;
        // The component's own definition and its doc comment mention the utility; only
        // an element carrying it as a class is a container.
        if (!/className/.test(all[i].text)) continue;
        const key = all[i].file;
        if (!Object.hasOwn(NOT_A_SCROLL_REGION, key)) {
          unreachable.push(`${all[i].file}:${all[i].no} — ${all[i].text.trim()}`);
          continue;
        }
        // An exempted site still has to be focusable and named — the exemption is from
        // the COMPONENT, never from the rule. The attributes sit in the same element, so
        // the few lines around the class are where they must appear.
        const near = all
          .slice(Math.max(0, i - 8), i + 8)
          .map((l) => l.text)
          .join(" ");
        if (key !== "components/ui.tsx" && !/tabIndex=\{0\}/.test(near)) {
          unreachable.push(`${all[i].file}:${all[i].no} — exempted but not focusable`);
        }
      }
    }

    expect(
      unreachable,
      "scroll containers a keyboard cannot reach — there is no key that scrolls a " +
        "non-focusable element (axe `scrollable-region-focusable`, which jsdom cannot fire)",
    ).toEqual([]);
  });

  it("carries an accessible name wherever it is used", () => {
    // A `role="region"` with no name is not exposed as a landmark at all, so an unnamed
    // one buys a screen-reader user a focus stop and nothing else. `ScrollRegion` requires
    // `label` in its type; this is the check that nobody passes an empty one.
    const unnamed: string[] = [];
    for (const file of files) {
      for (const line of lines(file)) {
        if (!/<ScrollRegion\b/.test(line.text)) continue;
        const rest = readFileSync(file, "utf8").split("\n").slice(line.no - 1, line.no + 3).join(" ");
        if (!/label=\{?["`{]/.test(rest) || /label=""/.test(rest)) {
          unnamed.push(`${line.file}:${line.no}`);
        }
      }
    }
    expect(unnamed, "ScrollRegion with no usable label").toEqual([]);
  });
});

describe("a control a thumb has to hit", () => {
  const files = sourceFiles(SRC);

  /**
   * WCAG 2.2 SC 2.5.8 Target Size (Minimum) is 24×24 CSS px at Level AA; this repo's own
   * minimum for a touch target is 44px (`min-h-11`, `components/marketing/faq.tsx`), which
   * also clears SC 2.5.5 at AAA.
   *
   * What is checkable without layout is the combination that produced the 20px control:
   * `text-xs` (12px text in a 16px line box) with `py-0.5` (2px each side) and no height
   * floor — about 20px rendered, which is UNDER the AA minimum on any reading. The
   * threshold stops there deliberately: `py-1` computes to 24px, exactly the minimum, and
   * a guard that also failed the controls which pass would be one people learn to widen
   * rather than obey. It is a shape rather than a measurement either way, which is the
   * honest limit of a jsdom-era guard and why the browser run above is named as what
   * closes the question properly.
   */
  const TINY = /text-xs/;
  const THIN_PADDING = /\bpy-0\.5\b/;
  const HAS_FLOOR = /min-h-|\bh-\d/;

  /**
   * Is this class string worn by something a person presses?
   *
   * TWO SHAPES, and the second is the one that matters: the defect this test was written
   * for lives in a shared `const INLINE_EDIT = "…"` at the top of `leads/page.tsx`, not on
   * a JSX line — so a check that only looked upward for a `<select>` would have passed on
   * the exact control the finding named, which is the failure mode this whole file is
   * about. A SCREAMING_CASE const holding a class string is a control style by convention
   * here (`PRIMARY_BUTTON`, `SECONDARY_BUTTON_SM`, `FIELD`, `QUIET_BUTTON`), so it counts.
   */
  function isPressable(all: Line[], at: number): boolean {
    const chain = [all[at], ...ancestorsOf(all, at)].slice(0, 3);
    if (chain.some((l) => /<(select|button|input|a)\b|Select\b/.test(l.text))) return true;
    for (let i = at; i >= 0 && i > at - 4; i -= 1) {
      if (/^(export )?const [A-Z][A-Z0-9_]* =/.test(all[i].text)) return true;
    }
    return false;
  }

  it("is never a text-xs control with no height floor", () => {
    const cramped: string[] = [];
    for (const file of files) {
      const all = lines(file);
      for (let i = 0; i < all.length; i += 1) {
        const text = all[i].text;
        // `className=` on an element, or the body of a shared class constant.
        if (!/className|^\s*["`]/.test(text)) continue;
        if (!TINY.test(text) || !THIN_PADDING.test(text) || HAS_FLOOR.test(text)) continue;
        // Only elements a person presses. A `<span>` badge at this size is text, not a
        // target, and SC 2.5.8 applies to targets.
        if (isPressable(all, i)) cramped.push(`${all[i].file}:${all[i].no} — ${text.trim()}`);
      }
    }

    expect(
      cramped,
      "pressable controls around 20px tall — under SC 2.5.8's 24px minimum, and these " +
        "are writes whose failure surface only speaks after a FAILED edit, never a wrong one",
    ).toEqual([]);
  });
});
