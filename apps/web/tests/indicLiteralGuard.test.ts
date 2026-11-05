import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * No hand-written Telugu, Hindi or other Indian-language words in the web code (audit of
 * 5 Nov 2026, founder rule 2). Sample lines live in the founder's `lib/founderLines.json`;
 * spoken lines are the server's data files. Comment lines are not read, and punctuation such
 * as the danda is not a letter.
 *
 * `ROUTED` holds files another fix lane owns that still carry such lines, by count of lines.
 * A count only shrinks: a file at a different count fails, so a cleaned file must leave.
 */

const SRC = resolve(__dirname, "../src");

const ROUTED: Readonly<Record<string, number>> = {
  // Unicode ranges that tell which script a reply is in (a detector, not words).
  "app/c/[slug]/agents/[agentId]/test/testCopy.ts": 4,
};

const INDIC_LETTER =
  /[\p{Script=Devanagari}\p{Script=Bengali}\p{Script=Gurmukhi}\p{Script=Gujarati}\p{Script=Oriya}\p{Script=Tamil}\p{Script=Telugu}\p{Script=Kannada}\p{Script=Malayalam}]/u;
const DANDA = /[।॥]/gu;
const COMMENT = /^\s*(\/\/|\/\*|\*)/;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

function indicLines(path: string): number {
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((line) => !COMMENT.test(line) && INDIC_LETTER.test(line.replace(DANDA, ""))).length;
}

describe("no hand-written Indian-language words in the web code", () => {
  it("reads the sources", () => {
    expect(sources(SRC).length).toBeGreaterThan(500);
  });

  it("finds them only in the files routed to their lanes, at their counts", () => {
    const found: Record<string, number> = {};
    for (const path of sources(SRC)) {
      const count = indicLines(path);
      if (count > 0) found[relative(SRC, path).replaceAll("\\", "/")] = count;
    }
    expect(found).toEqual(ROUTED);
  });

  it("sees what it guards", () => {
    expect(INDIC_LETTER.test("తెలుగు")).toBe(true);
    expect(INDIC_LETTER.test("।".replace(DANDA, ""))).toBe(false);
  });
});
