# 03 · AI quality end to end: Outpero vs Calevate (28 Nov 2026)

Scope: brief → follow-up questions → script → AI editing → knowledge/training → rehearsal →
in-call behaviour → post-call → strictness/raw prompting → versions. Read-only gap analysis.
Founder rule applies throughout: never copy Outpero; every proposal below is Calevate-native
and no proposal hand-writes a Telugu or Hindi line for an agent to say (lines come from the
writer, checked by code and reviewed by the owner/founder).

## Evidence base and its classes

| Source | What it is | Class |
|---|---|---|
| `../ai-tests.md` (Rehearse, Swara edit, clinic build) | first-hand in Outpero's app, 28 Nov 2026 | OBSERVED |
| `../screens/app-routes.md` (Training, Outcomes, Settings) | first-hand, 28 Nov 2026 | OBSERVED |
| `../../outpero-vs-calevate-2026-11-28/LOG.md`, `outpero_script.txt`, `calevate_script.txt` | same brief built on both, 28 Nov 2026 | OBSERVED |
| Founder test calls 27 Nov 21:35 and 28 Nov 00:48 (scratchpad notes `call_2135.md`, `call_0048.md`) | real Rytu Khata calls, transcripts + call page | OBSERVED |
| Calevate code at `794e7acdc` (rel-0.5.98) | read at source this session, paths cited | CODE (what the code says, not what a call did) |
| rememory 47c56d9a, 2d1e84b8, 7b05bdb2, d9155474, 04ccf39c and others cited | prior sessions' decisions | REPORTED unless re-read in code here |

**Version caveat that changes the reading of the Calevate side.** The Calevate first-run
build in `LOG.md` (C1-C13) ran BEFORE release 0.5.98: commits `ac52ba316` ("First run and first
campaign tell the truth (28 Nov trial defects C3-C13)") and `45ce56730` (opening, one step per
owner task, facts/rules/hours pinned, question writer reads the brief) exist to fix exactly
those defects, and `origin/production` holds them since 02:25 IST 28 Nov. The 00:48 call ran
0.5.97; the in-call fixes for it are `43e6cb877` (0.5.98). **So every 0.5.98 fix below is
CODE-ONLY: no call, no first-run run and no eval run has been observed on it.** That is
itself gap #1-#3's root: we ship rule text faster than we measure it.

Scale used: BETTER / PARITY / WEAKER / LACK (Calevate relative to Outpero), on what each
product actually produced, with the code position noted separately where it differs.

---

## 1. Scorecard

