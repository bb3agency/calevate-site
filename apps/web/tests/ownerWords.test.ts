import { describe, expect, it } from "vitest";

import { copyUnder } from "./copyScan";

/**
 * THE CLIENT SCREENS SPEAK THE OWNER'S WORDS, NOT THE BUILDER'S (redesign plan §6,
 * `docs/design/redesign-2026-11-28/PLAN.md`).
 *
 * The founder built the same agent on another product and on ours side by side and found
 * our script builder talking like a flowchart tool: scenarios, ways out, green dots. An
 * owner asks "what might the caller say?" and "where does it go next?", so those are the
 * words on screen. Code identifiers, API fields and admin screens keep their names; only
 * text a client reads is checked, through the shared copy walk (`copyScan.ts`), which
 * skips comments, object keys, ids and import paths.
 *
 * There is no allow-list: a word below has an owner-word replacement in the plan's table,
 * so a new sentence that needs one of them is a sentence to reword.
 */

const SURFACES = ["src/app/c", "src/components"];
/** The public site is not the client app; its copy has its own guards. */
const EXEMPT = ["src/components/marketing"];

const BUILDER_WORDS: ReadonlyArray<{ word: RegExp; say: string }> = [
  { word: /\bscenarios?\b/i, say: "What the caller might say / reply" },
  { word: /\bways? out\b/i, say: "Then go to…" },
  { word: /\bgreen dot\b/i, say: "Pick where it goes next" },
  { word: /\bmandatory regulatory\b/i, say: "Before it can call" },
  { word: /\bcall flow\b/i, say: "Call steps" },
  { word: /\bmain task\b/i, say: "What this campaign is for" },
];

/**
 * A bracketed capitals marker (`[SCENARIO SCRIPTS]`) is a heading of the prompt the engine
 * reads, mirrored from the server so a length check counts what is sent; no owner sees it.
 */
const ENGINE_MARKER = /\[[A-Z][A-Z ]+\]/g;

function findings(): string[] {
  const out: string[] = [];
  for (const entry of copyUnder(SURFACES, EXEMPT, { wide: true })) {
    const text = entry.text.replace(ENGINE_MARKER, "");
    for (const { word, say } of BUILDER_WORDS) {
      const match = word.exec(text);
      if (match) {
        out.push(`${entry.file}:${entry.line} — “${match[0]}” (say: ${say}) in: ${entry.text.trim().slice(0, 120)}`);
      }
    }
  }
  return out;
}

describe("client screens use owner words", () => {
  it("reads the screens it claims to read", () => {
    const all = copyUnder(SURFACES, EXEMPT, { wide: true }).map((entry) => entry.text);
    expect(all.length).toBeGreaterThan(2000);
    // The renamed sections themselves, so a walk that stopped matching cannot pass empty.
    const text = all.join("\n");
    expect(text).toContain("Before it can call");
    expect(text).toContain("What this campaign is for");
    expect(text).toContain("Pick where it goes next");
  });

  it("shows no builder jargon", () => {
    expect(findings(), "reword these in the owner's words (PLAN.md §6)").toEqual([]);
  });
});
