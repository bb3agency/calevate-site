"use client";

import type { CopilotFact, CopilotField } from "@/lib/copilot/types";
import type { CallScript, ScriptProposal } from "@/lib/api/script";
import type { SaveState } from "./scriptDraft";

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
 * around this text on every call and a second copy is drift: the AI and recording notices
 * (`compose_opening_line`, D-163; separate from the opening line, D-708), the speaking-style / brevity guidance (`VOICE_STYLE_GUIDANCE`,
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
  "business-specific rules. Instructions in plain English, one idea per line; the words the " +
  "agent says, in the callers' spoken language. Do NOT write the platform's " +
  "own rules here — the AI and recording notices, the speaking-style and brevity guidance, the " +
  "always-be-truthful rule and the general guardrails are added automatically around this " +
  "text, so repeating them only duplicates them. The agent's greeting goes on the line after " +
  "one that reads [OPENING], at the top.";

/**
 * The structured opener is a GREETING, not the place for identity/flow prose — those have
 * their own sections below it, and the model needs telling so it does not pour a whole
 * system prompt into the first box it sees.
 */
export const OPENING_LINE_COPILOT_HELP =
  "The agent's greeting, the line it opens every call with. When the agent's AI or recording " +
  "notice is switched on, that notice is said just before this line; when both are off, this is " +
  "the first thing the caller hears. Do not repeat the AI or recording notice here. Keep it a " +
  "short, warm spoken greeting that names the business and offers help — not a description " +
  "of the company. The agent's identity, goal, stages, objections and quick facts go in " +
  "their own sections, not here.";

/** The agent's role: plain English instructions, not a brochure. */
export const IDENTITY_COPILOT_HELP =
  "Who the agent is and its job on the phone, in one or two plain English sentences " +
  '("You answer the phone for the shop and take orders"). Not a description of the company ' +
  "for customers, and nothing about being an AI or about recording: the platform adds those.";

/**
 * One task-flow step. The steer keeps it a loose spoken instruction (PROMPT-GUIDE §2/§4:
 * "hints, not a rigid script") rather than a paragraph or a restated platform rule.
 */
export const STEP_COPILOT_HELP =
  "One stage of the call — a short plain-English instruction the agent follows in spirit, " +
  'like "ask what the caller needs" or "take their name and read it back to confirm". A hint, ' +
  "not a rigid line to read out and not a description of the company.";

/** A stage in "say" mode: the agent says its text as written, so it is a spoken line. */
export const SAY_STEP_COPILOT_HELP =
  "One stage of the call that the agent says word for word, so write exactly what the caller " +
  "hears, in the callers' spoken language and everyday words: one or two short spoken " +
  "sentences, not an instruction and not a description of the company.";

/**
 * The `<field>` list the copilot sees for this screen. Raw mode declares the one body box;
 * structured mode declares the script v2 sections and each existing stage, push-back and
 * quick-fact row. Ids are `script-<path-with-dots-as-dashes>`, the derivation
 * `ScriptBuilder`'s `apply` reverses (the same idea as `intakeFieldId`).
 *
 * Each box is marked for the server's fill check (D-831, D-832): a line callers hear carries
 * the call language (`spokenLanguage`, no textbook words), an instruction to the in-call
 * model is `instruction` (plain English). The fields of `script_assist._instruction_fields`
 * and `_spoken_fields`, so Pip's fills and the AI's drafts keep one rule. The raw body mixes
 * both, so it is marked spoken only: its instructions are English, which leaves any textbook
 * word in a spoken line, and an English rule over the whole body would refuse its greeting.
 */
export function scriptCopilotFields(script: CallScript, raw: boolean, language?: string): CopilotField[] {
  // The lines callers hear, as against the instructions the in-call model reads (D-832).
  const spoken = (field: CopilotField): CopilotField => (language ? { ...field, spokenLanguage: language } : field);
  const instruction = (field: CopilotField): CopilotField => ({ ...field, instruction: true });
  if (raw) {
    return [
      spoken({
        id: "script-raw_override",
        label: "Script body (raw)",
        type: "textarea",
        value: script.raw_override ?? "",
        help: RAW_SCRIPT_COPILOT_HELP,
      }),
    ];
  }

  const text = (id: string, label: string, value: string, help?: string): CopilotField => ({
    id,
    label,
    type: "textarea",
    value,
    ...(help ? { help } : {}),
  });
  return [
    instruction(text("script-business_line", "Your business in one line", script.business_line)),
    instruction(text("script-identity", "The agent's role", script.identity, IDENTITY_COPILOT_HELP)),
    instruction(text("script-goal", "What a good call achieves", script.goal)),
    instruction(text("script-outbound_purpose", "Why you are calling", script.outbound_purpose)),
    spoken(text("script-opening_line", "Opening line", script.opening_line, OPENING_LINE_COPILOT_HELP)),
    ...script.stages.flatMap((stage, index) => [
      stage.mode === "say"
        ? spoken(
            text(
              `script-stages-${index}-instruction`,
              `Stage ${index + 1}, said word for word`,
              stage.instruction,
              SAY_STEP_COPILOT_HELP,
            ),
          )
        : instruction(text(`script-stages-${index}-instruction`, `Stage ${index + 1}`, stage.instruction, STEP_COPILOT_HELP)),
      spoken(text(`script-stages-${index}-sounds_like`, `How stage ${index + 1} sounds`, stage.sounds_like ?? "")),
    ]),
    ...script.objections.flatMap((o, index) => [
      text(`script-objections-${index}-objection`, `Push-back ${index + 1}`, o.objection),
      instruction(text(`script-objections-${index}-response`, `Answer to push-back ${index + 1}`, o.response)),
    ]),
    instruction(text("script-ending", "How the call ends", script.ending)),
    ...script.faqs.flatMap((faq, index) => [
      text(`script-faqs-${index}-question`, `Quick fact ${index + 1} question`, faq.question),
      text(`script-faqs-${index}-answer`, `Quick fact ${index + 1} answer`, faq.answer),
    ]),
  ];
}

/** What the Script tab shows besides its fields, as the facts Pip reads (D-832). */
export interface ScriptScreenState {
  /** The suggestion waiting on this screen; null when none; undefined while it loads. */
  proposal: Pick<ScriptProposal, "status"> | null | undefined;
  /** The owner added the last suggestion to the draft on this screen, and none is waiting since. */
  keptSuggestion: boolean;
  save: SaveState;
  /** Something in the draft is not live yet. */
  unpublished: boolean;
  liveStep: string;
}

/**
 * THE PRESENT, SO AN EARLIER TURN CANNOT STAND IN FOR IT. Pip's own earlier answer ("I am
 * drafting your script") is replayed as history; without these facts that was the latest
 * thing Pip knew, so after the owner had kept the suggestion and the draft had saved, Pip
 * offered to prepare it again and filled fields nobody asked about (founder, 19 Oct 2026).
 */
export function scriptCopilotFacts(state: ScriptScreenState): CopilotFact[] {
  const facts: CopilotFact[] = [];
  const suggestion = suggestionLine(state);
  if (suggestion) facts.push({ key: "pip_suggestion", label: "Pip's script suggestion", value: suggestion });
  facts.push({ key: "draft", label: "The draft", value: draftLine(state) });
  return facts;
}

function suggestionLine({ proposal, keptSuggestion }: ScriptScreenState): string | null {
  if (proposal === undefined) return null;
  if (proposal === null) {
    return keptSuggestion ? "None waiting. The last one was added to the draft." : "None waiting.";
  }
  if (proposal.status === "drafting") return "Being written. It appears on this screen in about half a minute.";
  if (proposal.status === "failed") return "Could not be written. It can be asked for again.";
  return "Waiting on this screen for review: the owner adds the changes they want to the draft, or dismisses it.";
}

function draftLine({ save, unpublished, liveStep }: ScriptScreenState): string {
  const live = unpublished
    ? `Changes not live yet: they go live when ${liveStep} is pressed.`
    : "Nothing waiting to go live.";
  switch (save.kind) {
    case "clean":
      return `Saved as a draft. ${live}`;
    case "waiting":
    case "saving":
      return `Being saved as a draft by itself. ${live}`;
    case "held":
      return save.reason;
    case "conflict":
      return "Changed in another window; this copy is not saved until the owner picks which to keep.";
    case "failed":
      return "Could not be saved; the owner can try again.";
    case "read-only":
      return "This person can read the script but not change it.";
  }
}

/** The toolbar's control that puts the draft live (`ScriptToolbar`, `PutLive`). */
export const PUT_LIVE = "Put it live";
