import { describe, expect, it } from "vitest";

import {
  OPENING_LINE_COPILOT_HELP,
  RAW_SCRIPT_COPILOT_HELP,
  STEP_COPILOT_HELP,
  scriptCopilotFields,
} from "@/app/c/[slug]/agents/[agentId]/script/scriptSurface";
import { EMPTY_SCRIPT, type CallScript } from "@/lib/api/script";

/**
 * The call-script screen's declaration to the copilot. The property under test is the one
 * the founder's complaint is about: the assistant is told these boxes ARE the agent's system
 * prompt and must be drafted as one, not as a marketing paragraph — and it is told NOT to
 * restate the platform layers `compose_engine_prompt` already injects around the script.
 *
 * These assert the STEER a fill is drafted from, not a fill's outcome (that is the wire's
 * `validate_fill`, server-side). The steer lives on `help`, so `help` is what is pinned.
 */

const STRUCTURED: CallScript = {
  ...EMPTY_SCRIPT,
  opening_line: "నమస్కారం!",
  stages: [
    { id: "s1", name: "Need", instruction: "ask what they need", sounds_like: "cheppandi" },
    { id: "s2", name: "Name", instruction: "take their name", sounds_like: "" },
  ],
  faqs: [{ question: "hours?", answer: "9 to 9" }],
};

function helpFor(fields: ReturnType<typeof scriptCopilotFields>, id: string): string {
  const field = fields.find((f) => f.id === id);
  expect(field, `field ${id} present`).toBeDefined();
  return field?.help ?? "";
}

describe("the raw-mode script steer", () => {
  it("tells the copilot the box IS the agent's system prompt, drafted as one", () => {
    const help = helpFor(scriptCopilotFields({ ...EMPTY_SCRIPT, raw_override: "" }, true), "script-raw_override");
    expect(help).toBe(RAW_SCRIPT_COPILOT_HELP);
    expect(help.toLowerCase()).toContain("system prompt");
    // The correction to the observed failure: it must not be a brochure paragraph.
    expect(help.toLowerCase()).toContain("not a paragraph about the company");
    // The platform's own shape, asked for by name — task flow and confirm-back (PROMPT-GUIDE
    // §2/§3), not an invented format.
    expect(help.toLowerCase()).toContain("task flow");
    expect(help.toLowerCase()).toContain("confirm");
  });

  it("tells the copilot NOT to restate the platform-owned layers", () => {
    const help = helpFor(
      scriptCopilotFields({ ...EMPTY_SCRIPT, raw_override: "" }, true),
      "script-raw_override",
    ).toLowerCase();
    // compose_engine_prompt adds these around the client script on every call; a second copy
    // is drift. The steer must say so, so the model does not duplicate them.
    expect(help).toContain("do not");
    expect(help).toContain("recording");
    expect(help).toContain("guardrails");
  });

  it("is the only field raw mode declares — the structured lists are ignored while raw", () => {
    const fields = scriptCopilotFields({ ...EMPTY_SCRIPT, raw_override: "" }, true);
    expect(fields.map((f) => f.id)).toEqual(["script-raw_override"]);
  });
});

describe("the structured-mode steer", () => {
  it("keeps the opening line a greeting, pointing identity/flow at the sections below", () => {
    const help = helpFor(scriptCopilotFields(STRUCTURED, false), "script-opening_line");
    expect(help).toBe(OPENING_LINE_COPILOT_HELP);
    expect(help.toLowerCase()).toContain("greeting");
    expect(help.toLowerCase()).toContain("not a description of the company");
  });

  it("carries the task-flow steer on every existing stage row", () => {
    const fields = scriptCopilotFields(STRUCTURED, false);
    expect(helpFor(fields, "script-stages-0-instruction")).toBe(STEP_COPILOT_HELP);
    expect(helpFor(fields, "script-stages-1-instruction")).toBe(STEP_COPILOT_HELP);
    expect(STEP_COPILOT_HELP.toLowerCase()).toContain("hint");
  });

  it("declares the sections, then each stage, push-back and quick-fact row", () => {
    const ids = scriptCopilotFields(STRUCTURED, false).map((f) => f.id);
    expect(ids).toEqual([
      "script-business_line",
      "script-identity",
      "script-goal",
      "script-outbound_purpose",
      "script-opening_line",
      "script-stages-0-instruction",
      "script-stages-0-sounds_like",
      "script-stages-1-instruction",
      "script-stages-1-sounds_like",
      "script-ending",
      "script-faqs-0-question",
      "script-faqs-0-answer",
    ]);
  });

  it("declares no list rows on a fresh script — the copilot cannot grow the lists", () => {
    // paths.ts refuses a fill naming a row that does not exist.
    const ids = scriptCopilotFields(EMPTY_SCRIPT, false).map((f) => f.id);
    expect(ids).toEqual([
      "script-business_line",
      "script-identity",
      "script-goal",
      "script-outbound_purpose",
      "script-opening_line",
      "script-ending",
    ]);
  });
});
