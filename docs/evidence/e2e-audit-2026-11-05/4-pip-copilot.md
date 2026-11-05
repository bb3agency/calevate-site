# Lane 4: Pip, the dashboard copilot. Phase-1 audit, 5 Nov 2026

Scope: `apps/api/copilot/**`, `apps/web/src/components/copilot/**`, `apps/web/src/lib/copilot/**`,
and the Script tab's Pip surface (`apps/web/src/app/c/[slug]/agents/[agentId]/script/scriptSurface.ts`).
Baseline: branch `claude/calevate-legal-ops-docs-rd2c4t` at `6c0e887a9`. It includes today's fix
`364dd9a0a`: a repair keeps the run's first quote, the screen state carries `<spoken_style>`, and
text is held until a fill is accepted.

## What I could and could not exercise

- **Drove:** sign-in as the seeded owner, then the Pip panel on `/c/sunrise-homes` at 1440 and 375.
  Screenshots and logs are in `scratchpad/audit/4-pip-copilot/`: `open-open-1440.png`,
  `m-open-375.png`, `open-log.txt`, `m-log.txt`.
  - The seeded account has **Pip consent `required`**: `GET /v1/copilot/conversation` returned
    `consent.status: "required"`.
  - No horizontal overflow at either width.
- **Did not drive any ask, fill, action, proposal or routine.**
  - Turning Pip on means the owner accepts a data-sharing disclosure, and I do not accept terms
    on anyone's behalf.
  - Model legs need credentials that are not confirmed locally (`chat_leg` returns None without
    a key). Turning consent on would probably still end in "assistant unavailable".
  - So every loop finding below comes from reading the code (file:line). None of them was
    observed on a live run.
- **Not checked:**
  - the admin realm's Pip in a browser (lane 7 holds that login);
  - the `transcript.read_raw` audit on every Pip raw read (hard rule 5);
  - fair-use counter arithmetic;
  - PDF and attachment turns.

## 1. Map

