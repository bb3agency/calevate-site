# Prompting practices against our prompts (research, 14 Oct 2026)

What the leading vendors and papers say about prompting, for each of our four LLM surfaces,
and where our prompts differ. It changes no code. Every external claim cites the page read on
**14 Oct 2026** (the read date for every row below unless stated). Evidence classes follow
`docs/RESEARCH-DISCIPLINE.md`:

- **VERIFIED-VENDOR-DOCS**: read from the vendor's own documentation page this session.
- **VENDOR-PUBLISHED**: the vendor's blog or engineering post.
- **PAPER**: a peer-reviewed or arXiv paper.
- **REPORTED**: seen only in a search summary or a third-party page. Not used as a basis for
  any recommendation.

The WebFetch tool returns a summary of each page made by a smaller model. Short quotes below
are the ones it returned verbatim.

Models we actually run, as the repo states them (repo claims, not re-verified here):

- **In-call:** ThinnestAI's Prana [Voice] or GPT-OSS 120B. With `thinnest_own_model` on,
  Gemini 2.5 Flash-Lite on our key (D-764, off by default).
- **Pip copilot:** a console-chosen Gemini fast/planning tier (`copilot/model_tiers.py`).
- **Dashboard AI:** Azure OpenAI gpt-4o-mini.
- **First extraction:** Sarvam `sarvam-105b` (`calevate_shared/engine.py:473`).

## 1. Summary: where the sources agree

1. **Labelled sections in a fixed order, one topic each.** Persona and role come first. Rules
   come next, in the order they apply. Guardrails come last or in their own clearly named
   block. (OpenAI Realtime, Google Live API, ElevenLabs, Vapi, Deepgram, LiveKit, Anthropic.)
2. **Say each rule once and resolve contradictions.** Contradictory or vague instructions cost
   more on newer models (OpenAI GPT-5 guide, Realtime guide, Deepgram "define tone once",
   ElevenLabs "define tone once").
3. **On a voice call, turns are short and carry one question.** Every voice vendor gives 1-2
   (sometimes up to 3) sentences per turn and one question per turn. Numbers, dates and IDs
   are written for the ear. Codes are read character by character and confirmed back.
4. **Put enforcement in code, not in emphatic prompt text.** If a rule keeps being broken, move
   it to a server-side gate (Deepgram, Vapi, OWASP as already cited in `engine.py`). Avoid ALL
   CAPS and threats: they make newer models over-apply a rule (Anthropic, OpenAI GPT-4.1).
5. **Sample phrases get copied.** Give a few varied examples and tell the model to vary them
   (OpenAI Realtime, GPT-4.1). Google recommends always including few-shot examples, but not
   too many.
6. **Keep the stable prefix first and the variable content last** to get prompt caching
   (Azure OpenAI, OpenAI, Gemini implicit caching).
7. **Tools.** Use a small, non-overlapping set. Write each description as you would brief a new
   hire, and say when to use the tool and when not to. Keep known arguments out of the model's
   hands. Confirm before irreversible actions. Return errors that say how to recover. (Anthropic,
   OpenAI, Google.)
8. **Structured output.** Use a strict schema where it is offered. Make optional fields a
   `["type","null"]` union. Order keys deliberately, because generation follows schema order.
   Validate values in code, because a valid schema does not mean the values are right (OpenAI,
   Google).
9. **LLM judges.** Use pass/fail or pairwise rather than open-ended scores. Write a clear rubric,
   and put reasoning before the verdict. Use a different (ideally stronger) model than the one
   being judged. Calibrate against human labels before trusting it. Watch for position,
   verbosity and self-preference bias. (OpenAI evals, Anthropic evals, Zheng et al. 2023.)

## 2. Sources read

