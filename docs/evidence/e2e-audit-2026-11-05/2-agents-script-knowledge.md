# Lane 2: agents, script, knowledge (phase 1 audit, 5 Nov 2026)

Scope: everything on an agent (list, Overview, Script tab, Put it live, History, Undo,
proposals, opening notices, call handling, voice, lead details and suggestions, alerts,
Training and tests, readiness) and Knowledge (Teach box, uploads, call instructions,
questions to answer). Phase 1: no code changed. Only this file was written.

How it was checked:

- Code read at HEAD `6c0e887a9` plus the uncommitted `apps/api/agents/agent_pass.py` change.
- Real app driven headless (playwright-core, Chromium) as the seeded `sunrise-homes` owner
  at 1440px and 375px. Screenshots and page text are in
  `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/2-agents-script-knowledge/`
  (`*.png`, `text/*.txt`, `summary-*.json`; scripts `walk.mjs`, `api.mjs`).
- Read-only API calls through the signed-in page: `GET .../script`, `.../readiness`,
  `.../script/proposal`, `.../script/versions`, and `POST .../script/check` (stores nothing).
- No Python was run and no AI writer was triggered. "Fix them first" was NOT pressed: it
  spends AI allowance and rewrites the seeded draft. The P0s below are traced through code,
  with each line cited.

Things I could not check (honest gaps):

- **The running API is older than the code.** `GET /v1/agents/{id}/caller-help` returns 404
  on localhost:8000, and `/openapi.json` lists no `caller-help` path, but the route is in
  `apps/api/agents/call_handling_routes.py:726`. So I could not see the caller-help
  suggestion (Overview, Settings) or the D-971 weave live.
- The seeded agent's script is hand-written and has no proposals, practice runs, lead
  suggestions or knowledge. Those screens were only seen empty.
- Walking every tab tripped the API's rate limiter: 429s on `/v1/me` and others on the
  "What it notes" tab at 1440 (`summary-*.json`). That is environment noise, not a finding.
- No overflow at 375 or 1440 on any page I walked (`scrollWidth == clientWidth` on all of
  them).

---

## 1. Map

### Screens and routes (web)

| What | File | Purpose |
|---|---|---|
| Agent list | `apps/web/src/app/c/[slug]/agents/page.tsx`, `Roster.tsx`, `AgentReadiness.tsx` | Cards with status, calls and readiness gauge; "New agent", "Let Pip do this" |
| New agent / first agent | `agents/new/*`, `agents/first/*` (`OpeningLine.tsx`, `BriefStep.tsx`, `BuildStep.tsx`) | Creation wizard; brief, script, voice, opening line |
| Agent page shell | `agents/[agentId]/AgentWorkspace.tsx`, `sections/agentHeader.tsx` | Tabs: Overview, Script, Training, Actions, What it notes (`captured`), Voice, Settings; header Put it live and the ⋯ menu ("Undo waiting changes", "Delete…") |
| Overview | `sections/overview.tsx`, `AgentReadiness.tsx`, `panels/openingNotices.tsx`, `panels/openingLineFix.tsx` | Readiness and fixes, first-call checklist, the two notice switches, latest calls |
| Script tab | `script/ScriptBuilder.tsx`, `ScriptSections.tsx`, `SectionEditor.tsx`, `SectionList.tsx`, `SmallSteps.tsx`, `FlowCanvas.tsx`, `HandWritten.tsx`, `TaughtRules.tsx`, `ScriptToolbar.tsx` | Builder sections: business line, role, goal, opening(s), stages and steps, objections, policies, ending, example; hand-written mode |
| Put it live | `script/PutLive.tsx` (`PutLiveDialog`, `ScriptWarnings`, `FixWatcher`, `usePutLive`) | Publish or apply, lint warnings, "Fix them first", promo warning |
| History / restore | `script/ScriptHistory.tsx` | Versions; restore into the draft |
| Undo (in the builder) | `ScriptBuilder.tsx:237,620` (`undoTo`) | Undo after keeping a suggestion |
| Proposals review | `script/ProposalReview.tsx`, `ProposalEditors.tsx`, `PipProposal.tsx`, `PipAsk.tsx`, `ImprovementReview.tsx`, `scriptDiff.ts` | Review a Pip proposal or a test improvement row by row |
| Call handling | `panels/callHandling.tsx`, `panels/callerScreen.tsx`, `panels/callerContinuity.tsx` | Call length, silence, give callers time, screen guide, caller memory |
| Voice | `panels/voiceTuning.tsx`, `sections/deliverySections.tsx` | Voice choice and tuning |
| Lead details | `panels/extraction.tsx`, `extractionRow.tsx`, `extractionDraft.ts` | Extraction schema editor and suggested changes |
| Alerts / handover | `panels/teamAlerts.tsx`, `panels/handover.tsx` | Alerts after a call, transfer list |
| Training / tests | `sections/training.tsx`, `sections/tryIt.tsx`, `test/*` | Questions to answer, mistakes on real calls, chat and call tries, practice callers, saved tests |
| Knowledge | `apps/web/src/app/c/[slug]/knowledge/*` (`TeachBox.tsx`, `AddDocument.tsx`, `UploadList.tsx`, `CallInstructions.tsx`, `WhatItKnows.tsx`, `ProfileKnowledge.tsx`, `NotesList.tsx`) | Teach box, uploads, structured text, call instructions ("Use in call scripts"), what it knows |

