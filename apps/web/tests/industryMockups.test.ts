import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { INDUSTRY_CALLS } from "@/components/marketing/industries/industryCall";
import { INDUSTRIES } from "@/lib/marketing/industries";

import { tsSources } from "./copyScan";
import { relPosix } from "./repoPaths";

/**
 * THE `/solutions` AND `/industries` MOCKUPS, HELD TO THE HOMEPAGE MOCKUPS' RULES.
 *
 * `tests/homeMockups.test.ts` states the three source-scan rules and why each exists (a
 * 320px phone leaves 280px of content box; a mockup's words are labels, not the page's
 * outline or prose; a sample caller is never a diallable number). These two folders are
 * the same kind of drawing on two more public pages, so they get the same scan.
 *
 * Plus one rule of their own: every trade's opened call writes its captured details under
 * that trade's real column labels, all of them and in the seed's order — the same list
 * `publicLanding.test.tsx` diffs against `scripts/seed.py`. A mockup that invented a
 * prettier column would show a buyer a first screen their agent does not have.
 */

const ROOTS = ["solutions", "industries"].map((dir) =>
  resolve(process.cwd(), "src", "components", "marketing", dir),
);

const MOCKUPS = ROOTS.flatMap((root) => tsSources(root)).map((file) => ({
  file: relPosix(process.cwd(), file),
  text: readFileSync(file, "utf8"),
}));

/** Code lines only: a comment may talk about the utilities this scan bans. */
function codeLines(text: string): { line: string; n: number }[] {
  return text
    .split("\n")
    .map((line, i) => ({ line, n: i + 1 }))
    .filter(({ line }) => !/^\s*(\*|\/\/|\/\*)/.test(line));
}

describe("the solutions and industries mockups", () => {
  it("reads directories that are actually there", () => {
    expect(MOCKUPS.length, "the mockup walk found nothing — have the folders moved?")
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
    expect(offenders, "prefix them (`lg:w-80`) so a phone gets the fluid width").toEqual([]);
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
    expect(offenders, "use the `+91 98XXX XX123` mask for a sample caller").toEqual([]);
  });
});

describe("each trade's opened call", () => {
  it.each(INDUSTRIES.map((industry) => [industry.id, industry] as const))(
    "%s captures its own template's fields, in the seed's order",
    (id, industry) => {
      const call = INDUSTRY_CALLS[id];
      expect(call, `${industry.name} has no call drawn`).toBeDefined();
      expect(call?.captured.map(([label]) => label)).toEqual([...industry.fields]);
    },
  );

  it.each(Object.entries(INDUSTRY_CALLS))(
    "%s opens with the AI disclosure and the recording notice",
    (_id, call) => {
      const first = call.turns[0];
      expect(first?.who).toBe("Agent");
      // The English line is what a reader of the page can check, whatever was spoken.
      const english = first?.en ?? first?.said ?? "";
      expect(english).toMatch(/\bAI assistant\b/);
      expect(english).toMatch(/\brecorded\b/);
    },
  );
});