| Area | Where | What it is for |
|---|---|---|
| Ask stream (client) | `routes.py` `POST /v1/copilot/ask` (SSE); `service.run_copilot`, `_answer_stream`, `_run_tool_loop` (service.py:1969-2803) | One question becomes a tool loop of up to 6 turns (`MAX_TURNS`, service.py:140) and at most 3 actions (service.py:416). It emits text, fill, proposal, action, navigate, job, chart, step and spend events. |
| Ask stream (admin) | `admin_routes.py`, `admin_prompt.py`, `admin_tools.py`, `admin_actions.py`, `admin_screens.py`, `admin_memory.py` | The operator realm. Admin actions are always confirm-tier, and spend goes to the platform ledger. |
| System prompt | `prompt.py` `ASSISTANT_IDENTITY`, `CONVERSATIONAL_FRAMING`, `SYSTEM_PROMPT` (:315-485), `CLOSING_RULES` (:491-519) | Identity, the five jobs, fill and action rules, reply language. |
| Screen state | `prompt.render_screen` / `_render_field` / `render_spoken_styles` (prompt.py:700-800) | XML fields carrying `writable`, `redacted`, `spoken_language` and `instruction`; facts; `<spoken_style>` word list. |
| Screen guides, help, runbooks | `screen_guides.py`, `help.py`, `runbooks.py` | Per-route guide text and how-to lookups. |
| Area tools | `areas.py` (`<area>_find` / `<area>_do`) | 13 areas wrap about 120 registry tools (D-893). A misnamed call is refused with its schema. |
| Read tools | `tools.py READ_TOOLS`, `console_reads.py`, `agent_reads.py`, `knowledge_reads.py`, `diagnostics.py`, `charts.py` | Account lookups, troubleshooting, and the chart cards. |
| Fill | `set_fields` (`prompt.set_fields_tool`), `service.validate_fill` (:894-1003), `quotes.quoted_in`, `spoken_guard.textbook_words` | All-or-nothing writes into the on-screen form. Checks: `because` grounding, writability, select options, the textbook-word guard on spoken lines, plain English in instruction fields. |
| Immediate actions | `write_tools.run_immediate`; tools in `agent_actions`, `console_actions`, `lead_actions`, `campaign_actions`, `pin_actions`, `account_actions` and others | Reversible, with Undo (`undo.py`, `action_log.py`). Run at once; the receipt is `ActionReceipt.tsx`. |
| Confirm actions (proposals) | `write_tools.plan_write`, `POST /v1/copilot/confirm`, `ProposalCard.tsx` | A signed plan that runs on Confirm. In a job it is staged to `/copilot/approvals`. |
| Script actions | `script_actions.py` `agent_script_suggest` (confirm; queues `script_proposals.request_proposal`), `agent_tests_fix` | Pip's script rewrite and its fixes for failed tests. The result lands on the Script and Training tabs. |
| Bulk plans | `plans.py`, `plan_routes.py`, `PlanCard.tsx` | Lens-based bulk changes. |
| Background jobs | `jobs.py`, `apps/workers/copilot_jobs.py`, `JobCard.tsx`, `JobProgress.tsx` | Long tasks. Every write is staged for approval (D-729). |
| Routines | `routines.py`, `routine_routes.py`, `routine_actions.py` | Scheduled jobs (IST). |
| Memories | `memory.py` (`redacted_content`), `admin_memory.py` | Distilled, redacted memories. |
| Conversation | `transcript.py`, `GET /v1/copilot/conversation` | Client turns stored unmasked (D-788); operator turns stored redacted. |
| Notes | `notes.py`, `note_routes.py`, `PipNotes.tsx` | Hourly detector lines at the top of the panel. |
| Pins | `pins.py`, `pin_routes.py`, `PinnedCards.tsx` | Charts kept on the home screen. They re-run under the viewer's own role. |
| Consent | `consent.py`, `PipConsent.tsx`; enforced in routes.py:357, attachment_routes.py:243, copilot_jobs.py:85 | D-788: Pip is off until the owner accepts. Withdrawal is D-839. |
| Redaction | `masked_messages` (service.py:1176), `memory.redacted_content`, `action_log.redact_args`, `lib/copilot/redaction.ts` | The standby leg is always masked. Memories, job text and action args are redacted. |
| Metering | `CopilotSpend`, `PaidTurns`, `crm/assist.meter_assist`, `fair_use.py` | Every paid turn is metered. `unused` is set only for legs that died. |
| Identity and provider guard | `identity.py` | Pip never names a model vendor. |
| Panel UI | `CopilotPanel.tsx`, `CopilotDock.tsx`, `AskAssistant.tsx`, `StepList.tsx`, `answerText.tsx`, `DiagnosisCard.tsx`, `ChartCard.tsx`, `AnswerRating.tsx`, `ViewAsPanel.tsx` | Streaming answer, step list, cards, rating. |
| Saving copy | `lib/copilot/keeping.ts` | "Nothing is saved until…" and "saved as a draft" lines, chosen by the screen's `saves` value. |
| Suggestions | `lib/copilot/suggestions.ts` | Three neutral questions per screen; the business's own question comes last. |

## 2. Findings

Severities: P0 breaks money, law, data or a core flow; P1 is wrong but has a workaround; P2 is
confusing; P3 is polish. Rule numbers are the brief's founder rules (R1-R7) and CLAUDE.md's hard
rules (HR).