| # | Source | URL | Class | What it gave |
|---|---|---|---|---|
| S1 | OpenAI, "Prompting Realtime models" | developers.openai.com/api/docs/guides/realtime-models-prompting | VERIFIED-VENDOR-DOCS | sections; "Direct answers: Use 1-2 short sentences."; "Only respond to clear audio or text."; "Don't repeat the same unclear-audio clarification twice."; alphanumerics read separately and confirmed; "Do not infer language from accent alone."; preambles ("Before any tool call, say one short line"); proactive vs confirm-first tools; escalation thresholds ("2 failed tool attempts", "3 consecutive no-match/no-input events"); samples are anchors that should be varied |
| S2 | OpenAI Cookbook, "Realtime Prompting Guide" (marked archived) | developers.openai.com/cookbook/examples/realtime_prompting_guide | VERIFIED-VENDOR-DOCS (partial: only the first 200k of 2M chars were readable; the rest is audio) | bullets beat paragraphs; Variety rule; CAPS for key rules; write thresholds in words; the model "closely follows sample phrases" |
| S3 | ElevenLabs, "Prompting guide" | elevenlabs.io/docs/agents-platform/best-practices/prompting-guide | VERIFIED-VENDOR-DOCS (no date shown) | markdown sections; a `# Guardrails` heading; prompts over 2,000 tokens add latency and cost; tone defined once; text normalisation done in the prompt (default) or by a post-LLM normaliser; per-tool error handling; escalate after two failures; one change at a time; simulation regression tests |
| S4 | Vapi, "Prompting guide" | docs.vapi.ai/prompting-guide | VERIFIED-VENDOR-DOCS | six sections; "Keep responses to one or two sentences maximum."; one question per turn; silence: wait, then check in once; don't end on "ok"/"hmm"; banlists of 3-5 items plus a positive principle; at least three few-shot examples (happy, edge, error); the prompt is not a security boundary |
| S5 | Deepgram, "Prompting voice agents" | developers.deepgram.com/docs/prompting-voice-agents | VERIFIED-VENDOR-DOCS | ten sections; speaking-style rules near the top; the length cap is a "ceiling, not a target"; 1-2 sentences per turn; write data for the ear; call functions without narrating, with filler injected by the server; no bracketed cues (TTS reads them); "prompt as policy, server code as enforcement"; every out-of-scope rule paired with a fallback line; change one section at a time |
| S6 | LiveKit, "Prompting guide" | docs.livekit.io/agents/start/prompting | VERIFIED-VENDOR-DOCS | identity first; plain-text output; "one to three sentences"; one question at a time; summarise tool results and never recite IDs; on failure say so once, then offer a fallback; insert known user data so the agent does not re-ask; rotate openers; simulated-user tests |
| S7 | Google, "Live API best practices" (updated 15 Sep 2026) | ai.google.dev/gemini-api/docs/live-api/best-practices | VERIFIED-VENDOR-DOCS | persona, then conversational rules, then guardrails, in that order; separate one-time steps from loops; one tool call per sentence; tool invocation conditions; force the language explicitly; use prompt chaining rather than multi-page prompts |
| S8 | Google, "Prompt design strategies" (updated 13 Oct 2026) | ai.google.dev/gemini-api/docs/prompting-strategies | VERIFIED-VENDOR-DOCS | "always include few-shot examples", in a consistent format and not too many; constraints in the system instruction; with long context, instructions go at the end; one delimiter style; avoid overly persuasive language |
| S9 | Google, "Context caching" (updated 13 Oct 2026) | ai.google.dev/gemini-api/docs/caching | VERIFIED-VENDOR-DOCS | implicit caching on "all Gemini 2.5 and newer models"; minimum 2,048 tokens on 2.5 Flash and Pro; Flash-Lite not named; put large common content first; no discount figure given |
| S10 | Google, "Function calling" (best practices updated 23 Sep 2026) | ai.google.dev/gemini-api/docs/function-calling | VERIFIED-VENDOR-DOCS | "Keep active set to 10-20 tools maximum."; specific types and enums; validate calls before executing |
| S11 | Google, "Structured output" (updated 13 Oct 2026) | ai.google.dev/gemini-api/docs/structured-output | VERIFIED-VENDOR-DOCS | the schema guarantees syntax, not correctness ("always validate values in your application"); null via a type union |
| S12 | Microsoft, "Prompt caching with Azure OpenAI" (ms.date 11 Aug 2026) | learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/prompt-caching | VERIFIED-VENDOR-DOCS | at least 1,024 tokens, and the first 1,024 must be identical; GPT-4o and newer cache in memory (5-10 min, at most 1 h); messages, tools and the structured-output schema are all cached, and the schema "is appended as a prefix to the system message"; stable content first and dynamic content last |
| S13 | OpenAI, "Structured Outputs" | developers.openai.com/api/docs/guides/structured-outputs | VERIFIED-VENDOR-DOCS | keys are "produced in the same order as the ordering of keys in the schema"; all fields required, with optional fields as a null union; `additionalProperties: false`; supported from gpt-4o-mini |
| S14 | OpenAI, "Function calling" | developers.openai.com/api/docs/guides/function-calling | VERIFIED-VENDOR-DOCS | "Aim for fewer than 20 functions available at the start of a turn" (a soft guideline); the intern test; enums so invalid states cannot be expressed; don't make the model fill arguments the code knows |
| S15 | OpenAI Cookbook, "GPT-4.1 Prompting Guide" | developers.openai.com/cookbook/examples/gpt4-1_prompting_guide | VERIFIED-VENDOR-DOCS (archived) | with long context, put instructions before and after it; a later instruction wins a conflict; avoid ALL CAPS and bribes; "always call a tool" makes the model invent inputs; sample phrases repeat verbatim unless told to vary |
| S16 | OpenAI Cookbook, "GPT-5 prompting guide" | developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide | VERIFIED-VENDOR-DOCS (archived) | eagerness control with tool-call budgets and early-stop criteria; contradictions hurt more; use the prompt optimizer to find conflicts; metaprompting |
| S17 | Anthropic, "Prompting best practices" | platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices | VERIFIED-VENDOR-DOCS | give the reason behind a rule; say what to do rather than what not to do; "dial back any aggressive language" (CRITICAL/MUST makes the model over-trigger) |
| S18 | Anthropic, "Writing effective tools for agents" (11 Sep 2025) | anthropic.com/engineering/writing-tools-for-agents | VENDOR-PUBLISHED | consolidate tools; namespacing; return names rather than UUIDs; a concise/detailed response option; actionable errors; evaluate tools on real tasks |
| S19 | Anthropic, "Effective context engineering for AI agents" (29 Sep 2025) | anthropic.com/engineering/effective-context-engineering-for-ai-agents | VENDOR-PUBLISHED | "right altitude"; "smallest possible set of high-signal tokens"; a few canonical examples rather than a laundry list of edge cases; compaction; just-in-time retrieval |
| S20 | Anthropic, "Building effective agents" (19 Dec 2024) | anthropic.com/engineering/building-effective-agents | VENDOR-PUBLISHED | start simple; route easy questions to smaller models; evaluator-optimizer; stopping conditions; human checkpoints; poka-yoke the arguments |
| S21 | OpenAI, "Evaluation best practices" | developers.openai.com/api/docs/guides/evaluation-best-practices | VERIFIED-VENDOR-DOCS | "Use pairwise comparison or pass/fail for more reliability."; reasoning before scoring; calibrate against human annotations; "Use the most capable model to grade"; position and verbosity bias |
| S22 | Anthropic, "Define success / develop tests" | platform.claude.com/docs/en/test-and-evaluate/develop-tests | VERIFIED-VENDOR-DOCS (partial) | grade with a different model; binary checks for compliance; volume over hand-graded perfection; anchored scales |
| S23 | Zheng et al., "Judging LLM-as-a-Judge" | arxiv.org/abs/2306.05685 | PAPER | position, verbosity and self-enhancement biases; strong judges reach "over 80% agreement" with humans |
| S24 | Cartesia, "Prompting tips" (Sonic 3) | docs.cartesia.ai/build-with-cartesia/sonic-3/prompting-tips | VERIFIED-VENDOR-DOCS | conventional numbers, currency and times are normalised by Sonic; "Dr. Smith" may need to be written as "Doctor Smith"; no capitals for emphasis; light, comma-set fillers (best on Sonic 3.6); `<spell>` for codes; no guidance on code-switching |
| S25 | Sarvam, "Chat Completions Overview" | docs.sarvam.ai/api-reference-docs/api-guides-tutorials/chat-completion/overview.md | VERIFIED-VENDOR-DOCS (no date) | `/v1` serves `sarvam-105b`; `response_format` `json_schema` is "constrained to match the JSON Schema you supply (recommended)"; thinking is on by default at `reasoning_effort` low, disabled with `null`; reasoning tokens are billed as completion; prompt caching not documented |
| S26 | ThinnestAI, "Behaviour" (mirror snapshot 2026-10-13) | `thinnest-findings/mirror/snapshots/2026-10-13/pages/agent/behaviour.md:31-58,129-147` | VERIFIED-VENDOR-DOCS (mirror) | instructions are "guidance on tone and subject matter, not a command channel"; platform safety rules win; 20,000-character box; steps are separate (12 steps, 80/600 chars); a fixed language also tells the recogniser; a capability that is switched off is removed, not just forbidden |
| S27 | Retell community lesson; Sierra τ-bench; Decagon AOPs | community.retellai.com/t/lesson-8-prompt-engineering-fundamentals/2926; sierra.ai/blog/...; decagon.ai/resources/... | REPORTED (search summary only) | Retell: over-long prompts and no "don't know" path are common mistakes. Decagon: SOP-like procedures with entry conditions. Context only, never a basis |