### API (apps/api)

| Route / module | File | Purpose |
|---|---|---|
| `GET/PUT .../script`, `PUT .../script/draft`, `POST .../script/check`, `/preview` | `agents/script_routes.py:319-448,1471` | Read, autosave (CAS on `base_saved_at`), lint check |
| `POST .../script/fix-lines` | `script_routes.py:1526-1590` | "Fix them first": saves the draft, queues a `change` proposal |
| `GET .../script/proposal`, `DELETE .../proposal/{id}` | `script_routes.py:1380,1439` | Pending proposal; discard |
| `POST .../proposal/starter`, `/opening-line/after-introduction`, `/opening-line/in-language` | `script_routes.py:1409,1490,1673` | Queue writer proposals |
| `PUT .../opening-line` | `script_routes.py:1722`, `script_builder.replace_opening_line:758` | Replace the opening and put it live |
| `POST .../publish`, `/apply`, `/undo`, `/versions`, `/versions/{v}/restore` | `script_routes.py:1593-1858`, `publishing.py` | Put it live, apply staged, undo staged, history, restore |
| `.../tests/*` | `script_routes.py:1157-1380`, `script_edits.py`, `test_conversations.py` | Practice runs, suggested edits |
| Proposals store | `agents/script_proposals.py` | One proposal per agent (`agents.script_proposal` jsonb) |
| Lint | `agents/script_lint.py` | D-945 checks |
| Opening notices | `agents/opening_notices.py`, `packages/shared/.../opening_notices.py`, `engine.join_first_words:4533` | D-971 weave queue and the keyword matcher |
| Readiness | `agents/readiness.py`, `readiness_routes.py` | Score and fixes |
| Lead details | `agents/lead_fields*.py`, `field_suggestions.py`, `field_suggestion_routes.py`, `extraction_routes.py` | Schema and suggestions |
| Caller help / give time | `agents/caller_help.py`, `patient_caller.py`, `call_handling*.py` | Per-agent judgement and preset |
| Agent passes | `agents/agent_pass.py` | Queue for the field-suggestion and caller-help passes |
| Knowledge | `apps/api/kb/routes.py`, `kb/uploads.py:842 use_call_instructions`, `apps/api/teach/*` | Uploads, call instructions, questions to answer, facts |
| Engine adapter (read only) | `apps/api/engine/thinnest.py`, `hosted_platform.py` | Publish and live-apply |

### Workers and prompts