| ID | Sev | Where | What happens (from the code) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| PIP-01 | **P1** | service.py:2156-2165 | Text is held only on turns that call `set_fields`. On any turn with an action or a proposal, the model's "I've updated the script / put it live" streams to the screen **before** the server runs or plans the call. If the action is then refused (`WriteRefusedError` or `ProblemError`, :2534-2575 and :2624-2665), the claim stays on screen. The same 5 Nov "applied when nothing applied" defect is still open for every action tool. | Hold text on every turn that carries a write or proposal call. Show it only once the call succeeds; drop it on refusal, as fills now do. | service.py:2091 (`hold_text` is computed from fields only), :2158-2165 | R6, HR11 spirit |
| PIP-02 | **P1** | prompt.py:513-514 (`CLOSING_RULES`) | The prompt says "with every fill or suggestion, say in one or two sentences what you did". That asks the model to write the claim in the same turn as the call, before the outcome is known. It is the cause behind PIP-01. | Ask for the sentence **after** the tool result. The loop already feeds back "DONE. … Tell them…" (service.py:2681-2690). Fills can use `filledReply` or the server's `silent_answer_line`. | prompt.py:513 | R6 |
| PIP-03 | **P1** | routes.py:812-865, service.py:2537, :2649 | When every write is refused, the answer ends with `unchanged_line(refused_writes[-1])`. For action tools that string is the model-facing `WriteRefusedError.reason`, which carries backticks, field keys and instructions to the model. Example (script_actions.py:164-167): "Nothing was changed. This agent's script is already in steps, so use mode `change` for one change or `whole` to draft it again." It is also the step `detail` the owner sees in `StepList.tsx:105`. About 55 single-line `WriteRefusedError` strings with backticks exist in `apps/api/copilot/*.py`. | Give `WriteRefusedError` a `plain` owner message, as `FillRefusedError.plain` has. Use it for the step detail, `unchanged_line` and the out-of-turns detail. Keep `reason` for the model only. | grep count above; script_actions.py:164-189, :328-331; console_actions.py:1640 | R4, R6 |
| PIP-04 | **P1** | service.py:2785-2790 (`EXHAUSTED_MESSAGE` detail) | Out of turns, the message appends `refusal_reasons`. For a misnamed area call that is the `AreaCallError` reason, which "ends with the schema" (areas.py:486-488). For an action it is the model-facing reason. Raw schema text can reach the owner's answer. | Same fix as PIP-03. Never put an area refusal into `refusal_reasons`; use `AREA_RETRY_DETAIL`. | service.py:2167-2179 sets `refusal_reasons = (reason,)` | R4 |
| PIP-05 | **P1** | service.py:2243-2264, prompt.py:466-475 | **A claim with no tool call is unchecked.** A prose-only turn ("I've changed the opening line") ends the run, and nothing compares the claim with what the run did. The only guards are prompt lines. `unchanged_line` fires only when a write was attempted and refused. | Deterministic backstop: if the run made no fill, action or proposal and the final text uses a change verb in the first person past tense, append "Nothing was changed." This applies the same idea as `asks_for_a_change` (service.py:600) to the answer. Or have the model classify its own answer in a cheap closing structured field. Use as a backstop only. | no claim detector (grep `I have updated` finds only comments) | R6 |
| PIP-06 | **P1** | prompt.py SYSTEM_PROMPT and render_screen; scriptSurface.ts:136-180 | **"Refused its own Telugu."** The screen marks instruction fields `instruction="true"`. `validate_fill` refuses Pip's Indic text in them (service.py:871-885, D-831). But **no prompt line says what `instruction="true"` means**, and only two field helps ("The agent's role", plain stages) say "plain English". So "rewrite my script in Telugu" makes Pip write Telugu into business_line, goal, outbound_purpose, objection answers and ending. That is refused, the run burns its 6 turns, and since fills are all-or-nothing nothing lands. The new `<spoken_style>` covers textbook words only, not the English-instruction rule. | Say it in the screen block, as `render_spoken_styles` does when an `instruction` field is writable: "Fields marked instruction="true" are instructions to the agent: write them in plain English; only spoken_language fields are in the call language." Add matching help to every instruction field. | prompt.py:720-728 (attribute rendered, never explained); grep finds no "instruction=" in the prompt text | R6, "blocked by a check it could satisfy" |
| PIP-07 | **P1** | console_actions.py:1633-1642 (`_opening_line_problem`) | `agent_edit` / `agent_edit_live` exempt a textbook word only if the **current live** opening already had it (`allowed=current[field]`). Words the owner typed in the request are not exempt. `validate_fill` exempts question words (service.py:835), so the two Pip paths disagree. Dictate an opening containing a listed word and Pip refuses the owner's own Telugu. The blank refusal also says "the `opening_line` was blank". | Pass `said` (the person's messages) into `allowed`, as `validate_fill` does. Use one helper for both paths. | console_actions.py:1640-1642; service.py:822-836 | R6, R4 |
| PIP-08 | **P1** | write_tools.py:1067-1083; only `script_actions.py:294` sets `grounded=` | D-833 grounding (does the latest message ask for this?) applies to `set_fields` and to **one** action, `agent_script_suggest`. About 15 immediate actions run on the model's say-so with no grounding check (e.g. `agent_edit`, `lead_assign`, `campaign_edit`, `campaign_create`, `call_follow_up_set`, `agent_capture_fields_set`, `knowledge_rename`). Tool results include caller-authored transcript text, so this is an indirect prompt-injection path to writes. The receipt and Undo limit the damage but do not prevent it. | A `because` quote on every immediate action, checked with `quoted_in` against `person_said`, as for fills. Outside a quote, the action becomes a proposal (confirm). | grep `grounded=` in `apps/api/copilot` | R6; OWASP LLM01/LLM06 (research §3) |
| PIP-09 | P2 | service.py:2386-2392 (`fill_grounded` run-wide) | Once one fill of a run quoted the request, **every later fill in that run** skips the `because` check. It is not limited to the same fields or a repair of the same values. A refused-then-repaired turn can add fields nobody asked about. | Scope the waiver to a repair: the same `field_id` set, or a subset of the refused call's fields. | service.py:2083-2084, :2390 | R6 (Pip writes what the owner did not ask) |
| PIP-10 | P2 | service.py:822-836, :839 | Textbook words are exempt only if they appear in `field.value` or the latest question. If the owner dictated the line one turn earlier and then says "yes, put it in", the owner's own word is refused. | Use `person_said(payload)` (all user turns), as grounding does. | service.py:835 | R6 |
| PIP-11 | P2 | `spoken_guard._uses_word` (spoken_guard.py:52-57) | The match checks only that a word **starts** there, not where it ends, so a short listed word prefix-matches longer words. Examples: Telugu `ధర` (price) also matches `ధరించు`; Hindi `तथा` matches `तथापि`. Inflections are probably meant to match, so prefix matching may be partly deliberate. The en-IN "Kindly" match is case-sensitive, so lowercase "kindly" passes. | Decide which by checking a word list from the founder. Add a test for a false positive in each language. Make en-IN case-insensitive. | spoken_style.json te-IN shortest entries: ధర, ఋణం, వలన, కలదు | R6 |
| PIP-12 | P2 | `ProposalCard.tsx:368` + script_actions.py:228-232 | A queued script suggestion (`applied=True`) shows the heading **"Done"**, with "Writing it now. In about half a minute it is on …'s Script tab". If the writer job later fails (`script_proposals.store_failed`, stale after `DRAFTING_STALE_AFTER`), Pip's card still says Done and the conversation says nothing. | A queued outcome gets its own heading ("Started" / "Writing"). The card or a Pip note follows the proposal's status and says so if it failed. | script_proposals.py:90,141,461 | R6 |
| PIP-13 | P2 | keeping.ts:29-34, :52-55 | On an `autosave` screen, Pip says "It is saved as a draft" the moment the fill lands, before the screen's debounced autosave has run. A failed autosave (conflict, validation, network) contradicts it. | Word it as an intention ("will save as a draft"), or have the autosave's real state drive the line. | keeping.ts:31 | R6 |
| PIP-14 | P2 | routes.py:849-857 (`silent_answer_line`) | The stored and shown answer "I changed A, B and C" comes from the field ids the server accepted. The browser may apply fewer: `paths.setByPath` refuses rows that do not exist (paths.ts:19-24). The panel's own `filledReply` uses what was applied, so panel and transcript disagree after a reload. | Build the server's line from the applied set (the browser can report it back), or have the transcript store the panel's line. | paths.ts:19-24; routes.py:851 | R6 |
| PIP-15 | P2 | console_actions.py:1614-1616 | The `agent_edit` proposal shows "voice <voice_id>". That is the raw `agents.voice_id`, a catalogue or vendor id, on a client card. | Show the voice's display name from the catalogue. | console_actions.py:1592, :1615 | R4, R3 risk |
| PIP-16 | P2 | routes.py:555-575 / `CopilotSpend.unused` | A run whose every fill or write was refused **by our own guard** (textbook words, instruction language, grounding), or that ran out of turns, is charged to the client's AI allowance and fair-use count like a good answer. The 5 Nov Varsha rewrite cost the owner turns for Pip's own mistakes. | Mark these runs `unused=True`: still on our cost ledger (HR7), off the client's allowance. | service.py:2398-2414 (refusal path ends with a normal spend) | R6 / fairness |
| PIP-17 | P2 | agent_setup_actions.py:1026-1033 (`_SCREEN_WORDS`) | A hand-written Telugu and Hindi word list (యాప్, ఇన్‌స్టాల్, డౌన్‌లోడ్, …; ऐप, इंस्टॉल, …) lives in code. | Move it to a founder-owned data file (next to `spoken_style.json`) or let the model judge. | file:line above | R2 |
| PIP-18 | P3 | identity.py:163-168 | A hand-written Indic list of provider names (గూగుల్, जेमिनी, …) used by the egress guard. It guards provider names; it is not spoken text, so it is a lesser case. | Move it to a data file with an evidence note, or accept it as a guard list and record that decision. | file:line | R2 (borderline) |
| PIP-19 | P3 | StepList.tsx:54, :99 (`title={step.tool}`) | Hovering a step shows the internal tool name (`agents_do`, `agent_script_suggest`). This is deliberate, for support. | Keep it for the admin realm. On the client realm use the label, or put the name under a "Details" toggle. | file:line | R4 |
| PIP-20 | P3 | PipConsent panel (`m-open-375.png`, `open-open-1440.png`) | The consent gate is two dense paragraphs (~90 words) before the checkbox. That passes as legal text, but the panel never says what Pip *is* or what it does before asking. | One line on what Pip does, a "What is shared?" tap for the disclosure, then the checkbox. Get legal sign-off on the wording. | screenshots | R4 |
| PIP-21 | P3 | service.py:629-636 `UNQUOTED_FILL_REASON` | Model-facing text with backticks. Today it reaches only the model, and `plain` covers the owner. It is noted so that a future caller does not show `reasons`. | n/a | file:line | R4 |