| # | Dimension | Outpero (observed) | Calevate (observed, then code) | Score |
|---|---|---|---|---|
| 1 | Brief intake | 636-char brief taken intact; job type on the same screen | 803 chars typed became 821 garbled (C3-a); job asked at step 3. Code: C3-a and job preselect fixed in `ac52ba316` | WEAKER observed; PARITY in code, unverified |
| 2 | Follow-up questions | 4, all read from the brief (price, place, hours, Never chips); clinic: 1 question, chips generic | 3: districts served (wrong for an app), languages (useful), generic "one thing". Code: `apps/workers/first_run.py:132` `QUESTIONS_INSTRUCTION` now forbids place questions for remote businesses and asks hours/never with trade-fit Never options | WEAKER observed; claimed BETTER in code, unverified |
| 3 | Answers → knowledge | 3 facts + 2 rules in Training (but "Hyderabad" filed as service area, calling hours as business hours) | 0 quick facts; brief pasted verbatim as main task; hours not applied. Code: `45ce56730` pins fact sentences and Never-rules (`apps/api/teach/pinned.py` `pin_pairs`), calling window from brief | WEAKER observed; PARITY in code, unverified |
| 4 | Opening line | Name-check only ("am I speaking to {Lead Name}?"); blank variable left as a gap in rehearsal | First-run campaign: NONE ("No opening line yet", P0 C12-a). Real campaign calls (2135/0048): who + business + why + permission, good. Code: `call_rules.PLACED_OPENING_RULE`, `opening_line.write_opening` second ladder, heal writes missing openings | BETTER on real campaigns; LACK on first run (fixed in code, unverified) |
| 5 | Step structure | 8 steps, splits install / language / farm / expense+sale; one example line per step | 5 steps, heavier bundling (farm + expense + sale), close "confirm all steps are done"; BUT step outcomes, ways out per step, 5 push-back answers, Q&A per step. Code: `owner_words.owner_tasks` one step per owner task; close never "confirm all done" | Mixed: outcomes/branches BETTER, granularity WEAKER observed |
| 6 | Examples | One example per step, which itself bundles actions and says "tell me when done" (the model then copies it) | Example-led design: 3-5 turns + confused/stuck/busy per step per language, each one action (`apps/workers/step_writer.py:71` `STEP_INSTRUCTION`) and lint-checked | BETTER by design |
| 7 | Fact use | "free for farmers in Hyderabad, Telangana" (location misused as a price condition), repeated in rehearsal | "free app" used where it fits; no mixing seen | BETTER |
| 8 | Invented promises | WhatsApp guide + "support 9am-6pm" with no WhatsApp action; clinic "booking confirmed" + WhatsApp with no calendar | None seen in the script. Code: `script_lint.unbacked_promise` (`apps/api/agents/script_lint.py:255`) blocks WhatsApp/SMS/call-back/booking/hand-over promises the capability manifest cannot keep; in-call `ACTION_CLAIM_RULE` (`engine.py:3462`) | BETTER |
| 9 | AI editing speed | Swara: 4 instructions in ~30 s, ~₹0.2 | Not measured. A free-form change re-plans and rewrites every step (`apps/workers/campaign_script.py:403` `write_request` → `script_writer.plan_for` outline → one request per step, concurrency 6, 50 s timeout each) | UNKNOWN (likely WEAKER; measure) |
| 10 | AI editing faithfulness | Followed all 4 instructions, kept owner structure, touched nothing else (also did not fix an untouched error) | A whole-script ask rewrites all steps; owner instruction text is kept word for word (`OWNERS_NOTE`), but the heal pass once rewrote 8 of 11 owner instructions (bug 5db1e6f2, fixed 0.5.94) | WEAKER (structural risk) |
| 11 | Change visibility + undo | "updated" tag per step, Undo, "Helpful?" | Per-change review rows with Keep/Edit/Reset (`ProposalReview.tsx` mounted on `CampaignWorkspace.tsx:436`), 30 restorable versions per holder with CAS (`apps/api/campaigns/script_history.py:47`) | BETTER |
| 12 | Facts vs rules | Typed Fact/Rule with category, filter, search | Facts only: teach rules retired (D-1017); Never-rules now stored as pinned facts (0.5.98) | WEAKER (taxonomy) |
| 13 | Teach from photo / voice | Text 0.1, photo 0.15, voice 0.25 credits | Teach box: text, photo (OCR), file, voice (STT, owner confirms what was heard) (memory e070121c, `apps/workers/kb_teach.py`) | PARITY |
| 14 | Struggles from real calls | "Where it struggled on real calls" | "Questions to answer" from knowledge gaps with source-cited drafted answers (`apps/api/teach/questions.py`, D-893) + per-agent call-mistake card with auto-fix state (D-949/D-985) | BETTER |
| 15 | Typed rehearsal | Rehearse: whole call typed, same script and rules, tool calls inline with reason and "Not actually run", ₹0.20/msg | Try it chat on the agent page tests the agent's LIVE engine agent or its "Just the business" copy (`apps/api/teach/try_chat.py:57`), never a campaign's or line's script and never a draft; only "looked up knowledge" is surfaced though the engine returns every tool and result (`apps/api/engine/test_chat.py:40-52`) | WEAKER |
| 16 | One action a turn | Bundled in turns 3 and 5 of the rehearsal | Bundled in 9 turns of the 00:48 call ("X చేసి, Y", "A మరియు B"). Code: `PROCEDURE_LEAD`, `ACTIONS_LEAD` (`call_script.py:1166-1174`) say it on the step list itself (0.5.98) | PARITY observed (both fail); fix unverified |
| 17 | Bare "okay" is not done | Rehearsal turn 4: asked "did you open it?" | 00:48 call moved on at four bare "Okay"s. Code: same 0.5.98 leads + `_UNCLEAR_BULLET` | WEAKER observed; fix unverified |
| 18 | "Tell me when done" | Asked in turns 3 and 5 | "అది సేవ్ అయిందో లేదో చెప్తారా?" twice on 00:48. Code: `CHECK_WHAT_THEY_SEE` (`call_script.py:1439`) | PARITY observed (both fail) |
| 19 | Early stop | Offered help later; no call-back time, no "what is left" | 21:35: "you finished the app setup" two steps short. Code: `STOPPED_EARLY_RULE` (0.5.96) | WEAKER observed; fix unverified |
| 20 | Unverified claims | Rehearsal did not claim records | 21:35: "our records show your number is registered". Code: `CALL_REASON_RULE` "our list, never records you checked" (`engine.py:5074`) | WEAKER observed; fixed in code |
| 21 | Numbers spoken | Clinic: fee as "three hundred" and 108 as "one-o-eight" in Telugu letters | Rule: any number or code digit by digit with pauses; amounts the English way (`engine.py:3150` `_NUMBER_BULLETS`; D-1024 English letters for Telugu). No live Telugu emergency-number observation | BETTER in rules; unverified |
| 22 | Code-mix | Natural Tenglish, "Telugu enhance" tick | Natural on both calls; owner setting light/natural/heavy (`call_script.py:641` `CODE_MIX_SENTENCES`); some textbook words ("మరియు") still spoken | PARITY |
| 23 | Outcome labels | 4 labels, long classifier-style definitions with explicit NOT-interested exclusions, editable | Per-agent outcomes, AI-drafted once, editable, max 8, meaning ≤200 chars (`packages/shared/src/calevate_shared/business_outcomes.py:33-35`), plus derived system outcome | PARITY (shorter definitions) |
| 24 | Auto capture fields | Job-fit data fields (Callback time, Interest level enum, Farm name/location, First expense/sale); clinic: Date-typed field | Typed fields exist (text/number/bool/enum/date, `extraction.py:28`), but the Rytu agent's drafted fields were mostly judgements (Installation Status, Setup Progress, Interaction Outcome, Campaign Goal Met) that then contradicted the step reading (Installation Status "Not mentioned" while confirmed at turn 13 on 00:48) | WEAKER |
| 25 | Summaries / call page truth | Not observed (their test call failed silently) | False completion summary on BOTH founder calls; markers quoting lines that do not say it; step 3 side step marked Done. Code: `apps/workers/step_truth.py` strips completion clauses by regex, widened again in 0.5.98 | LACK of evidence for Outpero; Calevate WEAKER than it should be |
| 26 | Strictness | Global slider Flexible 1-5 | Per-step "say" mode (exact words, `call_script.py:847`) + example-led steps; no global dial | PARITY (different shape) |
| 27 | Power / raw prompting | "Your prompt, nothing added" keeping core safety | `CallScript.raw_override` exists (`call_script.py:1009`, 20,000 chars, `promo`/`unbacked_promise` still checked); prompt anatomy is admin-only (`apps/api/agents/prompt_anatomy.py`); hard rule 5 layers can never be dropped | PARITY for experts, deliberate; no owner-visible "what it is told" |
| 28 | Versions | Published version + timestamp; switching job saves a version | 30 versions per holder, owner-made never pruned, put-back with CAS (D-1039) | BETTER |
| 29 | Automatic repair | None; edits only what is asked | Healer repairs real-call mistakes in the script and puts it live with Undo (D-985/D-1038) | BETTER (with the faithfulness risk in row 10) |
| 30 | Eval harness | None visible | `scripts/eval_script_writer.py` (12 cases), `scripts/eval_calls.py` + `scripts/call_sim/` (15 personas, Rytu only, mostly hand-written English stand-ins; `--live` VPS only), `tests/fixtures/golden_transcripts.json`, register evals | BETTER in kind, thin in coverage |

