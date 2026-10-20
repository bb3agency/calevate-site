import { describe, expect, it } from "vitest";

import {
  OPENING_LINE_COPILOT_HELP,
  RAW_SCRIPT_COPILOT_HELP,
  PUT_LIVE,
  SAY_STEP_COPILOT_HELP,
  STEP_COPILOT_HELP,
  scriptCopilotFacts,
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

describe("the lines callers hear, and the screen's present state (D-832)", () => {
  it("marks the opening line and each example line as spoken in the agent's language, and nothing else", () => {
    const fields = scriptCopilotFields(STRUCTURED, false, "te-IN");
    const spoken = fields.filter((f) => f.spokenLanguage === "te-IN").map((f) => f.id);
    expect(spoken).toEqual(["script-opening_line", "script-stages-0-sounds_like", "script-stages-1-sounds_like"]);
    expect(scriptCopilotFields(STRUCTURED, false).some((f) => f.spokenLanguage)).toBe(false);
  });

  it("marks a stage said word for word as spoken, with its own help, and a guide stage as an instruction", () => {
    const script: CallScript = {
      ...STRUCTURED,
      stages: [{ ...STRUCTURED.stages[0], mode: "say" }, STRUCTURED.stages[1]],
    };
    const fields = scriptCopilotFields(script, false, "te-IN");
    const say = fields.find((f) => f.id === "script-stages-0-instruction");
    expect(say?.spokenLanguage).toBe("te-IN");
    expect(say?.instruction).toBeUndefined();
    expect(say?.help).toBe(SAY_STEP_COPILOT_HELP);
    const guide = fields.find((f) => f.id === "script-stages-1-instruction");
    expect(guide?.instruction).toBe(true);
    expect(guide?.spokenLanguage).toBeUndefined();
  });

  it("marks every instruction the in-call model reads, and no line callers hear", () => {
    const fields = scriptCopilotFields(
      { ...STRUCTURED, objections: [{ objection: "Too costly", response: "Say why it is worth it." }] },
      false,
      "te-IN",
    );
    expect(fields.filter((f) => f.instruction).map((f) => f.id)).toEqual([
      "script-business_line",
      "script-identity",
      "script-goal",
      "script-outbound_purpose",
      "script-stages-0-instruction",
      "script-stages-1-instruction",
      "script-objections-0-response",
      "script-ending",
    ]);
    expect(fields.some((f) => f.instruction && f.spokenLanguage)).toBe(false);
  });

  it("marks the raw body spoken, never an instruction: it holds the greeting too", () => {
    const [body] = scriptCopilotFields({ ...EMPTY_SCRIPT, raw_override: "" }, true, "te-IN");
    expect(body.spokenLanguage).toBe("te-IN");
    expect(body.instruction).toBeUndefined();
  });

  it("says a kept suggestion is no longer waiting and the draft is saved but not live", () => {
    const facts = scriptCopilotFacts({
      proposal: null,
      keptSuggestion: true,
      save: { kind: "clean", savedAt: "2026-10-19T10:05:00+00:00" },
      unpublished: true,
      liveStep: PUT_LIVE,
    });
    expect(facts).toEqual([
      { key: "pip_suggestion", label: "Pip's script suggestion", value: "None waiting. The last one was added to the draft." },
      {
        key: "draft",
        label: "The draft",
        value: "Saved as a draft. Changes not live yet: they go live when Put it live is pressed.",
      },
    ]);
  });

  it("says a suggestion is being written or waiting, and leaves it out while it loads", () => {
    const base = { keptSuggestion: false, save: { kind: "saving" as const }, unpublished: false, liveStep: PUT_LIVE };
    const value = (status: "drafting" | "ready") =>
      scriptCopilotFacts({ ...base, proposal: { status } }).find((f) => f.key === "pip_suggestion")?.value;
    expect(value("drafting")).toMatch(/^Being written/);
    expect(value("ready")).toMatch(/^Waiting on this screen for review/);
    expect(scriptCopilotFacts({ ...base, proposal: undefined }).map((f) => f.key)).toEqual(["draft"]);
  });
});
