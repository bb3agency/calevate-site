import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { relPosix } from "./repoPaths";

/**
 * Every request that carries `confirmAction` must be able to prompt for a code.
 *
 * A gated write sent as a plain `apiRequest(..., { confirmAction })` fails on a stale second
 * factor with a refusal the operator cannot act on from the screen; sent through
 * `confirmedAdminRequest`, `withActionCode` or `withAccountCode`, the code prompt opens and
 * the request is sent once more (safe: the gate refuses before the route does anything).
 *
 * A source walk, like `authnSourceGuards.test.ts`: each `apiRequest(` / `apiUpload(` call
 * whose arguments mention `confirmAction` must sit inside one of those wrappers, which in
 * this codebase is always written within a few lines above the call.
 */

const WRAPPERS = /\b(withActionCode|withAccountCode|confirmedAdminRequest|confirmedRequest)\s*[<(]/;
const LOOKBEHIND = 700;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts") ? [path] : [];
  });
}

/** The argument text of the call whose `(` is at `open`, by bracket depth. */
function callArguments(source: string, open: number): string {
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(open, i + 1);
    }
  }
  return source.slice(open);
}

function unwrappedConfirmedCalls(): string[] {
  const root = join(process.cwd(), "src");
  const offenders: string[] = [];
  for (const file of sourceFiles(root)) {
    const source = readFileSync(file, "utf8");
    const call = /\b(apiRequest|apiUpload)\s*(<[^()]*?>)?\s*\(/g;
    for (const match of source.matchAll(call)) {
      // The transport's own definitions take `confirmAction` as a parameter.
      if (/function\s*$/.test(source.slice(Math.max(0, (match.index ?? 0) - 20), match.index))) {
        continue;
      }
      const open = (match.index ?? 0) + match[0].length - 1;
      if (!/\bconfirmAction\b/.test(callArguments(source, open))) continue;
      const before = source.slice(Math.max(0, (match.index ?? 0) - LOOKBEHIND), match.index);
      if (WRAPPERS.test(before)) continue;
      const line = source.slice(0, match.index).split("\n").length;
      offenders.push(`${relPosix(root, file)}:${line}`);
    }
  }
  return offenders;
}

describe("gated writes prompt for a code instead of failing", () => {
  it("every request carrying confirmAction goes through a code-prompting wrapper", () => {
    expect(unwrappedConfirmedCalls()).toEqual([]);
  });
});