Net: Calevate's DESIGN is ahead on the hard problems (examples that cannot bundle, promise
blocking, outcomes per step, healer, versions, evals). Calevate's OBSERVED output on 27-28 Nov
was behind on the things a caller hears (bundling, bare OK, false "done", false summary) and
on the first-run path (no opening, garbled brief). The gap is between rule text and measured
behaviour.

---

## 2. Findings by stage, with what each actually produced

### 2.1 Brief and follow-up questions
- Outpero asked four brief-specific questions and turned them into Training. Its mistakes are
  in the mapping, not the asking: "Hyderabad" became a service area AND a price condition;
  calling hours became support hours. Outpero's clinic flow asked one question with generic
  chips ("never guarantee returns") that do not fit a clinic.
- Calevate (pre-0.5.98) asked a service-area question for an app. `QUESTIONS_INSTRUCTION`
  (`apps/workers/first_run.py:132`) now says not to and asks Never options "that fit what this
  business does". `apps/api/first_run/questions.written_questions` drops items that break a
  rule. No run has measured either.
- Neither product separates *business location* from *service area* from *calling window*
  from *opening hours* as four distinct facts; Outpero's errors show why that matters.
  Calevate's `hours` kind already says "never when the agent calls" — one of the four.

### 2.2 Script generation
- Calevate architecture (memory 7b05bdb2, code read): structure by code
  (`apps/api/agents/script_plan.py`), one strict-JSON request per step
  (`apps/workers/step_writer.py`), one check registry (`apps/api/agents/script_checks.py`),
  failing steps rewritten alone up to two rounds. This is the right shape and better than a
  one-pass writer.
