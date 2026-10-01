import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { tsSources } from "./copyScan";
import { relPosix } from "./repoPaths";

/**
 * THE /pricing AND /roi CONSOLE MOCKUPS HOLD THE HOMEPAGE MOCKUPS' RULES, PLUS ONE.
 *
 * The three rules of `homeMockups.test.ts` (fits a 320px phone, no prose elements, no
 * dialable number), applied to `components/marketing/pricing/` and `.../roi/`. And the one
 * that matters on the money pages: a mockup draws NO rupee figure. Every ₹ on `/pricing`
 * must be one the rate card sent (`marketingPages.test.tsx`), and a sample balance would
 * be an invented price whatever its caption said — so amounts are masked, and this scan
 * is what keeps a "realistic" figure from being typed back in.
 */

const MOCKUPS = ["pricing", "roi"].flatMap((dir) =>
  tsSources(resolve(process.cwd(), "src", "components", "marketing", dir)).map((file) => ({
    file: relPosix(process.cwd(), file),
    text: readFileSync(file, "utf8"),
  })),
);

/** Code lines only: a comment may talk about the things this scan bans. */
function codeLines(text: string): { line: string; n: number }[] {
  return text
    .split("\n")
    .map((line, i) => ({ line, n: i + 1 }))
    .filter(({ line }) => !/^\s*(\*|\/\/|\/\*)/.test(line));
}

describe("the pricing and ROI mockups", () => {
  it("reads directories that are actually there", () => {
    expect(MOCKUPS.length, "the mockup walk found nothing — have the directories moved?")
      .toBeGreaterThanOrEqual(2);
  });

  it("sets no unprefixed width wider than a phone's content box", () => {
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
    expect(offenders).toEqual([]);
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
        if (/(?:\d[\s-]?){10,}/.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("draws no rupee figure — amounts are masked", () => {
    const offenders: string[] = [];
    for (const { file, text } of MOCKUPS) {
      for (const { line, n } of codeLines(text)) {
        if (/₹\s*\d|\bRs\.?\s*\d|\bINR\s*\d/i.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders, "a sample amount on a money page reads as a price").toEqual([]);
  });
});