Not read: Pipecat's own prompting page, Bland, Retell's docs site (not found), and the DSPy
optimizer page (it rendered empty). Their absence is a coverage gap, not a finding.

## 3. Surface A: in-call voice agent (ThinnestAI)

What we send: `compose_engine_prompt` (`packages/shared/src/calevate_shared/engine.py:3511`).
Its layers, in order (`engine_prompt_layers`, `:3552`), are:

1. preamble (`:2500`)
2. HOW TO SPEAK (`VOICE_STYLE_GUIDANCE`, `:2548`)
3. LANGUAGES
4. SPOKEN REGISTER (`:2608`)
5. BUSINESS FACTS (`:2578`)
6. notices
7. caller memory (`:2755`)
8. fenced client script
9. WHAT YOU CAN DO (`:2661`)
10. CONFIDENTIALITY (`:2415`)
11. truthful answers (`:2356`)

The script's stages go to ThinnestAI as native `steps` (`call_script.native_steps`,
`packages/shared/src/calevate_shared/call_script.py:722`). ThinnestAI's own platform rules sit
above all of this (S26).

### Practices

- **Structure.** Role and objective first, then personality and tone, context, pronunciations,
  tools, rules, flow, and safety/escalation (S1, S2). Google orders it persona, rules,
  guardrails (S7). Deepgram puts speaking style near the top (S5).
- **Turns.** 1-2 short sentences, one question, then wait (S1, S4, S5, S6). Cap the length in
  code where you can (S5).
- **Unclear audio.** Respond only to clear speech. Never guess. Don't repeat the same
  clarification twice (S1).
- **Silence.** Wait, then check in once (S4). Cover silence in the prompt (S5).
- **Escalation.** Give numeric thresholds in words, such as two failed attempts or three
  no-match events, plus a fixed line said before the hand-off (S1, S3, S4).
- **Tool preambles.** The sources disagree; see §7.
- **Variety.** Add a variety rule, and tell the model not to always use the sample phrases (S1,
  S2, S6).
- **Examples.** Google says always include few-shot examples (S8). Vapi asks for at least three
  (S4). OpenAI warns that samples are copied (S1, S15).
- **Numbers and IDs.** Read each character separately, repeat the number exactly, and confirm
  (S1). Write for the ear (S5, S6).