- Pre-0.5.98 output still had: no opening, a 3-task step, a "confirm all done" close, brief
  pasted as main task with 0 facts. 0.5.98 addresses each (`45ce56730`). Not re-run.
- Outpero's examples teach the model to bundle ("open Chrome … then tell me"), and its
  rehearsal bundled accordingly. Our `STEP_INSTRUCTION` forbids it in the examples; the 00:48
  call bundled anyway, which is why 0.5.98 also put the rule on the step's action list
  (`ACTIONS_LEAD`).
- Trade safety rails: Outpero's clinic script put emergency first (good) but no "no medical
  advice"; it promised "booking confirmed" with nothing connected. Calevate has promise
  blocking but no trade-derived safety rails at all (`grep -i emergenc` over
  `apps/api/agents/trade_playbooks.py` and starters: nothing; `trade_playbooks.JOB_SHAPES` is
  per job, not per sensitivity).

### 2.3 AI editing (Pip vs Swara)
- Swara: one pass, four instructions honoured, owner structure kept, per-step "updated" tag,
  Undo, ~30 s.
- Pip: a free-form ask on an existing script goes `write_request` → `WriteRequest("whole",
  base=base)` (`apps/workers/campaign_script.py:403`) → `plan_for` builds a NEW model outline
  when an instruction is present (`apps/workers/script_writer.py:763-787`) → every step is
  re-written. Part asks (a named step, the opening, examples) are targeted. So "make every step
  one action and remove WhatsApp" re-generates the script rather than editing it. The review UI
  then lets the owner keep change by change, which is better than Swara's tags, but the owner
  must review a regenerated script to find four edits.
- Latency of a whole Pip edit is not measured anywhere (no timing in eval reports read).

### 2.4 Knowledge and training
- Teach box (text/photo/file/voice) and source-cited "Questions to answer" are at least
  parity and the drafted-answer loop is better.
- Rules: D-1017 retired teach rules; 0.5.98 stores Never-rules as pinned facts. A rule is not
  a fact: the judge (`call_rules.CALL_RULES`) and turn checks never read pinned facts as
  prohibitions, so an owner's "Never promise a call-back time" is enforced only by the model
  reading a fact list.

### 2.5 Rehearsal
- Outpero's Rehearse runs the employee's real script, shows tool calls with reasons and "Not
  actually run". It is how an owner sees "it would hang up here, because…".
