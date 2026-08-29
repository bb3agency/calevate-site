"use client";

import type { CopilotField } from "@/lib/copilot/types";
import type { CallScript } from "@/lib/api/script";

/**
 * The call-script screen, declared to the screen assistant — the FIELDS half.
 *
 * Split out of `ScriptBuilder.tsx` and pure, for the reason `intakeSurface.ts` is: a
 * screen's declaration is the one thing the copilot reasons over, so it is worth a test of
 * its own (`scriptSurface.test.ts`) rather than one reachable only by mounting the whole
 * editor behind its query hooks. The apply path and the variable facts stay in the
 * component — they close over its `setScript` state — this is the part that carries no
 * state and every word of which the model reads.
 *
 * ## Why the `help` on these fields is longer than a form hint usually is
 *
 * THE SCRIPT IS THE AGENT'S SYSTEM PROMPT. `PromptVersion.body` (raw) and the compiled
 * `structured_script` are fed verbatim to the in-call LLM through `compose_engine_prompt`
 * (`packages/shared/src/calevate_shared/engine.py`) — they are not marketing copy and not
 * a description of the company. Left to the generic "draft sensible values" instruction in
 * the copilot's system prompt, the model writes a brochure paragraph ("You are an AI voice
 * agent for X, a company providing excellent care…") because nothing on the screen tells it
 * these boxes ARE a system prompt. The `help` is that missing context, and `help` is the
 * right channel for it (not the copilot's byte-identical cacheable system prompt, which is
 * per-request-invariant by design — see `apps/api/copilot/prompt.py`): it rides the SCREEN
 * STATE the same way every other per-field hint does, changes nothing about the safety model
 * (every fill is still re-validated server-side and nothing is saved until Save), and is
 * exactly where `intakeSurface.ts` puts the same kind of steer.
 *
 * The drafting shape it asks for MIRRORS what the platform already defines — the block order
 * in `docs/PROMPT-GUIDE.md` §2 and the sections `call_script.py::compile_call_script` emits
 * ([OPENING] / [TASK FLOW] / [FAQ] / [END CALL]) — never a new format. It deliberately tells
 * the model NOT to write the platform-owned layers, because `compose_engine_prompt` adds them
 * around this text on every call and a second copy is drift: the AI-and-recording opening
 * (`compose_opening_line`, D-163), the speaking-style / brevity guidance (`VOICE_STYLE_GUIDANCE`,
 * D-479), the always-truthful floor (`TRUTHFUL_ANSWER_DIRECTIVE`, hard rule 5) and the generic
 * guardrails block (`GUARDRAILS_BLOCK`). The client's half is identity + what to say + task
 * flow + client-specific rules, which is precisely what this asks for.
 */

/**
 * The raw box holds the WHOLE prompt, so its steer is the whole doctrine. This is the field
 * the founder's complaint is about — on a fresh script the structured lists are empty and
 * `paths.ts` refuses a fill that would grow them, so RAW mode is where the copilot actually
 * authors a script from nothing, and where a brochure paragraph does the most damage.
 */
export const RAW_SCRIPT_COPILOT_HELP =
  "This box IS the agent's system prompt: it is sent word-for-word to the model that speaks " +
  "to the caller, not shown to anyone as marketing. Draft it as a spoken-agent system prompt, " +
  "not a paragraph about the company. Give it a short identity line (who the agent is, the " +
  "business name, its role, the language), then the call goal as a loose task flow — greet, " +
  "understand the need, answer or qualify, capture the details, read each value back to " +
  "confirm, agree the next step, wrap up — plus the specific things to collect and any " +
  "business-specific rules or what to do when it does not know (offer a callback). Short " +
  "directive sentences in Telugu or Tenglish, one idea per line. Do NOT write the platform's " +
  "own rules here — the AI-and-recording opening, the speaking-style and brevity guidance, the " +
  "always-be-truthful rule and the general guardrails are added automatically around this " +
  "text, so repeating them only duplicates them.";

/**
 * The structured opener is a GREETING, not the place for identity/flow prose — those have
 * their own sections below it, and the model needs telling so it does not pour a whole
 * system prompt into the first box it sees.
 */
export const OPENING_LINE_COPILOT_HELP =
  "The first thing the caller hears, after the platform's AI-and-recording sentences. Keep it " +
  "a short, warm spoken greeting that names the business and offers help — not a description " +
  "of the company. The agent's identity, the task flow, the questions to ask and the rules go " +
  "in the steps, FAQ and end-call sections below, not here.";

/**
 * One task-flow step. The steer keeps it a loose spoken instruction (PROMPT-GUIDE §2/§4:
 * "hints, not a rigid script") rather than a paragraph or a restated platform rule.
 */
export const STEP_COPILOT_HELP =
  "One step of the call's task flow — a short spoken instruction the agent follows in spirit, " +
  'like "ask what the caller needs" or "take their name and read it back to confirm". A hint, ' +
  "not a rigid line to read out and not a description of the company.";

/**
 * The `<field>` list the copilot sees for this screen. Raw mode declares the one body box;
 * structured mode declares the opener, each existing step and FAQ row, the don't-know line
 * and each end-call rule. Ids are `script-<path-with-dots-as-dashes>`, the derivation
 * `ScriptBuilder`'s `apply` reverses (the same idea as `intakeFieldId`).
 */
export function scriptCopilotFields(script: CallScript, raw: boolean): CopilotField[] {
  if (raw) {
    return [
      {
        id: "script-raw_override",
        label: "Script body (raw)",
        type: "textarea",
        value: script.raw_override ?? "",
        help: RAW_SCRIPT_COPILOT_HELP,
      },
    ];
  }

  return [
    {
      id: "script-opening_line",
      label: "Opening line",
      type: "textarea",
      value: script.opening_line,
      help: OPENING_LINE_COPILOT_HELP,
    },
    ...script.steps.map((step, index) => ({
      id: `script-steps-${index}-instruction`,
      label: `Step ${index + 1}`,
      type: "textarea" as const,
      value: step.instruction,
      help: STEP_COPILOT_HELP,
    })),
    ...script.faqs.flatMap((faq, index) => [
      {
        id: `script-faqs-${index}-question`,
        label: `FAQ ${index + 1} question`,
        type: "text" as const,
        value: faq.question,
      },
      {
        id: `script-faqs-${index}-answer`,
        label: `FAQ ${index + 1} answer`,
        type: "textarea" as const,
        value: faq.answer,
      },
    ]),
    {
      id: "script-faq_fallback",
      label: "What it says when it does not know",
      type: "textarea",
      value: script.faq_fallback,
    },
    ...script.end_call_extra_rules.map((rule, index) => ({
      id: `script-end_call_extra_rules-${index}`,
      label: `End-of-call rule ${index + 1}`,
      type: "text" as const,
      value: rule,
    })),
  ];
}