- **Prompt as policy.** Enforcement belongs in code (S4, S5). ThinnestAI says the same of its
  own platform (S26).
- **Size and latency.** Prompts over 2,000 tokens add latency and cost (S3). The cap is a
  ceiling, not a target (S5). The system prompt is paid on every turn (S4).
- **Caching.** Stable prefix first (S9, S12). ThinnestAI reports `cachedInputTokens` per call
  (repo memory of `calls/get-call.md:1105-1135`, snapshot 2026-10-13). How their stack
  places our text in the prefix is UNKNOWN.

### Gap table

Locks: **HR5** = hard rule 5 truthful answers; **D-674** = `CONFIDENTIALITY_RULE`;
**BUDGET** = the instructions budget (`tests/agent_prompt_budget_test.py`); **SS** =
founder-reviewed spoken-style data (`spoken_style.json`, D-744); **PIN** = a test pins the
phrase.

| # | Current (file:line) | What we do | What leaders do | Recommended change | Effect | Risk | Touches |
|---|---|---|---|---|---|---|---|
| A1 | `engine.py:2567` | "Missed it? Ask them to repeat it, never guess." | Never repeat the same clarification twice; escalate after repeated no-match (S1) | Add to the same bullet: "never the same way twice; after two tries, offer what WHAT YOU CAN DO allows". The second half belongs in `_when_you_cannot_help_section` (`:2661`) so a script cannot undo it | Quality: fewer loops like the 11 Oct triple re-ask | Low. About 90 chars | BUDGET; `turn_checks` repeated_question |
| A2 | `engine.py:2661-2693` | No escalation threshold | Thresholds in words, plus a fixed line before the hand-off (S1, S3, S4) | One line: "If you still cannot understand or help after two tries, say so and {follow_up}." It reuses the existing call-back/business-will-get-back wording, so it stays true to the account | Quality, and trial honesty is kept | Low | BUDGET. Must keep the D-714 rule: no call back on trial |
| A3 | none | No silence rule | Check in once after silence, then close (S4, S5) | **Verify first** how ThinnestAI presents silence to the model (`voice.turnDetection`, the `goes_quiet` scenario). Add one line only if the model actually sees a silent turn. Ask in the next ThinnestAI email (`docs/vendor/thinnest-replies-2026-10-12.md` §13) | Quality | Medium: a rule about an event the model never sees is noise | BUDGET |
| A4 | `engine.py:2611-2612`; D-739 memory | No platform examples; examples live only in the client's `[EXAMPLE CALL]`. D-739 rejected platform examples because "the Pipecat output guard treats all platform text as never-to-say" | Few-shot strongly recommended (S8, S4). Founder research (memory f48a64c7): anchor the register with 2-3 example exchanges. Samples get copied, so mark them "vary" (S1, S15) | **The reason for the rejection is gone**: Pipecat was removed by D-763. Add 1-2 very short per-language exchanges to SPOKEN REGISTER from `spoken_style.json` `examples`, introduced as "how it sounds; never copy these words". Only for reviewed (`native_reviewed`) languages | Quality: register adherence, fewer formal words | Medium: verbatim copying and longer prompts. Measure the `formal_words` hit rate before and after | SS (founder review), BUDGET, `agent_intelligence_test` register format (PIN) |
| A5 | `engine.py:2500-2504`, `:3552` | Identity, goal and business live in the client script, after the platform layers, which measured about 4,500 chars on 10 Oct (REPORTED: D-714 memory, not re-measured) | Role and objective first (S1, S6, S7) | Make the preamble name the business and the job from `AgentConfig` (platform-composed and fence-safe), e.g. "You are the phone assistant for {business}, {answering calls / calling leads who asked}." Keep everything the client wrote inside the fence | Quality: persona adherence; agent replies anchored to the business sooner | Low-medium: the business name is client-supplied text, so cap its length and strip fence runs (as `clean_fact` does) | D-674/HR5 not touched; PIN on `PLATFORM_RULES_PREAMBLE` checks in tests |
| A6 | `engine.py:2548-2570` | About 15 bullets, many of them "never" | Keep banlists to 3-5 plus a positive principle (S4). Say what to do instead (S17) | Rewrite only where a positive form is shorter, e.g. "Speak in plain sentences" in place of the "no markdown, emoji, dashes..." list. Keep every PIN phrase, or move its test | Small token saving and less over-application | Medium: PINs, and the live-apply re-queue that any platform text change triggers | PIN (`agent_intelligence_test`), BUDGET |
| A7 | `engine.py:2558` | `"Dr Ravi", never "Dr. Ravi"` | Cartesia: write "Doctor Smith" if "Dr." is misread (S24) | Change the example to a full word ("Doctor Ravi"). Confirm by ear on ThinnestAI's own voices too (Clear does not use Cartesia) | Small quality gain | Low | PIN (`tests/agent_intelligence_test.py:162`) |
| A8 | `engine.py:2559-2561` | Prices and times in English words, never ₹ or digits | Cartesia normalises "$19.99" and "7:00 PM" itself (S24). ElevenLabs' default is the same in-prompt normalisation we use (S3) | **No change.** Words are the safe default: no normaliser sits between model and voice on ThinnestAI, and Cartesia's normalisation is not documented for Telugu text. Record the disagreement | n/a | n/a | SS (founder decision) |
| A9 | `engine.py:2568` | "After a tool or search, never narrate or greet again." | Sources conflict on preambles (S1 vs S5); see §7 | No change until ThinnestAI says whether it injects filler during a tool call (add to the next email) | n/a | n/a | none |
| A10 | `engine.py:3552-3590` (caller_memory before client_script) | A per-call memory block sits mid-prompt | Dynamic content last for caching (S9, S12) | **Measure first.** Read `cachedInputTokens` from `call.analysed` usage over own-model calls (`billing/own_model_prompt.py` already reads usage). Move the block only if cache hits are low. It sits before the script for injection framing, which outranks a cache win | Token cost on the own-model leg only | Medium: the security ordering argument at `:2755` | HR5 ordering (truthful block stays last) |
| A11 | `docs/PROMPT-GUIDE.md` §2 "Size budget: ≤ ~2,500 tokens"; this brief's "8,000-char budget" | Three different budgets are stated: PROMPT-GUIDE about 2,500 tokens; `engine/thinnest.py:241` `INSTRUCTIONS_MAX_CHARS = 20_000`; `tests/agent_prompt_budget_test.py:1-12` | ElevenLabs: over 2,000 tokens adds latency (S3). Deepgram: a ceiling, not a target (S5) | Fix PROMPT-GUIDE §2 to name the 20,000 box as the hard cap and keep a latency target of about 2,500 tokens. Report the per-agent token count (not chars) on the size panel, since Telugu chars cost about 1 token each (D-764 ASSUMPTION) | Docs truth; keeps prompts lean | None | docs only |
| A12 | `engine.py:2415-2428`, `:2356-2375` | D-674 and HR5 are composed after the script, and HR5 is last | Guardrails last and in a named block (S3, S7). A later instruction wins conflicts (S15) | **No change.** Our order already matches. Never shorten either block to win budget | n/a | n/a | HR5, D-674 |