- Calevate's Try it chat (`apps/api/teach/try_chat.py`) reaches only the agent's live engine
  agent or the "Just the business" copy; since D-1019 an agent holds no engine agent of its own,
  so the campaign script the owner is about to launch cannot be typed through. The engine
  returns `tools` and `tool_results` per turn (`apps/api/engine/test_chat.py:47-52`); the screen
  shows only a "looked up" flag (`apps/web/src/components/improvement/TryChat.tsx:15`). Our
  `turn_checks` (bundling, textbook words, early comma, asked-done-too-soon) run on practice
  runs but never inline in a typed rehearsal. The test copy mechanism
  (`agent_test_copies`, republished with a campaign's script for a test call) is the seam that
  makes a campaign rehearsal possible. Founder decision 5a08c365 rules out an in-browser
  VOICE widget, not a typed chat.

### 2.6 In-call behaviour (from the two founder calls)
21:35 (0.5.95/96 era) and 00:48 (0.5.97):
- Bundled actions: 9 turns on 00:48 (10, 12, 22, 28, 30, 34, 36, 42, 44).
- Bare "Okay" taken as done: turns 25, 27, 33, 41 on 00:48; on 21:35 the caller later admitted
  he had not done it (turn 47), the clearest proof that "okay" is not done.
- Report-back requests: turns 36, 44 on 00:48.
- False completion on early stop: 21:35 turn 58.
- False records claim: 21:35 turn 10.
- Good: opening order, one action at install/login on 00:48, side question answered and back to
  the step (21:35 turns 7-12), natural code-mix.
Each failure has a 0.5.96/0.5.98 rule now. The pattern across 26 Nov → 28 Nov is: one call,
one rule patch, next call shows the same class in a new form. The call-sim scorecard exists
(`scripts/eval_calls.py`, memory c20a54dc) but its Rytu recordings are hand-written English
stand-ins except two, and nothing requires a live sim run before a prompt release.

### 2.7 Post-call
- Summaries on both calls claimed completion; the 0.5.96 scrub and the 0.5.98 widening are
  regex clause removal over model prose (`apps/workers/step_truth.py` `without_unreached`).
  That is defending text after generation rather than generating from the truth.
- Markers quoted lines that do not contain the words (21:35 turn 7; 00:48 turns 1 and 21).
- The step reading needs Pip consent (`step_truth.py` docstring: "when the owner has turned Pip
  on"); without it only the transcript-bound check stands.
- Drafted capture fields duplicated judgements already produced by step progress and outcomes,
  so three sources disagreed on one call. `script_builder.job_details` already knows
  status-type fields are "heard, never asked" (memory 5b5faada); the field drafter does not use
  that to avoid proposing them.

---

## 3. Improvements (Calevate-native), ranked by call-quality impact

Effort: S ≤ half a day, M ≈ 1-2 days, L ≈ 3+ days of one lane. "Measure" names the harness.

### G1. A release cannot change in-call rules without a live Telugu sim run on real-call personas — L
Why: the same failure classes (bundling, bare OK, report-back, false done) reappeared across
0.5.94-0.5.98; each fix is rule text proven by unit tests on the text, not by a call.
Build: (a) turn the founder's real calls (21:35, 00:48, and every later founder test call) into
call-sim personas: caller lines taken from `transcript_turns.text_redacted`, name and number
redacted, stored under `scripts/fixtures/call_sim/recorded/rytu/` with `expected_flags` from the
founder's notes — recorded lines, not hand-written agent lines; (b) a `--live` run of
`scripts.eval_calls` against the release candidate's composed prompt on the VPS, its report
committed under `docs/evidence/call-sim/`, required by the release checklist when
`engine.py`/`call_script.py`/`spoken_style.json` change; (c) scorecard kinds already exist
(`several_actions`, `done_without_signal`, `moved_on_unclear`, `claimed_complete`).
Acceptance: on the Rytu persona set, `several_actions` = 0, `done_without_signal` = 0,
`claimed_complete` = 0, report-back asks = 0 across ≥ 10 live runs per persona; baseline
ratchet only shrinks. Measure: `uv run python -m scripts.eval_calls --live --holder campaign:<id>`
+ `tests/call_sim_test.py` equality ratchet.

### G2. Rehearse the real script: typed rehearsal on campaigns and Inbound lines, tool calls and turn checks inline — M
Why: owners cannot type through the script they launch; Outpero can. Ours can be better:
Outpero shows tool calls; we can also show, per agent turn, the check that fails ("two things
to do in one turn", "asked them to report back", "textbook word") because `turn_checks` already
computes them.
Build: "Rehearse" on the campaign and line pages using the test copy republished with that
holder's current (or draft) script (`agents/paid_test_calls.refresh_test_copy`,
`copy_call_live` guard); render `tool_results` in owner words ("Would hang up — not run",
"Would book a call back for 5 pm — not run", "Looked up: prices"); run
`turn_checks.turn_problems` on each reply and show a quiet flag with "Fix this in the script"
(a part ask). Draft testing removes the "test only what is live" limit for typed rehearsal.
Acceptance: a draft campaign can be rehearsed before Put it live; every tool the engine reports
appears in the turn with "not run"; a reply with two actions shows the flag; nothing contacts a
person (test window open, opt-out recorded_in_test). Measure: web test with a mocked test-chat
turn carrying two tools; API test that the copy carries the holder's draft script.

### G3. First-run end-to-end eval: brief → questions → script, scored, for the Rytu and a clinic-receptionist brief — M
Why: the P0 "no opening" and the garbled-brief bugs shipped to the first screen a client sees;
0.5.98 fixed them in code with no run.
Build: two `tests/fixtures/script_writer_cases/cases/` entries that start from the raw brief
(`brief.txt` verbatim; a fictional inbound clinic brief in English), run the question writer,
answer with recorded answers, run the first-run write, and score: opening present and passes
`placed_opening_problems`; one step per owner task (`owner_words.owner_tasks`); facts pinned
count ≥ facts in brief; Never-rules present; calling window applied; no question about service
area for a remote business. Then re-do LOG.md C1-C12 by hand in the product once.
Acceptance: both cases pass in recorded mode in CI and in `--live` on the VPS; the manual re-run
shows an opening on "Hear it". Measure: `uv run python -m scripts.eval_script_writer --cases
first_run_rytu,first_run_clinic_inbound`.

### G4. Simulated-call gate before the owner sees a draft — M (after G1)
Why: founder's own target design (memory d9155474: "simulated-call gate before review") is not
built: no product path runs `scripts/call_sim` (grep over `apps/`).
Build: after `campaign_script._write` stores a draft, an outbox job runs three personas
(cooperative, stuck, stops early) against the draft via the test copy; findings attach to the
draft as `script_checks` warnings with turn numbers, and failing steps go back to
`write_script(mode="steps")` once. Metered to the client's AI allowance like the healer (D-985).
Acceptance: a draft whose step example bundles two actions is flagged before review; the
owner sees "Tried it 3 ways: 1 problem" with the turn. Measure: a fixture draft with a known
bundled step; count of drafts reaching review with a sim finding.

### G5. Summaries and statuses generated from the step state, not scrubbed after — M
Why: two consecutive founder calls had false completion summaries; regex clause removal has
been widened twice.
Build: the extraction receives the settled step reading first (already true) and the summary
is composed in two parts: a code-built "where it got to" clause from `StepProgress`
(reached / not reached / not needed) and the model's prose restricted to what the caller
wanted and said, with completion verbs refused in prose by the same check the call page uses.
Markers: a suggested quote must be found in the turn it is anchored to after `_plain`, or it is
dropped (extend `moments.said_on` to Latin quotes too).
Acceptance: on `golden_transcripts.json` plus the 21:35 and 00:48 transcripts (redacted), no
summary says done/complete/all steps when the last non-branch step is not reached; zero markers
whose quote is absent from their turn. Measure: extraction golden run + a new fixture pair.

### G6. Capture fields are data, judgements come from steps and outcomes — S
Why: Installation Status / Setup Progress / Interaction Outcome / Campaign Goal Met restated
what step progress and the business outcome already say, and disagreed with them.
Build: `apps/workers/lead_fields_draft.py` refuses (and `field_suggestions` never offers) a
status/progress/outcome/result field when the holder has steps or outcomes — reuse the
`job_details` "heard_detail" test (memory 5b5faada) — and is told to propose the values the job
collects (things a person says: a time, a choice, an amount), typed (`date`, `enum`, `number`).
Acceptance: re-drafting fields for the Rytu case yields no status-type field; each proposed
field has a non-text type where one fits. Measure: unit test over the drafter's parser +
`eval_script_writer` "a judgement field asked" check stays 0.

### G7. A targeted edit mode for free-form changes — M
Why: a four-line change re-plans and rewrites every step; faithfulness and speed both suffer
(rows 9-10). Outpero's editor is fast because it edits.
Build: `WriteRequest("edit")`: one small request reads the instruction against the script's
outline and returns `{paths, change_per_path}`; only those steps/lines go through `step_writer`
or `lines`; untouched stages are byte-identical (asserted); a global rule ("one action per turn
everywhere") fans out as `fields=` per step rather than a new outline. Review rows already show
what changed; add a one-line "What Pip changed" note per row and time the run.
Acceptance: on the Swara instruction set (four instructions on the Rytu script), all four are
honoured, unchanged steps are identical, wall time p50 ≤ 40 s on the VPS. Measure: an
`eval_script_writer` edit case with the instruction and expected touched paths; timing logged
in `holder_script_written`.

### G8. Sensitivity rails derived from what the business does, not a clinic table — M
Why: a health, money or legal business needs "never advise / never guarantee / urgent → say
where to get help" whatever the trade label (founder: not clinic-centric). Outpero got emergency
right and medical advice wrong; we have neither.
Build: the business copy (`BusinessFit`) gains a `sensitive` set read from the brief by the
model (health advice, money advice, legal advice, urgent danger); each maps to English writer
rules and a judge rule in `call_rules.CALL_RULES` (one record, four readers, as the module
requires); urgent danger yields a side step whose words the writer writes in the call language
and the owner reviews. Numbers in it obey `_NUMBER_BULLETS`.
Acceptance: the clinic case gets an urgent side step and a never-advise rule without the word
"clinic" anywhere in code; an app business gets none. Measure: `eval_script_writer` cases
clinic_reminder (inbound) + a fictional insurance brief; judge fails a practice caller who asks
for a diagnosis and gets one.

### G9. Owner rules as rules, not facts — S (needs a founder decision: amends D-1017)
Why: Never-rules pinned as facts are read as information, not prohibitions; no checker reads
them.
Build: a holder-level `owner_rules` list (Never … lines, owner words kept verbatim) compiled
into its own short section, read by the judge and by `unbacked_promise`-style checks where a
rule names a promise ("never promise a call-back time" → offers_call_back with time).
Acceptance: a practice caller who asks "call me at 5?" fails the run when the agent promises
5 pm under that rule. Measure: test_conversations judge fixture.

### G10. Native-language turn checks stop depending on hand-kept word lists — M
Why: `several_actions` and the done/OK checks read English and founder-supplied
`call_words.json`; Telugu joins ("X చేసి, Y", "మరియు") slipped through, and the open founder item
is to add more verbs. Lists can't keep up.
Build: keep the word-list check as the fast path; add a model-judged per-turn classifier in the
sim and the rehearsal (G2) for non-English turns: "how many actions does this turn ask for?",
"does it ask them to report back?", returning counts only. Calibrate it against the founder's
annotated turns of 21:35 and 00:48.
Acceptance: on those two calls the classifier finds the nine bundled turns of 00:48 and both
report-back asks, with no false flags on single-action turns. Measure: a labelled turn fixture
(turn index + expected kind, no new Telugu written).

### G11. Questions that separate place, service area, calling window and opening hours — S
Why: both products mis-filed these; ours asked the wrong one.
Build: `QUESTIONS_INSTRUCTION` already distinguishes `hours` from calling; add the same for
`location` vs areas served and have the writer's pinned-fact step label each ("Based in",
"Serves", "Calls between", "Open"). The script writer reads the labels, so "free" is never
conditioned on "based in".
Acceptance: the Rytu brief yields "Based in Hyderabad" (not a service area) and "Calls between
9 and 6" (not support hours). Measure: G3's first-run case.

### G12. Outcome definitions an owner can make precise — S
Why: Outpero's labels carry inclusion and exclusion criteria; ours cap meaning at 200 chars
with neutral starters, so "Interested" vs "Not interested" drift.
Build: `BusinessOutcome` gains `counts_when` / `not_when` (bounded), drafted per job by
`business_outcomes_draft`, shown as two short lines in the editor; the extraction prompt renders
both.
Acceptance: on golden transcripts, a polite "I'll think about it" is not labelled Not interested.
Measure: extraction golden run with labelled outcome expectations.

### G13. Early stop: say what is left and offer the later, measured — S (rule exists)
Why: 21:35 closed with "you finished the setup" two steps short; `STOPPED_EARLY_RULE` exists
since 0.5.96 but has no persona that stops mid-task at a known step.
Build: a sim persona that stops after step N (N from the script) and a scorecard kind
`left_unsaid` (close turn names no remaining step) beside `claimed_complete`.
Acceptance: 0 `claimed_complete`, 0 `left_unsaid` across 10 live runs. Measure: G1 harness.

### G14. Numbers on emergency and price lines, checked — S
Why: our rules are better than Outpero's output on paper; no Telugu observation exists of an
urgent number or a fee spoken by our agent.
Build: add a fee and an urgent number to the clinic case; run `turn_checks` `spoken_number`
and the digit-by-digit rule in the sim.
Acceptance: urgent numbers digit by digit with a pause each; amounts the English way per
D-1024. Measure: G1/G8 cases.

### G15. Let the owner see what their agent is told, and a stick-to-script dial that maps to what exists — S
Why: Outpero offers strictness and raw prompting; we have per-step "say" mode and admin-only
anatomy. A raw prompt for clients would conflict with hard rule 5 only if it could drop the
platform floor, which `raw_override` does not.
Build: an owner-facing read-only view of the OWNER part of the compiled prompt (never the
platform rules, D-674), and a three-position "Follow the script" setting that sets examples-led
(default), "say these words" on the opening and close, or every step in say mode.
Acceptance: switching to "exact words" sets `mode="say"` on the chosen stages and the publish
read-back still finds the truthful-answer and confidentiality markers. Measure: publish verifier
tests.

---

## 4. Top 15 gaps by call-quality impact (summary)

1. In-call rules ship without a live call measurement; bundling, bare-OK, report-back and false-done recurred across 0.5.94-0.5.98 (G1).
2. No typed rehearsal of the campaign/line script or of a draft; tool calls and turn checks not shown (G2).
3. First-run path produced no opening and a garbled brief; 0.5.98 fixes are unrun (G3).
4. No simulated-call gate before the owner reviews a draft (founder's own target design) (G4).
5. Post-call summaries claimed completion on both founder calls; truth is regex-scrubbed after generation (G5).
6. Drafted capture fields are judgements that contradict step progress and outcomes (G6).
7. A free-form Pip edit regenerates every step: faithfulness risk and unmeasured speed (G7).
8. No sensitivity rails (health/money/legal advice, urgent help) derived from the business (G8).
9. Owner Never-rules are stored as facts; no checker enforces them (G9, founder decision).
10. Non-English turn checks depend on word lists that miss Telugu joins (G10).
11. Place / service area / calling window / opening hours not kept apart (G11).
12. Outcome definitions too short to separate close labels (G12).
13. Early-stop rule has no persona measuring it (G13).
14. Emergency numbers and fees never observed spoken by our agent in Telugu (G14).
15. No owner view of what the agent is told; no global stick-to-script setting (G15).

Out of this area but blocking AI-quality verification for trial clients: no shared test
number (LOG C11-a, founder item T-22) and the 3-minute trial test-call cap, which cuts a
4-5 minute guided call before its last steps.
