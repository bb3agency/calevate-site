import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Frontend audit W8 (8 Nov 2026), admin realm: ops levers, voices, tenant sub-pages.
 */

const ADMIN_DIR = join(__dirname, "..", "src", "app", "admin");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return name.endsWith(".tsx") ? [path] : [];
  });
}

/** JSX text only: comments may still explain why the notice is gone. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("no 'this is recorded in the activity log' notices (founder, 15 Oct 2026)", () => {
  // The rule: admin and client copy does not tell the user that an act is audited or
  // logged; the disclosures already say it. The halt, load-shed, outbox-resend and TM
  // registration levers still said "Recorded in the activity log ...".
  it("no admin screen tells the operator an act is kept in the activity log", () => {
    const offenders = sourceFiles(ADMIN_DIR).filter((path) =>
      /(Recorded|recorded|kept) in the activity log/.test(withoutComments(readFileSync(path, "utf8"))),
    );
    expect(offenders.map((path) => relative(ADMIN_DIR, path))).toEqual([]);
  });
});