## 4. Surface B: Pip copilot (client and admin)

What we send: `SYSTEM_PROMPT` (`apps/api/copilot/prompt.py:326`) after `ASSISTANT_IDENTITY`
(`:252`) and `CONVERSATIONAL_FRAMING` (`:315`). The last user message carries the screen, the
live state, `CLOSING_RULES` (`:525`) and the question (`build_messages`, `:815`). Tools come
from one byte-identical array per realm (`apps/api/copilot/service.py:899`). Settings:
`temperature=0.2`, `tool_choice="auto"` (`service.py:1132`), `MAX_TURNS = 6` (`:117`). The
admin realm gets `ADMIN_SYSTEM_PROMPT` (`admin_prompt.py:98`) plus admin reads on top of the
client set.

### Practices

- Write tool descriptions for a new hire, saying when to use the tool and when not to. Keep
  parameter names unambiguous and use enums (S10, S14, S18, S20).
- Keep the active tool set small: 10-20 on Gemini (S10), fewer than 20 on OpenAI as a soft
  guideline (S14). Avoid overlapping tools (S19). Consolidate tools (S18).
- Draw the line between proactive and confirm-first actions explicitly (S1, S16). Use human
  checkpoints and stopping conditions (S20).
- Return actionable errors (S18). Don't retry blindly (S1, S3).
- Avoid ALL CAPS and over-emphatic language (S15, S17). Google: avoid overly persuasive
  language (S8).
- With long context, put instructions before and after it (S15). This is our sandwich of
  `SYSTEM_PROMPT` and `CLOSING_RULES`.
- Stable prefix first, append-only history, and tools held constant for caching (S9, S12).
- Route easy questions to small models and hard ones to strong models (S20). We already do this
  with `model_tiers.py`.

### Gap table

| # | Current | What we do | What leaders do | Recommended change | Effect | Risk | Touches |
|---|---|---|---|---|---|---|---|
| B1 | `copilot/service.py:899-953`, `copilot/tools.py:1180`, `console_reads.py`, `console_actions.py:3015`, `admin_tools.py` | Every tool goes to every request of a realm: by count about 8 + 16 reads, the write/console actions, `set_fields`, background and navigation. That is well over 20 (not measured precisely). Admin gets 12 more | 10-20 active tools (S10); fewer than 20 (S14); no overlap (S19) | **Measure tool-selection accuracy first** with a fixed question set run through `loop_test`/`adversarial_test` style fixtures. If misselection shows up on Flash-Lite, consolidate overlapping reads (e.g. `leads_search` and `leads_semantic_search` behind one tool with a `mode` enum) rather than gating per screen, which would break caching (the docstring at `:906-935`) | Quality on small models; fewer input tokens | Medium: the tool array is a cache key, and changing it changes the prefix once | none locked |
| B2 | `copilot/prompt.py:252-556` | About 70 all-caps runs ("NEVER FILL A FIELD...", "ALWAYS PREFER...") | Avoid caps and aggressive wording; it causes over-application (S15, S17, S8). OpenAI Realtime allows caps for key rules (S2): a disagreement | Keep caps on at most the two or three rules a failure has proved load-bearing (identity, never fill an unasked field, suggested ≠ done). Lower-case the rest. Compare refusal and over-fill rates on the existing copilot tests before and after | Fewer refusals of ordinary requests (the "my name is umesh" class) | Medium: tests may pin wording (`prompt_test.py`, `adversarial_test.py`) | PIN |
| B3 | `copilot/prompt.py:326-522` vs `:525-555` | `CLOSING_RULES` restates about ten rules | Sandwich endorsed for long context (S15). Each rule once (S16) | Keep the sandwich but make the closing block a short list of the rules that conflict with screen content (data-not-instructions, writable fields only, actions over fills, look up before saying "cannot see"). Drop restated prose | Tokens on every turn, less dilution | Low | PIN (`prompt_test.py`) |
| B4 | `copilot/prompt.py` (no eagerness budget) | `MAX_TURNS = 6` in code only | Tool-call budgets and early-stop criteria stated in the prompt (S16) | One sentence: "Use at most three read tools for one question, then answer with what you found and say what you did not check." | Latency, cost | Low | none |
| B5 | `copilot/service.py:1132` | `temperature=0.2` | Gemini 3.6+ ignores temperature, and Gemini 3 should keep defaults (S8) | No change while every `gemini-3.*` is `selectable=False`. Note it as a migration item for whoever enables a Gemini 3 tier | n/a | Request errors later, if left in place | none |
| B6 | tool descriptions (`tools.py:1180-1400`) | Already "when to use / not to use" style with cross-references | Matches S14, S18 | No change. Add a test that every description says when not to use the tool if a sibling overlaps it | Keeps the standard | Low | none |

