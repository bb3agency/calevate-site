import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * No screen, public page or legal text may claim that every call announces it is an AI or
 * that it is recorded. The volunteered notices are account switches that start OFF
 * (D-1021, `organizations.notice_ai_enabled` / `notice_recording_enabled`,
 * `server_default=false()`); what is true of every call is the truthful ANSWER when a caller
 * asks (hard rule 5). So "always says it is an AI when asked" is allowed and "every call
 * announces it is an AI" is not.
 */

const SRC = join(__dirname, "..", "src");
const API_MODELS = join(__dirname, "..", "..", "api", "tenancy", "models.py");

/** Generated from the API and never written by hand. */
const GENERATED = new Set(["lib/api/openapi.json", "lib/api/schema.d.ts"]);

/** A claim about the start of every call, naming the AI or the recording. */
const FALSE_CLAIMS: RegExp[] = [
  /every call (announces|says|tells|discloses|starts by saying|opens by saying)[^.]{0,60}\b(ai|artificial|recorded|recording)\b/i,
  /(always|automatically) (announces|discloses|introduces itself as)[^.]{0,60}\b(ai|artificial|recorded|recording)\b/i,
  /(every|each|all) callers? (is|are|will be|gets?) (told|informed|notified)[^.]{0,60}\b(ai|artificial|recorded|recording)\b/i,
  /every call says it is (an )?ai/i,
];

/** The true claim names the condition: when the caller asks. */
const WHEN_ASKED = /\b(when|if) (they |the caller |a caller |someone )?(ask|asks|asked)\b/i;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx?|md|json)$/.test(name) ? [path] : [];
  });
}

/** Each sentence-sized piece of a file that makes a false claim, as `file: text`. */
function falseClaims(file: string, text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\n/)
    .filter((sentence) => FALSE_CLAIMS.some((re) => re.test(sentence)) && !WHEN_ASKED.test(sentence))
    .map((sentence) => `${file}: ${sentence.trim()}`);
}

describe("no text claims every call volunteers the AI or recording notice", () => {
  it("finds no such claim in any screen, page or legal text", () => {
    const found = sourceFiles(SRC)
      .map((path) => [relative(SRC, path).replaceAll("\\", "/"), path] as const)
      .filter(([file]) => !GENERATED.has(file))
      .flatMap(([file, path]) => falseClaims(file, readFileSync(path, "utf8")));
    expect(found).toEqual([]);
  });

  it("catches the claims it exists for and lets the true one through", () => {
    for (const claim of [
      "Every call announces it is an AI.",
      "Our agent always announces that the call is recorded.",
      "every call says it is AI",
      "Each caller is told they are speaking to an AI.",
    ]) {
      expect(falseClaims("x", claim), claim).toHaveLength(1);
    }
    for (const truth of [
      "Every agent answers honestly, every time, when asked if it is an AI or if the call is recorded.",
      "The agent always says it is an AI when asked.",
    ]) {
      expect(falseClaims("x", truth), truth).toEqual([]);
    }
  });

  it("rests on the notices starting off for a new account", () => {
    // If the founder turns them on by default, this guard's premise has changed: revisit it
    // rather than delete it.
    const models = readFileSync(API_MODELS, "utf8");
    expect(models).toMatch(/notice_ai_enabled: Mapped\[bool\] = mapped_column\([^)]*server_default=false\(\)/);
    expect(models).toMatch(/notice_recording_enabled: Mapped\[bool\] = mapped_column\(\s*Boolean, nullable=False, server_default=false\(\)/);
  });
});
