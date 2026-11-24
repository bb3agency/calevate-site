import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/*
 * EVERY BUTTON SHOWS IT IS WORKING (founder, 24 Nov 2026: "all across calevate when a button
 * is clicked a loader circle animation from the saved components should be shown in the button
 * as long as the operation is running").
 *
 * The one way is `ActionButton` (`components/arc/feedback.tsx`): `status="pending"` draws its
 * `LoaderCircle` and ignores presses. A raw `<button>` locked by `disabled={...isPending}` goes
 * grey and says nothing, which is what the founder saw on Rewrite now. This scan fails on any
 * raw `<button>` whose `disabled` reads a pending/busy flag, so the pattern cannot come back.
 */

const SRC = join(__dirname, "..", "src");
const BUSY = /\b(isPending|isFetching|pending|busy|saving|submitting|sending|working|loading)\b/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return path.endsWith(".tsx") ? [path] : [];
  });
}

/** The opening tag starting at `from` (`<button ...>`), braces respected so `=>` inside an
 * attribute does not end it. */
function openingTag(source: string, from: number): string {
  let depth = 0;
  for (let i = from; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth++;
    else if (ch === "}") depth--;
    else if (ch === ">" && depth === 0) return source.slice(from, i + 1);
  }
  return source.slice(from);
}

/** The expression of `disabled={...}` in `tag`, or null. */
function disabledExpression(tag: string): string | null {
  const at = tag.search(/\sdisabled=\{/);
  if (at < 0) return null;
  let depth = 0;
  const start = tag.indexOf("{", at);
  for (let i = start; i < tag.length; i++) {
    if (tag[i] === "{") depth++;
    else if (tag[i] === "}" && --depth === 0) return tag.slice(start + 1, i);
  }
  return null;
}

/** Raw buttons allowed to stay as they are, each with its reason. */
const ALLOWED: ReadonlyMap<string, string> = new Map([
  // Pip's suggested questions and quick replies: pressing one sends it, and the progress
  // shows in the chat thread itself; the pills wrap long questions, which ActionButton's
  // single-line faces would cut off.
  ["components/copilot/CopilotPanel.tsx", "the chat thread shows the work"],
]);

export function busyRawButtons(): string[] {
  const found: string[] = [];
  for (const path of files(SRC)) {
    const source = readFileSync(path, "utf8");
    for (const match of source.matchAll(/<button\b/g)) {
      const expression = disabledExpression(openingTag(source, match.index ?? 0));
      const file = relative(SRC, path).replaceAll("\\", "/");
      if (expression && BUSY.test(expression) && !ALLOWED.has(file)) {
        const line = source.slice(0, match.index).split("\n").length;
        found.push(`${file}:${line}`);
      }
    }
  }
  return found;
}

describe("buttons that are working show it", () => {
  it("has no raw <button> greyed by a running action instead of showing ActionButton's spinner", () => {
    expect(busyRawButtons()).toEqual([]);
  });

  it("finds the pattern it forbids", () => {
    const tag = '<button type="button" onClick={() => save()} disabled={save.isPending}>';
    expect(BUSY.test(disabledExpression(openingTag(tag, 0)) ?? "")).toBe(true);
  });
});