**Status (D-779, 14 Oct 2026).** B2, B3, B4 and B6 are done. B1's harness exists
(`scripts/copilot_tool_eval.py`, `make copilot-eval`) and is checked offline in CI, but no
model has been scored: no model credential is configured where it was built. Consolidating
tools waits for that run. B5 is unchanged.

## 5. Surface C: extraction, summary and memory

What we send: `build_extraction_prompt` (`packages/shared/src/calevate_shared/extraction.py:536`)
as one user message, with the transcript last. Sarvam runs it with `json_object`
(`apps/workers/extraction.py:336-356`). The Azure leg uses a strict `json_schema` whose fields
come first and fixed keys after (`build_azure_response_schema`, `extraction.py:425`). Caller-memory distillation uses
`_SYSTEM_PROMPT` (`apps/workers/caller_memory_distil.py:180`).

### Practices

- Use a strict schema where offered. Express optional fields as null unions. Order keys on
  purpose (S13). Validate in code (S11). We already do all of this on Azure, and the
  fields-before-summary order is deliberate (`extraction.py:456-466`).
- Say what to do with input that cannot produce a value (S13). We do this: "ABSENT MEANS NULL".
- Put instructions before and after long context (S15), or at the end of long context (S8).
- Always include few-shot examples, but not too many (S8).
- Run evals on every change and grow the golden set from logs (S21).

### Gap table

| # | Current | What we do | What leaders do | Recommended change | Effect | Risk | Touches |
|---|---|---|---|---|---|---|---|
| C1 | `apps/workers/extraction.py:353`; docstring `:266-268` | Sarvam gets `json_object` only. The code says Sarvam "publishes ... no per-request schema" | Sarvam `/v1` now documents `json_schema` Structured Outputs and calls it "recommended" (S25, VERIFIED-VENDOR-DOCS 14 Oct 2026) | Send the same strict schema (`build_azure_response_schema`) to Sarvam, degrading to `json_object` on a 400 exactly as the Azure leg does. Correct the docstring | Quality: no dropped or misspelt keys. Also lets `_first_json_object` become a fallback | Low-medium: confirm on our key with one golden run | `scripts/eval.py` golden set |
| C2 | `apps/workers/extraction.py:336-356` | No `reasoning_effort` sent, so Sarvam thinks at `low` by default (S25) and bills those tokens as completion tokens | Decide reasoning effort per task (S16) | Run the golden set with `reasoning_effort` `null` and `low`. Pick on `restraint`/`capture_wrong` and cost. Make it explicit either way so a vendor default change cannot move our cost silently | Cost, latency, or quality, whichever the run shows | Low | `EXTRACTION_MAX_TOKENS` headroom (reasoning tokens count against it) |
| C3 | `calevate_shared/extraction.py:565` | "The call is in Telugu, often code-mixed..." for every agent | Persona and context must match the input. Name the language explicitly (S7, S1) | Pass the agent's language(s) into `build_extraction_prompt` and say "The call is in {Telugu/Hindi/English}...". `ExtractionSchemaSpec` has no language today, so the pipeline must pass it | Quality on Hindi and English agents | Low. Golden set is mostly Telugu, so add Hindi and English cases | golden fixtures |
| C4 | `calevate_shared/extraction.py:651-652` | The transcript is the last thing in the prompt. No closing reminder | Instructions before and after (S15) | Append one line after the transcript: "Return only the JSON object, by the rules above. null for anything the caller did not say." | Fewer prose-wrapped answers on Sarvam | Low; about 25 tokens | golden set |
| C5 | `calevate_shared/extraction.py:562-651` | Per-agent field list comes before about 1.5k tokens of fixed rules | Stable content first (S12) | Move the fixed rules (WHO SPOKE ... TRANSCRIPT IS EVIDENCE) above the field list. Gain is limited on Azure because the per-agent schema is cached as a system prefix (S12). Sarvam caching is UNKNOWN (S25) | Small token cost saving | Low, but the harness must score the same prompt (it does: shared function) | golden set |
| C6 | `calevate_shared/extraction.py` (no example) | No worked example | Few-shot is recommended (S8). A canonical example rather than more rules (S19) | Try one 6-line example (caller denies, gives a relative time, gives a number in words) with its JSON. Keep it only if the golden set improves on `restraint` without raising `capture_wrong` | Quality | Medium: the example's values can leak into answers. Test for that | golden set |

