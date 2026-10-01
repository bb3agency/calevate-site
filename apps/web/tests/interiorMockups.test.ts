import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * The `/why-calevate`, `/security` and `/resources` mockups, held to the homepage mockups'
 * three rules (`homeMockups.test.ts` gives the reasons): no fixed width wider than a
 * phone's content box, no prose or outline elements, no diallable number.
 *
 * `pageHero.tsx` is not here: it is the page's heading block, not a drawn screen.
 */
const FILES = [
  ["src", "components", "marketing", "why", "mockups.tsx"],
  ["src", "components", "marketing", "security", "mockups.tsx"],
  ["src", "components", "marketing", "resources", "samples.tsx"],
].map((parts) => {
  const file = resolve(process.cwd(), ...parts);
  return { file: relPosix(process.cwd(), file), text: readFileSync(file, "utf8") };
});

function codeLines(text: string): { line: string; n: number }[] {
  return text
    .split("\n")
    .map((line, i) => ({ line, n: i + 1 }))
    .filter(({ line }) => !/^\s*(\*|\/\/|\/\*)/.test(line));
}

describe("the interior-page mockups", () => {
  it("sets no unprefixed width wider than a phone's content box", () => {
    const PHONE_CONTENT_PX = 280;
    const offenders: string[] = [];
    for (const { file, text } of FILES) {
      for (const { line, n } of codeLines(text)) {
        for (const match of line.matchAll(/(^|[\s"'`])((?:min-)?w-(\d+(?:\.\d+)?|\[(\d+)px\]))(?=[\s"'`])/g)) {
          const px = match[4] ? Number(match[4]) : Number(match[3]) * 4;
          if (px > PHONE_CONTENT_PX) offenders.push(`${file}:${n} — ${match[2]} (${px}px)`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("draws with no heading, paragraph or list-item elements", () => {
    const offenders: string[] = [];
    for (const { file, text } of FILES) {
      for (const { line, n } of codeLines(text)) {
        if (/<(h[1-6]|p|li|ul|ol)[\s>]/.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("prints no phone number that could be dialled", () => {
    const offenders: string[] = [];
    for (const { file, text } of FILES) {
      for (const { line, n } of codeLines(text)) {
        if (/(?:\d[\s-]?){10,}/.test(line)) offenders.push(`${file}:${n} — ${line.trim()}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("prints no percentage, score or certification inside a security mockup", () => {
    // The security page publishes no score and holds no certification; a drawn screen is
    // still text on that page.
    const security = FILES.find(({ file }) => file.includes("/security/"));
    const code = codeLines(security?.text ?? "").map(({ line }) => line).join("\n");
    // `%]` is a Tailwind arbitrary value (`left-[37.5%]`), not a figure on the page.
    expect(code).not.toMatch(/\d+\s*%(?!\])|\bSOC ?2\b|\bISO ?27001\b|\bcertified\b/i);
  });
});