**Counts:** P0 0 · P1 8 · P2 9 · P3 4 · total 21.

No P0 was proven: every write path I read is still mediated by the server (registry tier, planner,
confirm token). The P1s are false claims and owner-facing jargon, plus one injection-shaped gap
(PIP-08). The founder will see these.

Checked and clean:
- the client prompt and the suggestions contain no business-specific examples (grep for
  clinic, real estate, crop and similar found nothing in prompt text);
- no provider names appear on client copy in this area;
- consent is enforced on ask, upload, job and routine;
- the standby leg is always masked.

## 3. Research notes (primary sources, read 5 Nov 2026)

- **OWASP GenAI Top 10 2025, LLM06 Excessive Agency**
  (https://genai.owasp.org/llmrisk/llm062025-excessive-agency/). Its mitigations include
  minimising extension functionality and permissions, executing in the user's context, and
  "complete mediation" (authorise in the downstream system, not the LLM). Its human-in-the-loop
  rule is "require a human to approve high-impact actions before they are taken".
  - Pip already meets: user context (RLS, `actor`) and mediation (registry tier, the button's
    own service function).
  - It changes PIP-08: an immediate action whose request did not come from the person is the
    excessive-agency shape. A grounding check (or a fall back to confirm) is the narrow fix.
- **OpenAI Agents SDK, Guardrails** (https://openai.github.io/openai-agents-python/guardrails/).
  It separates *tool input guardrails* (run before a tool call; can skip or replace it) from
  *output guardrails* (run on the final answer). Pip has strong tool-input guards
  (`validate_fill`, planners). It has **no output guardrail on the final text**, which is the gap
  behind PIP-01, PIP-02 and PIP-05.
- **Anthropic, Building effective agents**
  (https://www.anthropic.com/engineering/building-effective-agents). Agents should get "ground
  truth from the environment at each step" (tool results) and pause at checkpoints for human
  feedback. In tool design: "design toolsets and their documentation clearly and thoughtfully."
  This bears on PIP-06: an attribute the model must obey (`instruction="true"`) has to be
  documented where the model reads it. And the claim should follow the tool result (PIP-02).
- **Microsoft Foundry Agent Service, Transparency Note**
  (https://learn.microsoft.com/en-us/azure/ai-foundry/responsible-ai/agents/transparency-note,
  updated 2026-06-05). It recommends giving users information "before, during, and after actions
  are taken" and real-time controls to authorise, review and override actions. This bears on
  PIP-12: a queued job must report its real end state, not a "Done" frozen at queue time.

## 4. Proposed fixes, grouped by file ownership for phase 2

- **G1. Claim truthfulness in the loop.** Covers PIP-01, 02, 04, 05, 09, 16. Files:
  `apps/api/copilot/service.py`, `apps/api/copilot/prompt.py` (`CLOSING_RULES`),
  `apps/api/copilot/routes.py`, plus tests in `loop_test.py`, `route_test.py`, `prompt_test.py`.
  1. Generalise `hold_text` to any turn with a write or proposal call.
  2. Drop "say what you did" from the call turn.
  3. Scope `fill_grounded` to a repair of the same fields.
  4. Add a final-answer backstop for a change claimed with no change made.
  5. Mark guard-refused or exhausted runs `unused`.
- **G2. Owner-language refusals.** Covers PIP-03, 04, 21. Files: `apps/api/copilot/actions.py`
  (`WriteRefusedError` gains `plain`), every `*_actions.py` raise site (about 200 sites; can be
  mechanical, defaulting `plain` to a generic "This could not be done here: <label>"), plus
  `service.py` and `routes.py` to use `plain` for step detail and `unchanged_line`. Coordinate
  with G1 on `service.py`, or run G2 after G1.
- **G3. Script language rules.** Covers PIP-06, 07, 10, 11. Files: `apps/api/copilot/prompt.py`
  (render an instruction-field rule next to `render_spoken_styles`),
  `apps/web/src/app/c/[slug]/agents/[agentId]/script/scriptSurface.ts` (help text on every
  instruction field), `apps/api/copilot/console_actions.py` (`_opening_line_problem` gets
  `said`), `apps/api/copilot/service.py` (`_pips_textbook_words` reads `person_said`; shared with
  G1, so sequence them), and `packages/shared/src/calevate_shared/spoken_guard.py` (word-end rule
  decision, en-IN case). Shared with the script and agents lane (2).
- **G4. Grounding for immediate actions.** Covers PIP-08. Files:
  `apps/api/copilot/write_tools.py` (default grounding on immediate tools, or demote to confirm),
  `apps/api/copilot/areas.py` (`because` in `<area>_do` args), `prompt.py`, `actions_test.py`,
  `tests/copilot_tool_eval_test.py`.
- **G5. Truthful UI for queued and saved work.** Covers PIP-12, 13, 14. Files:
  `apps/web/src/components/copilot/ProposalCard.tsx`, `apps/web/src/lib/copilot/keeping.ts`,
  `apps/web/src/components/copilot/CopilotPanel.tsx`, `apps/api/copilot/routes.py`
  (`silent_answer_line` from the applied set), and possibly a Pip note for a failed suggestion in
  `apps/api/copilot/notes.py`.
- **G6. Ids, data files and copy.** Covers PIP-15, 17, 18, 19, 20. Files:
  `apps/api/copilot/console_actions.py` (voice display name),
  `apps/api/copilot/agent_setup_actions.py` and `identity.py` (word lists to data files),
  `StepList.tsx`, `PipConsent.tsx` / `consent.py` (copy; legal sign-off needed for disclosure
  text).

Verify each group by re-running the 5 Nov Varsha scenario on a consented local account with a
model key: Telugu rewrite of a stepped script, a dictated opening containing a listed word, and a
refused action whose turn claimed success.
