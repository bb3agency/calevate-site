import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";
import { blankComments } from "./sourceScan";

/**
 * Phone and wide-screen rules for the agent and knowledge screens, on top of the
 * console-wide ones in `responsive.test.ts`.
 */

const SRC = join(process.cwd(), "src");
const AREA = [
  "app/c/[slug]/agents",
  "app/c/[slug]/knowledge",
  "components/leadFields",
  "components/improvement",
  "components/forwarding",
  "components/businessProfile",
];

function areaFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tsx")) out.push(full);
    }
  };
  for (const dir of AREA) walk(join(SRC, dir));
  if (out.length === 0) throw new Error(`no .tsx found under ${SRC} — wrong cwd`);
  return out;
}

const code = (file: string): string[] => blankComments(readFileSync(file, "utf8").split("\n"));

describe("agent and knowledge screens on a phone", () => {
  /**
   * `responsive.test.ts` reads the class straight after `className=`, so a grid chosen by a
   * ternary (`className={wide ? "grid xl:grid-cols-…" : ""}`) slipped past it: the script
   * page's two side-panel grids had no base column, and below `xl` one long step name or
   * prompt line could widen the implicit auto track past the screen.
   */
  it("every string that switches grid columns at a breakpoint names its phone column", () => {
    const offenders: string[] = [];
    for (const file of areaFiles()) {
      code(file).forEach((line, i) => {
        for (const [, cls] of line.matchAll(/"([^"]*)"/g)) {
          if (!/(?:^|\s)grid(?:\s|$)/.test(cls)) continue;
          if (!/(?:^|\s)[\w-[\]()]+:grid-cols-/.test(cls)) continue;
          if (!/(?:^|\s)grid-cols-/.test(cls)) offenders.push(`${relPosix(SRC, file)}:${i + 1}`);
        }
      });
    }
    expect(offenders, "add grid-cols-1 so the phone column can shrink").toEqual([]);
  });

  /**
   * The step list is where an owner finds out what to fix. A step name or an error cut to
   * "Ask what they ne…" hid the very thing the row exists to say, at every width, so the
   * summary wraps; only the instruction preview is clamped, and the step opens in place.
   */
  it("the step summary wraps the step name and its problem instead of cutting them", () => {
    const source = code(join(SRC, "app/c/[slug]/agents/[agentId]/script/SectionList.tsx")).join("\n");
    // `\r?`: the split on "\n" leaves a "\r" on each line in a CRLF checkout.
    const summary = /function SectionSummary[\s\S]*?\n}\r?\n/.exec(source)?.[0] ?? "";
    expect(summary, "SectionSummary not found").not.toEqual("");
    expect(summary).not.toMatch(/\btruncate\b/);
  });

  it("the script bar's save line wraps rather than hiding a failure", () => {
    const source = code(join(SRC, "app/c/[slug]/agents/[agentId]/script/ScriptToolbar.tsx")).join("\n");
    const status = /<p role="status"[^>]*>/.exec(source)?.[0] ?? "";
    expect(status).not.toEqual("");
    expect(status).not.toMatch(/\btruncate\b/);
  });
});