## 6. Surface D: test generator, judge and improver

What we send:

- `GENERATE_INSTRUCTION` (`apps/workers/agent_test_ai.py:134`), at temperature 0.9.
- `JUDGE_INSTRUCTION` (`:254`), at 0.1, judging all conversations in one request, with the
  schema `key, verdict, reason, fix, step_id, formal_words` (`:288-295`).
- `IMPROVE_INSTRUCTION` (`:382`), at 0.3.
- Deterministic hard checks run first (`apps/api/agents/turn_checks.py`,
  `test_conversations.hard_check`).

### Practices

- Use pass/fail or pairwise, a clear rubric, and reasoning before the verdict (S21).
- Grade with a different model, ideally the most capable one available (S21, S22). Watch for
  self-enhancement and position bias (S23).
- Calibrate the judge against human labels before scaling it (S21).
- Generate synthetic cases with a strong model, covering typical, edge and adversarial cases,
  and have humans label them (S21). Run simulated-user regression tests (S3, S6).
- Evaluator-optimizer loops need clear criteria (S20). Change one thing at a time and re-run the
  cases that failed (S3, S5).

### Gap table

| # | Current | What we do | What leaders do | Recommended change | Effect | Risk | Touches |
|---|---|---|---|---|---|---|---|
| D1 | `agent_test_ai.py:288-295` | `verdict` is generated before `reason` (strict schema order = generation order, S13) | Reasoning before scoring (S21) | Reorder to `key, reason, formal_words, fix, step_id, verdict`. The parse is by key, so only the order changes | Judge accuracy | Low | judge tests (`agent_test_*_test.py`) |
| D2 | `agent_test_ai.py:260-263` | The judge rubric says the agent must say "the call is recorded" | The rubric must match the truth the agent was given (HR5 clause 2 depends on `call_is_recorded`, `engine.py:2356`) | Put `call_is_recorded` (from `engine_capabilities().records_audio`) in `AgentBrief` and state the matching expectation. It is true today on ThinnestAI, but it is a silent coupling | Correctness if an engine stops recording | Low | HR5 wording mirrored, not changed |
| D3 | `ask_json` leg selection (`apps/workers/script_assist.py:609`) | The judge runs on whichever dashboard leg answers. With the own-model switch on, the agent and the judge can both be Gemini Flash-Lite | Judge with a different and stronger model (S21, S22, S23 self-enhancement) | Prefer a judge leg whose model differs from the agent's in-call model. Record the judge model on `agent_test_runs` so a verdict can be traced | Less self-preference | Low-medium: cost if the stronger model is dearer | billing of the test loop (ai_quota) |
| D4 | none | No judge calibration exists (no agreement metric in `apps/api/agents` or `scripts`) | Calibrate against human labels before trusting the judge (S21); strong judges reach about 80% agreement (S23) | Founder labels about 50 stored test conversations pass/fail. A script computes judge agreement per verdict class. Re-run it when the judge prompt or model changes | Trust in the "Improve my agent" loop | Low | none |
| D5 | `agent_test_ai.py:356-379` | One request judges up to ten conversations | Position bias is a known judge bias (S23) | Keep batching for cost, but shuffle the conversation order per run and log position. If D4 shows position-dependent errors, judge one conversation per request | Measured, not assumed | Low | none |
| D6 | `agent_test_ai.py:382-405` | The improver writes the whole script, then a re-test runs | Evaluator-optimizer with clear criteria; re-run previously failing cases (S20, S3) | Already in place (source `retest`). Add the rule "one change per failing conversation" to cap drift, which matches "change one thing at a time" (S3, S5) | Fewer regressions from broad rewrites | Low | none |

## 7. Where sources disagree

- **Tool preambles.** OpenAI: say one short line before a tool call (S1). Deepgram: call without
  narrating, with filler injected by the server, because prompt-level narration is unreliable
  (S5). Vapi: use the tool's `request-start` message rather than the model (S4). Ours says
  never narrate after a tool. Whether ThinnestAI injects filler is UNKNOWN.
- **Capitals for emphasis.** OpenAI Realtime: capitalise key rules (S2). GPT-4.1, Anthropic and
  Google: avoid them or keep them sparing (S15, S17, S8). Cartesia: never use capitals for
  emphasis in text to be spoken (S24). Do not confuse this with prompt text.
- **Numbers.** Cartesia normalises conventional formats (S24). ElevenLabs' default asks the LLM
  to write words (S3). Vapi, Deepgram and LiveKit: write them out for the ear (S4, S5, S6).
- **Few-shot.** Google: always include it (S8). Vapi: at least three (S4). OpenAI: samples get
  copied, so vary them (S1, S15). Anthropic: a few canonical examples, not a laundry list (S19).
