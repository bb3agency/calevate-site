import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { tsSources } from "./copyScan";
import { relPosix } from "./repoPaths";

/**
 * THE HOMEPAGE'S PRODUCT MOCKUPS FIT A PHONE AND SAY NOTHING THEY SHOULD NOT.
 *
 * The mockups under `components/marketing/home/mockups/` are dense, absolutely sized
 * pieces of product UI on the one page a stranger reads on a 360px phone. The defects this
 * guards were found by measuring them in a real browser at 320-1440px; what a source scan
 * buys is that the fix cannot be silently undone (the trade `tests/responsive.test.ts`
 * states in its own header).
 *
 *  1. No fixed width wider than a phone's content box, unless it waits for a breakpoint.
 *     The marketing shell leaves 280px at 320px (`px-5`), and a card inside it pads again,
 *     so an unprefixed `w-72` (288px) is already a horizontal overflow or a clipped column.
 *  2. No prose elements. A mockup's words are labels on a drawn screen, not the page's
 *     outline or body copy: an `<h3>` inside one would enter the heading order a
 *     screen-reader user navigates by, and a `<p>`/`<li>` would fall under the landing
 *     page's reading-size guard, which is about prose.
 *  3. No dialable phone number. Sample callers carry the `+91 98XXX XX123` mask; a run of
 *     ten digits in a mockup could be somebody's real number on a public page.
 */

const MOCKUPS = tsSources(
  resolve(process.cwd(), "src", "components", "marketing", "home", "mockups"),
).map((file) => ({ file: relPosix(process.cwd(), file), text: readFileSync(file, "utf8") }));

/** Code lines only: a comment may talk about the utilities this scan bans. */
function codeLines(text: string): { line: string; n: number }[] {
  return text
    .split("\n")
    .map((line, i) => ({ line, n: i + 1 }))
    .filter(({ line }) => !/^\s*(\*|\/\/|\/\*)/.test(line));
}

describe("the homepage mockups", () => {
  it("reads a directory that is actually there", () => {
    expect(MOCKUPS.length, "the mockup walk found nothing — has the directory moved?")
      .toBeGreaterThan(4);
  });

  it("sets no unprefixed width wider than a phone's content box", () => {
    // 280px: a 320px viewport less the shell's 20px gutters.
    const PHONE_CONTENT_PX = 280;
    const offenders: string[] = [];
    for (const { file, text } of MOCKUPS) {
      for (const { line, n } of codeLines(text)) {
        for (const match of line.matchAll(/(^|[\s"'`])((?:min-)?w-(\d+(?:\.\d+)?|\[(\d+)px\]))(?=[\s"'`])/g)) {
          const px = match[4] ? Number(match[4]) : Number(match[3]) * 4;
          if (px <= PHONE_CONTENT_PX) continue;
          offenders.push(`${file}:${n} — ${match[2]} (${px}px)`);
        }
      }
    }
    expect(
      offenders,
      `these widths are wider than a 320px phone can hold at every breakpoint:\n  ${offenders.join("\n  ")}\n` +
        "Prefix them (`lg:w-80`) so a phone gets the fluid width.",
    ).toEqual([]);
  });

  it("draws with no heading, paragraph or list-item elements", () => {
    const offenders: string[] = [];
    for (const { file, text } of MOCKUPS) {
      for (const { line, n } of codeLines(text)) {
        if (/<(h[1-6]|p|li|ul|ol)[\s>]/.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders, "a mockup's words are labels, not prose or outline").toEqual([]);
  });

  it("prints no phone number that could be dialled", () => {
    const offenders: string[] = [];
    for (const { file, text } of MOCKUPS) {
      for (const { line, n } of codeLines(text)) {
        // Ten or more digits, allowing the spaces and dashes a number is written with.
        if (/(?:\d[\s-]?){10,}/.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders, "use the `+91 98XXX XX123` mask for a sample caller").toEqual([]);
  });
});