| Job | File | Prompt |
|---|---|---|
| `script_proposal` (change, whole, steps, knowledge, opening, written, starter) | `apps/workers/script_proposal.py` | `script_assist._SYSTEM_INSTRUCTION`, `EDIT_INSTRUCTION`, `CONVERT_INSTRUCTION`, `KNOWLEDGE_CHANGE` |
| `suggest_scripts_from_document` | `script_proposal.py:454` | knowledge proposal for every agent on each new upload |
| Opening writer | `apps/workers/opening_line.py` | `OPENING_WRITER_INSTRUCTION` |
| `weave_opening_notices` (D-971) | `apps/workers/opening_notices.py` | opening writer with the notice rules; **puts the line live** |
| Field suggestions | `apps/workers/field_suggestions.py` | `SYSTEM_PROMPT` |
| Caller help | `apps/workers/caller_help.py` | screen guide / give time judgement |
| Teach question drafts | `apps/workers/teach_questions.py` | grounded draft with a numbered source |
| KB teach | `apps/workers/kb_teach.py` | sorts teach-box text into facts |

---

## 2. Findings

Counts: **P0 3 · P1 9 · P2 14 · P3 3** (29).

### P0

| ID | Sev | Where | What happens (observed / traced) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| A-01 | P0 | `script_routes.py:1539-1590`; `workers/script_assist.py:1349-1356,431`; `PutLive.tsx:109-114`; `lib/api/script.ts:607-619` | **"Fix it first" on a HAND-WRITTEN script wipes the whole script from the draft.** The lint runs on hand-written text (`script_lint.py:398-399`), so the button appears. `fix-lines` then queues a `change` proposal with no hand-written guard. Pip's own action refuses this case (`copilot/script_actions.py:167-171`) and so does the knowledge proposal (`script_proposals.py:384-387`). The edit prompt sends the current script with `exclude={'raw_override'}`, so the model never sees the owner's text. `edited_script` returns `raw_override=None`. `useKeepFixedScript` then PUTs that script as the draft with no review. The owner's whole prompt is replaced by whatever the model wrote from an empty skeleton, and the next "Put it live" sends it to callers. | Refuse fix-lines on a hand-written script (offer "turn into steps" first), or fix the text inside `raw_override`. Never write a proposal to the draft unreviewed. | Live check: `POST /v1/agents/01a1aad8…/script/check` with `{"raw_override": "...by SMS..."}` → `200 {"warnings":["The script: has the agent promise an SMS, and this platform sends no SMS."]}`, so the button shows. Rest traced in code (not pressed). | Founder rule 6; hard rule 12 (inspect before mutate); "nothing silently drops owner content" |
| A-02 | P0 | `PutLive.tsx:109-114`; `lib/api/script.ts:607-625`; `workers/script_proposal.py:257-268`; `script_assist.py:375-431`; `call_script.py:642-672` | **"Fix them first" accepts the model's WHOLE script with no review and no check that "nothing else" changed.** Today's fix (`837dde8ef`, `openings_kept`) only puts back a BLANK opening. `edited_script` merges `{**current, **model_fields}`, and every list (`stages`, `objections`, `faqs`, `example_exchange`) and string (`goal`, `identity`, `ending`, `business_line`) defaults to empty. So a model that returns `"stages": []` or a reworded goal blanks or changes them, and the fixed script goes straight into the draft. Only the language and lint rules are checked, and only on lines the model changed (`language_problems`, `before=`). | Route the fix through `ProposalReview` (only the flagged rows), or diff server-side: accept only changes to the paths the lint named, and refuse any part that went from non-empty to empty. | Code as cited; the founder's opening-wipe on 5 Nov is one instance of this class (BRIEF.md). | Founder rule 6; hard rule 12 |
| A-03 | P0 | `packages/shared/src/calevate_shared/opening_notices.py:26-42,95-97`; `engine.py:4565-4575` | **A switched-on AI or recording notice is silently dropped when the opening line happens to contain "AI", "artificial" or "record" in another sense.** `join_first_words` drops the stored notice sentence whenever `says_ai(opening)` / `says_recorded(opening)` match. These are bare regexes: `\bAI\b|artificial|…` and `record|రికార్డ్|…`. They also match negations. Examples that suppress a notice the owner switched on: "Looking for artificial jewellery?", a business named "… AI Solutions", "I'll update your records", a Telugu accounting app's "ఖాతా రికార్డ్స్", "this call is not recorded". The docstring claims it "fails safe", but it fails safe only in the other direction (a missed word). A false match removes a legally required volunteered notice. | Treat a notice as said only when the line holds the notice phrase the writer was asked for. Store which sentence the weave wrote, compare it exactly, and otherwise keep the stored sentence. Never infer from a single word. | Code as cited. Not reproduced live (local API predates D-971 surfaces). | Hard rule 5; compliance invariants; IT Rules disclosure cited in the module's own docstring |