- **Fillers and disfluencies.** Vapi suggests 2-4 per turn (S4). Cartesia: sparing (S24). Ours:
  light per-language fillers, "never uhm" (founder decision). Vendors do not agree on a number.
- **Prompt size.** ElevenLabs: over 2,000 tokens costs latency (S3). Deepgram: a 25,000-char cap
  that is a ceiling, not a target (S5). ThinnestAI: a 20,000-char box (S26).
- **Copilot tool count vs caching.** Selection guidance wants a small active set (S10, S14).
  Caching wants a byte-identical tools array (S12). Our code chose caching. Only measurement
  settles which costs more on Flash-Lite.

## 8. UNKNOWN

- How ThinnestAI combines its own system rules with our instructions, and where caching breaks.
  `cachedInputTokens` is reported per call but is not yet read on Prana or GPT-OSS calls.
- Whether ThinnestAI shows silence to the model, and whether it speaks filler during tool calls.
- Whether Gemini 2.5 Flash-Lite has implicit caching: the page says "all Gemini 2.5 and newer"
  but names no minimum for Flash-Lite (S9).
- Prompt-caching behaviour on Sarvam `sarvam-105b` (S25 does not document it).
- Whether Sarvam's `json_schema` works on our key and with `reasoning_effort` together (S25
  documents both separately). Run one golden pass before relying on it.
- Telugu-English code-switch handling in Cartesia (S24 says nothing). This remains confirmed
  by ear only (founder, 11 Oct).
- Tool-selection accuracy of the copilot on Flash-Lite with the current array: not measured.
- The OpenAI Realtime cookbook body beyond 200k chars (the page is mostly embedded audio).

## 9. Integration plan (independent work packages)

Each package can ship alone. Evaluate before and after on the same inputs. No real phone
calls are needed.

**WP-A: in-call prompt (A1, A2, A5, A7, A11; A4 after founder review; A3 and A10 after
measurement)**

- Files: `packages/shared/src/calevate_shared/engine.py` (`VOICE_STYLE_GUIDANCE`,
  `_when_you_cannot_help_section`, `PLATFORM_RULES_PREAMBLE`, `_register_section`);
  `packages/shared/src/calevate_shared/spoken_style.json` (A4 only); `docs/PROMPT-GUIDE.md` §2.
- Tests to update: `tests/agent_intelligence_test.py` (the "Dr Ravi" PIN, register format),
  `tests/agent_prompt_budget_test.py` (sizes), the publish verifier and drift tests only if a
  marker moves (it must not).
- Evaluate: run the standard and specimen scenarios through Test Chat on two agents (the Raghava
  Telugu starter and one Hindi or English agent), three runs each, before and after. Compare:
  - the counts of `turn_checks` kinds (`repeated_question`, `too_long`, `formal_words`,
    `several_questions`);
  - the judge's pass rate;
  - the composed size in chars and estimated tokens.
- A deploy re-queues a platform live apply (D-739), so the change reaches every agent at once.
  Land it only on a green before/after.

**WP-B: copilot (B1 measurement first, then B2, B3, B4)**

- Files: `apps/api/copilot/prompt.py`, `apps/api/copilot/admin_prompt.py`, and possibly
  `tools.py`/`console_reads.py` (consolidation).
- Tests: `apps/api/copilot/prompt_test.py`, `admin_prompt_test.py`, `adversarial_test.py`,
  `tools_test.py` (byte-identity per realm).
- Evaluate: a fixed set of about 40 questions. For each, record the expected tool (or none),
  whether it should refuse, and whether it should fill. Score tool-choice accuracy, wrong
  fills, wrong refusals and turns used, on the fast and planning tiers, before and after.

**WP-C: extraction (C1, C2, C3, C4; then C5, C6)**

- Files: `apps/workers/extraction.py` (Sarvam leg response_format and reasoning_effort),
  `packages/shared/src/calevate_shared/extraction.py` (language, closing line, order, example),
  and the pipeline call site that knows the agent's language.
- Tests: the extraction unit tests and the golden-transcript harness (`scripts/eval.py`,
  `scripts/golden_transcripts.json`, `make eval`).
- Evaluate: `make eval` on both legs before and after. Watch `restraint` and `capture_wrong`
  (unwaivable), field accuracy, parse failures, and usage tokens (completion plus reasoning).
  Add Hindi and English golden cases for C3.

**WP-D: generator and judge (D1, D2, D3, D5; D4 needs founder labels)**

- Files: `apps/workers/agent_test_ai.py`, `AgentBrief` (where `brief_text` reads it),
  `apps/workers/script_assist.py` (`ask_json` leg preference), and the `agent_test_runs` model
  if the judge model is recorded (that needs a migration).
- Tests: the agent-test loop tests (`tests/agent_test_loop_fixes_test.py` and siblings).
- Evaluate: re-judge a frozen set of stored conversations with the old and new judge. Report
  verdict flips and, once D4 exists, agreement with the founder's labels.

Order, by value per hour:

1. C1 + C2 + C3 + C4 (cheap, measurable by an existing harness)
2. D1 + D2
3. A1 + A2 + A7 + A11
4. B1 measurement
5. B2 + B3
6. D3 + D4
7. A5
8. A4 (founder review)
9. A3 and A10 (vendor answers first)