### P1

| ID | Sev | Where | What happens | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| A-04 | P1 | `script/ProposalReview.tsx:87`; `scriptDiff.ts:136,186` | Every change in a proposal starts **ticked "Keep"**, including `section-removed` rows and parts emptied by the model. One "Add" on a knowledge proposal (queued automatically for every agent on every upload, `script_proposal.py:454-497`) deletes steps or objections. | Removals and emptied parts start unticked and are marked "Pip removes this". | Code | Rule 6; HAX G9 (efficient correction) |
| A-05 | P1 | `workers/opening_notices.py:58-124`; `agents/service.py:3225-3227`; `publishing.py:1525` | D-971 weave: on **every publish**, any opening line that does not match the notice word lists is rewritten by the model and **put live** through `replace_opening_line`, without review. That includes owner-typed and founder-written Telugu lines. Only a History entry ("Opening line now says the notices in its own words") records it. The Script tab does not say a typed opening will be rewritten; only the notices panel does (`openingNotices.tsx:187`). If the owner edits it back, the next publish rewrites it again. | Keep D-971's weave, but make it a proposal the owner keeps (or at least show the new line with an Undo and a notice). Say it next to the opening field. **Founder decision needed:** D-971 says "Pip weaves…", and auto-live vs review is not stated. | Code | Rule 6; owner content |
| A-06 | P1 | `apps/api/copilot/script_actions.py:233-238` | Pip's script action returns `Executed(applied=True, "Writing it now…")` when it has only queued a job. If the proposal then fails (A-07), nothing reports back to Pip's conversation. This matches the founder's "said applied when nothing was applied". | Report "queued", poll the proposal, and say the result or the failure note in the chat. | Code; BRIEF.md incident | Rule 6 |
| A-07 | P1 | `script_assist.py:257-338,422-431` | A proposal fails WHOLE when any model-written line breaks one language rule (textbook word, Latin word in the opening, lint) after one repair. The owner gets `FAILED_NOTE` and none of the good changes. This matches "refused its own Telugu". | Return the proposal with the failing lines flagged (or dropped to the owner's version) instead of failing it all. | Code; BRIEF.md incident | Rule 6 |
| A-08 | P1 | `workers/field_suggestions.py:249-257` | The "new detail only from the script or calls" rule (today's `6c0e887a9`) trusts the model's **own `source` label**. Nothing checks that the label or its words appear in the script or in callers' answers. A model that tags "Main crops grown" as `source: "script"` still gets through. | Ground it: require the label's words, or a quoted span, to be found in the script text or the unlisted-answer rows, or drop the suggestion. | Code | Rule 1 (grounded in THIS business); "AI outputs accepted without validation" |
| A-09 | P1 | `workers/caller_help.py:82-83` | The prompt example is Rytu Khata's: *"She walks farmers through installing the app step by step."* The model's reason is shown to every owner. | Remove the example; state the rule only (as today's lead-detail fix did). | Code | Founder rule 1 |
| A-10 | P1 | `workers/field_suggestions.py:116` | The prompt still carries real-estate examples: `"Your script lists 2BHK and 3BHK flats", "3 callers asked for 6BHK"`. Today's fix removed only the farmer line. | Generic placeholders ("Your script lists X and Y") or none. | Code; `git show 6c0e887a9` | Founder rule 1 |
| A-11 | P1 | `knowledge/CallInstructions.tsx:49-52`; `kb/uploads.py:874-880`; `script_proposals.py:378-387` | "Use in call scripts" always toasts "Suggestion on each Script page soon". The API returns `{agents, skipped}`, and agents with an owner-asked proposal or a hand-written script are skipped. All skipped still says "soon". | Read `agents`/`skipped`: "Sent to 2 agents. 1 is waiting on your earlier change." Show nothing-sent as nothing-sent. | Code | Rule 6 (truthful UI) |
| A-12 | P1 | `agents/patient_caller.py:66-74` | Spoken "Can you see it?" lines hand-written in Hindi, Tamil, Kannada, Malayalam and Marathi ("not yet reviewed by a native speaker"). They are written onto the agent and spoken to callers. | Move to the founder's spoken-style data file; no line for a language until he supplies it. | Code | Founder rule 2 |

### P2

| ID | Sev | Where | What happens | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| A-13 | P2 | `script_routes.py:1573` (`save_draft` with no `base_saved_at`); `lib/api/script.ts:614-617` | fix-lines and "keep" overwrite the draft without the CAS every autosave uses, so another tab's newer draft is lost. | Pass `base_saved_at`; refuse `script_changed_elsewhere`. | Code; `script_builder.save_draft:644-684` | CAS doctrine (CLAUDE.md quality bar) |
| A-14 | P2 | `script_proposals.py:291-317` | A new request (fix-lines, opening, in-language, starter) silently replaces a **ready** proposal the owner may be reviewing, including their rewording in `ProposalReview`. Only Pip's card warns (`script_actions.py:200-203`). | Refuse or warn: "A suggestion is waiting. Replace it?" | Code | Rule 6 |
| A-15 | P2 | `PutLive.tsx:109-134` | If the fix changes nothing (the model left the owner's line, which is then not judged), the dialog shows the same "N lines to fix first" with no message. | "Pip could not fix these. Edit them yourself or put it live anyway." | Code | Rule 6 |
| A-16 | P2 | `workers/script_assist.py:145-151` | The system prompt hand-writes Telugu/Hindi words (`ఆర్డర్, డెలివరీ, బుకింగ్; ऑर्डर, डिलीवरी`) and business-type identity examples ("a shop…", "an app's helpline…"). | Take spoken examples from `spoken_style.json`; drop trade examples. | Code | Rules 1, 2 |
| A-17 | P2 | `agents/specimen_scenarios.py:70-100` (43 `te-IN` lines) | Practice callers are hand-written in Telugu/Hindi, with fixed products per trade: every retail business gets "one kilo of the powder", every local service a "haircut slot". | Fill product and service words from the business's own copy (`GeneratedCopy`), and take wording from the data file. | Code | Rules 1, 2 |
| A-18 | P2 | `agents/trade_playbooks.py:356-418` | Per-trade objections and topics are fixed in code (clinic medicine, real-estate prices, insurance policy…). They are passed as guidance to the script writer. A business placed in the wrong trade gets another trade's objections. | Derive from the business profile and capability copy; keep only the neutral structure. | Code | Rule 1 |
| A-19 | P2 | `agents/handoff.py:187-198` | Spoken transfer lines are hand-written: Telugu/Hindi romanised, plus staged languages "NEEDS NATIVE-SPEAKER REVIEW". Not heard today while transfers are unavailable (`PLATFORM_CANNOT_TRANSFER`). | Data file from the founder. | Code | Rule 2 |
| A-20 | P2 | `teach/questions.py:126-130` (`_COVERED_SQL`); Knowledge and Training screens | "Questions to answer" asks the seeded agent's price, hours and address ("Your setup leaves this open"), and Knowledge says "Your agents don't know anything yet". The agent's own script states prices (65/85/40 lakhs) and hours (9am to 8pm). Coverage reads only facts and documents, never the script. | Count the agent's script (and profile) as covering a topic; never say "don't know anything" when the script holds facts. | `text/*section_training-1440.txt`, `text/c_sunrise_homes_knowledge-375.txt`; `GET .../script` | Rules 1, 6 |
| A-21 | P2 | `workers/teach_questions.py:76-93` | A teach draft's "source" is the model's own citation number. A figure or time in the answer is not checked against that source text. | Check every number, time and ₹ in the draft appears in the cited source; otherwise no draft. | Code | Rule 1 grounding; hard rule 11 spirit |
| A-22 | P2 | Script tab (hand-written); `readiness.py:422`, `roster.py:195` | The hint "Greeting goes under [OPENING]" is bracket syntax for an owner. Readiness gives the hand-written agent 0/20 "Write the opening line" and links to a textarea with no opening field. | A plain "Opening line" box above the hand-written text; no brackets. | `section_script-375.png`; `GET .../readiness` → `"opening": 0, "No opening line yet."` | Rule 4 |
| A-23 | P2 | `panels/extraction.tsx:343,355` | The lead details tab says "Add variable" and "Save variables". | "Add a detail" / "Save". | `text/*section_captured-375.txt` | Rule 4 |
| A-24 | P2 | Settings tab, Model | It shows "the model running now Standard", and Standard also says "It isn't switched on for your account yet; ask your Calevate team to enable it." | One true state. | `text/*section_settings-375.txt` | Rule 6 |
| A-25 | P2 | `script_builder.restore_into_draft:728-748`; `ScriptHistory.tsx` | Restore overwrites an unpublished draft. The confirm says so, but there is no way back to the replaced draft. | Snapshot the replaced draft (one "Undo restore"). | Code | HAX G9 |
| A-26 | P2 | `sections/agentHeader.tsx:364-381`; `PutLive.tsx:240` | The header's Put it live passes no `onFixed`. After a fix, the "What changed" note is still the pre-fix diff (`useState` initialiser), and the header path has no Undo for the fix. | Recompute the summary when the draft changes; offer Undo. | Code | Rule 6 |

### P3

| ID | Sev | Where | What happens | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| A-27 | P3 | `sections/agentHeader.tsx:108-117` | "Undo waiting changes" runs from the ⋯ menu with no confirm. Whether the discarded version can be restored from History is UNVERIFIED. | Confirm, or toast with Undo. | Code | HAX G9 |
| A-28 | P3 | `opening_notices.py:26-31`, `script_lint.py:147-172`, `teach/questions.py:76-84`, `turn_checks.py:203-223` | Detection word lists are hand-typed for te/hi/en only. Staged languages miss them (double notices, lint misses). | Move the word lists to a data file per language. | Code | Rule 2 (data, not code) |
| A-29 | P3 | `call_mistakes.py:170`, `retired_lines.py:18-35`, `caller_help.py:7`, `call_handling.py:137` | Comments and docstrings cite Rytu Khata calls in Telugu. That is session narration in code. | Move to the decision log. | Code | Hard rule 13 |

---

## 3. Research notes

- Microsoft's Guidelines for Human-AI Interaction (CHI 2019) include G8 "Support efficient
  dismissal" and G9 "Support efficient correction": make it easy to edit, refine or recover
  when the AI is wrong. This is the standard behind A-02, A-04, A-05, A-25 and A-27. An AI
  edit to owner content should be reviewable and reversible. Sources (searched 5 Nov 2026):
  [Guidelines for Human-AI Interaction](https://medium.com/microsoft-design/guidelines-for-human-ai-interaction-9aa1535d72b9),
  [AI Guidelines cards (PDF)](https://microsoft.com/en-us/research/uploads/prod/2019/01/AI_Guidelines_Cards_PrintQuality.pdf),
  [HAX Toolkit examples](https://www.microsoft.com/en-us/haxtoolkit/library/example/7,10,11,13/).
  This repo's own `ProposalReview` already follows the pattern. The defect is that "Fix them
  first" and the D-971 weave bypass it.
- Compare-and-set on the draft is already this repo's rule (`save_draft`'s `base_saved_at`).
  A-13 is a missed call site, not a design question.
- A-03: the module docstring says no Indian rule prescribes the wording, and quotes IT Rules
  G.S.R. 120(E) asking for a "prominently prefixed audio disclosure". I did not re-read that
  primary source this session. The fix does not depend on the wording: it only has to stop a
  keyword match from removing a notice that is switched on.

## 4. Proposed fixes (grouped so phase-2 lanes do not collide)

**G1. Proposal safety (A-01, A-02, A-04, A-13, A-14, A-15, A-26)**
- `apps/api/agents/script_routes.py` (fix-lines: refuse a hand-written script, or a
  raw-text fix mode; CAS), `apps/api/agents/script_proposals.py` (do not replace a ready
  proposal unasked), `apps/workers/script_proposal.py` (server-side guard: for `change`
  and `knowledge`, keep every path not named in the request, and never let a non-empty part
  become empty; generalise `openings_kept`), `apps/workers/script_assist.py`
  (`edited_script`: refuse emptied lists).
- Web: `script/PutLive.tsx` (show the fix in a `ProposalReview` limited to the flagged rows,
  or a before/after; "could not fix" message; recompute the summary),
  `lib/api/script.ts` (`useKeepFixedScript` sends `base_saved_at`),
  `script/ProposalReview.tsx` + `scriptDiff.ts` (removals start unticked),
  `sections/agentHeader.tsx` (`onFixed`, Undo).
- Tests: a fix-lines test on a hand-written script; a test that a stage list emptied by the
  model is kept.

**G2. Notices (A-03, A-05, A-28)**
- `packages/shared/src/calevate_shared/opening_notices.py`, `engine.py::join_first_words`
  (exact-phrase match against what the weave wrote, stored per agent; negation-safe),
  `apps/workers/opening_notices.py` + `apps/api/agents/opening_notices.py` (store the woven
  phrase; review or notify plus Undo, pending the founder's decision),
  `script/ScriptSections.tsx` (say at the opening field that notices get woven in).
  Hard rule 5 tests: "artificial jewellery", "your records", and a business name containing
  "AI" each keep the stored notice.

**G3. Pip honesty (A-06, A-07)** (coordinate with the Pip lane)
- `apps/api/copilot/script_actions.py` (queued is not applied; report the outcome),
  `apps/workers/script_assist.py` + `script_proposal.py` (partial proposal with flagged
  lines instead of failing everything).

**G4. Grounding and no business-specific code (A-08, A-09, A-10, A-16, A-17, A-18, A-20, A-21)**
- `apps/workers/field_suggestions.py` (verify `source` against the script and unlisted
  answers; drop the BHK examples), `apps/workers/caller_help.py` (drop the farmer example),
  `apps/workers/script_assist.py` (drop the Indic words and trade examples),
  `apps/api/agents/specimen_scenarios.py`, `trade_playbooks.py` (business copy instead of
  trade constants), `apps/api/teach/questions.py` (script counts as coverage),
  `apps/workers/teach_questions.py` (figure check against the source).

**G5. Hand-written spoken lines to data files (A-12, A-19, A-28)**
- `apps/api/agents/patient_caller.py`, `apps/api/agents/handoff.py`, and the detection
  lists. Founder supplies wording in the spoken-style data file.

**G6. Plain words and truthful UI (A-11, A-22, A-23, A-24, A-25, A-27)**
- `knowledge/CallInstructions.tsx` (use `agents`/`skipped`), `script/HandWritten.tsx`
  (opening box), `apps/api/agents/readiness.py` (hand-written opening),
  `panels/extraction.tsx`, Settings model block (`AgentModel.tsx`),
  `script/ScriptHistory.tsx` + `script_builder.restore_into_draft` (undo restore),
  `sections/agentHeader.tsx` (confirm Undo).

**G7. Comments (A-29)**: the comment files listed under A-29, as hard rule 13 cleanup.
