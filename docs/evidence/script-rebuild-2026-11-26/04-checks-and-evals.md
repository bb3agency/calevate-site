# 04: Quality checks, evaluation assets, and a pre-review simulated-call gate

Read-only research, 26 Nov 2026. Code: `D:\Agency\calevate\.claude\worktrees\agent-tabs` at `b5613a0b3`
(feat/agent-four-tabs). All paths below are relative to that worktree.

**Sources.** I read the code myself. The rememory ids I used are `d980cc9b` (the 26 Nov test call),
`c20a54dc` (the call_sim feature), `01d9deb9` (the lean prompt), `d95ec1ab` (writerfix), `8a49f9d4`
(finish_written), `1d6ff902` (D-1031 refine), `f368c630` (D-1022 stalled), `f23a4b51` (wave-5 C1),
`4c8af4fc` (latency and tokens of 23 Oct calls), `fad8a72f` / `cea94c7c` (Gemini prices), `f4ecc712`
(ThinnestAI Test Chat runs the saved agent), `62444536` / `f50ad0ba` (judge calibration still pending)
and `b932f2c2` (register_eval).

**Probe.** I ran the detectors on reconstructed 26 Nov reply shapes, in Docker on an export of this
tree, with no model calls. The real transcript is only in the prod DB, so these are stand-ins written
from the memory's description. The scripts are `scratchpad/probe04-src/zz_probe04.py` and `zz_probe04b.py`.

**State of the fixes.** Of the 26 Nov fix lanes, only **N (names and phone)** is in this tree
(`e5907ce43`). Lanes **W** (writer and lints) and **P** (in-call prompt and fillers) are NOT in it:
`git log f8bef47a6..HEAD` shows two commits, both from N.

---

## 1. The checks

### 1a. Where each check runs (the pipeline)

The writer and the campaign job: `workers/campaign_script._write`, about line 1240.

1. Draft.
2. `_refined` (D-1031).
3. `_restructured`. Its input is `script_shape.structure_problems` plus `owner_plan.plan_problems`
   (`campaign_script.py:808`).
4. `_shortened`.
5. `_reviewed`, an LLM review pass.
6. `script_proposal.finish_written`. This runs `_mistakes_checked`, which is the targeted repair, at
   most `script_mistake_repair_passes=2` passes (`config.py:1530`). Then `_opening_repaired`.
7. Stored as a draft. The owner reviews it, with any leftovers shown as LeftOut warnings.

Inside each model answer, `script_assist.language_problems` (`script_assist.py:442-547`) and
`drafted_script` (`:631-660`) refuse the answer with an `UnusableAnswerError`, which buys one repair.
Once the repairs are spent, `drafted_with_warnings` keeps the draft and attaches warnings.

The whole job shares `WORKER_JOB_TIMEOUT_S = 300` (`core/queue.py:62`). Each request gets at most
`PROPOSAL_REQUEST_TIMEOUT_S = 50` (`script_proposal.py:62`).

After a save, `script_heal.queue_after_save` queues a repair (`campaigns/workspace.py:244`). Separately,
`sweep_script_heal` runs every hour (`workers/script_heal.py:537`). Both write a `pip_repair` version
and put it live; neither blocks anything.

After every call that has a transcript (test calls included; nothing gates on `trial_call`):

- `pipeline.py:1519-1559` STEP 3c' runs `call_mistakes.mistakes_in`.
- It adds `step_mistakes` and `lookup_mistakes`.
- `record_call_mistakes` stores the rows, opens healer fixes and raises alerts.

**No gate blocks Put it live on a script check.** `agents/readiness.py` imports none of
`script_lint`, `mistake_lints` or `script_heal` (checked with grep). The only api readers are the
healer, `campaigns/diagnose.py` and the writer. So the `mistake_lints.py:14-20` docstring's claim
("on the readiness card and in Put it live as a separate group of warnings") is **not backed by any
`apps/api` caller**. I did not search `apps/web`, so that side is UNKNOWN.

### 1b. The checks, one row each

What each column means:

- **Reads** is the field or fields the check reads. "lines" means `script_lint.agent_lines` (`:1210`):
  the opening and outbound opening, `stages.N.sounds_like`, a `says_instruction` step's instruction,
  sample phrases, the agent side of the example exchange, `stages.N.scripts[lang]` and `qa` answers.
- **Lang** is the languages the rule can actually read.
- **When**: W is writing (it refuses the answer or triggers a repair), R is the targeted repair
  (`_Fix.problems`), H is the heal sweep or save repair, C is after the call, S is the simulator or
  eval, and E is eval only.
- **Effect**: Ref means refuse and repair once, Rep means targeted repair, Warn means a LeftOut
  warning, Row means a `call_mistakes` row plus a healer fix plus an alert, and Score means points in
  a scorecard.

| Check (file:line) | Exact rule | Reads | Lang | When | Effect |
|---|---|---|---|---|---|
| `script_lint._promo` → `compliance.call_purpose.first_finding` | Promo or urgency word list, with negation and everyday-sense guards | lines and instructions | en, te, hi lists | W, eval | Ref, Warn (the launch block is a separate path) |
| `unbacked_promise` (:236) | A WhatsApp, callback, booking or hand-over the manifest cannot do; SMS always | lines and instructions | en plus romanised te negatives | W, C (JOB) | Ref; Row as `unbacked_promise` (JOB_KINDS, but not in LESSONS, so not stored on real calls) |
| `unknown_figure` (:270) | A digit, ₹ or % whose digits appear in no fact | lines | script-neutral (digits) | W | Ref |
| `asks_count` (:310) | `?` count plus `listed_asks` (English "your …, your … and …") > 1 | lines | `?` in any language; list detection English only (`has_indic_letters` returns 0, :300) | W, E | Ref |
| `other_persona` (:321) | "my name is X", where X is not the agent or the business | lines | Latin only | W | Ref |
| `placed_opening_problem` / `name_segment_problem` (:358/:717) | Opening lacks `{{…name}}` or a `?`; or does not read without the name | opening fields | any | W | Ref |
| `stacked_actions` (:388) | ≥2 numbered items, or ≥2 English action verbs (open\|tap\|press…) | `stages.N.instruction` only (:713) | **English only** | W | Ref |
| `unasked_details` (:478) | A collect field that no step asks for | collect plus stems of English words | English stems | W, R | Ref, Rep |
| `flow_problems` (:1501) | placeholder / order / repeated_line / opening_redone / **same_opener** / **same_ending** / unreachable / step_outcome / empty_title / bracket | stages; lines by language group | see the next two rows | W, R, H | Ref, Rep |
| `same_opener_problems` (:1081) | The words before the first mark, ≤3 words, **identical** to an earlier step's line in the same language group | sounds_like, `scripts[lang]` | any (by words) | W, R, H | Ref, Rep |
| `same_ending_problems` (:1158) | The last 3 words identical in ≥3 lines AND ≥half the group (lines of ≥5 words) | sounds_like, `scripts[lang]`, procedure actions | any | W, R, H | Ref, Rep |
| `call_rules.said_line_problem` (call_rules:383) | claims_done, "as I said", honorific >1, **reaction_lead** (not on the close), … | the model's own spoken lines | lists from `call_words.json` | W | Ref |
| `call_rules.reacted_line_problems` (:505) | A `scripts[lang]` line or a procedure action opening with a reaction (`turn_checks.reaction_lead`; the reaction must match `_ACKNOWLEDGEMENT`) | `scripts[lang]`, procedure | words in `call_words.json` | W, R, H | Ref, Rep |
| `spoken_guard.textbook_problem` / `spoken_swapped` | A textbook word from `spoken_style.json`; swapped by code before the repair | lines | per-language list | W, H, C (`formal_words`) | swap, then Ref |
| `spoken_guard.latin_word_problem` (:220) | English letters inside an Indic-script line, apart from names | lines | te, hi | W | Ref |
| `spoken_guard.english_problem` (:343) | An Indic-letter instruction (instructions must be English) | instruction fields | script test | W | Ref |
| `script_assist.way_out_problems` (:593) | No `call_back` exit; no end exit before the last step | stage graph | structure | W | Ref |
| `owner_plan.plan_problems` (:471) | The owner's numbered steps are missing, duplicated or out of order; an outcome or named way-out is missing; call back / end written as a step | step names and branches (parsed with `name_key`) | owner text parsed by structure | W (`drafted_script`), restructure | Ref, then whole restructure |
| `script_shape.structure_problems` (:267) | piled collect, a trailing step after "Finalise the call", a main-task item not covered | stages, English stems | structure; coverage by English stems | restructure pass | Rep (whole), then Warn |
| `script_shape.line_problems` (:422): `several_action_problems` (:307) and `caller_action_claimed_problems` (:318) | `stacked_actions` on a line; "I'll note" in a step that collects nothing | `_english_lines` | **English only** (Indic lines are left to the review pass) | R, H | Rep |
| `script_structure.settled` | Code mends: renumber, reach, empty titles, time taken, wire ways out, drop judged asks and echo branches | stages | structure | before review | mutate |
| `mistake_lints._CHECKS` (:409-429): 19 kinds | Each runs its `turn_checks` detector on the script's lines: brackets, opened_again, same_opening (`same_opener` plus `reacted_line`), same_closing, said_again, too_long (>2 sentences of ≥3 words or >1 `?`), asked_again, reasked_name, caller_line, goodbye_while_asking, false_recall, wrong_language (a wholly-English line), third_person, offered_more_too_soon, false_history, stalled (only a reaction), moved_on_unconfirmed (an outcome with no exit), formal_words, asked_done_too_soon | lines (openings excluded except false_history) plus procedure actions | as their detectors (next rows) | R (`script_mistakes`), H | Rep. Its own docstring says "never blocks" |
| `campaign_script_ask.REVIEW_INSTRUCTION` (:750) | An LLM review with yes/no rubric items: off_task, generic, repeats, missing_task, dead_end, vague, renamed, no_purpose, purpose_repeated, **several_asks (any language)**, wrong_actor, broken_line; plus claims with a word-for-word evidence quote | the parts Pip wrote plus the opening | **any language** (model) | W, after shortening; temperature 0.2; max_tokens 4000 | `Noted` findings join the repair rounds, then Warn |
| `turn_checks.turn_problems` (:760) | Per reply: brackets, symbols (… — / etc.), time, money_digits, formal_words, speaker_labels, caller_line, repeated or several or unmarked question, too_long, wrong_language, foreign_script, spoken_number, no_breath (>10 words without a mark), early_comma, asks_to_tell, … | a live reply | en, te, hi via `call_words.json` | C, S, practice | Row (LESSONS kinds only), Score, practice note or fail |
| `turn_checks.conversation_problems` (:1996) | opened_again (a re-greet, or the opening question asked again), offered_more_too_soon, stalled, picked_for_them, false_recall, invented_source, false_history, presumed_state, stacked_after_who, reasked_name, unbacked_promise, wrong_weekday, unconfirmed_action, partial_number, asked_known_number, goodbye_while_asking, asked_again, said_again, repeated_turn, **same_opening** (`_stock_opener`: one identical opener ≤**2** words in ≥**3** replies), **same_closing** (`_stock_closer`: one identical last-3-words ending in ≥3 replies) | the whole call | as above | C, S, practice | Row, Score |
| `turn_checks.asks_done_too_soon` (:1637) | Last sentence is a yes/no question asking "done?" (`_asks_if_done`, done stems) or naming the instruction's word, after a clause that gives an action (any Indic clause counts as an action) | a reply or line | te (stems), en | C, S, R, H | Row, Rep |
| `SOUND_KINDS` vs `JOB_KINDS` (:149, :193) | SOUND is a note only (it never fails a practice test); JOB fails it | | | | |
| `call_mistakes.LESSONS` (:71-205): 19 kinds stored on real calls | said_again, asked_again, reasked_name, opened_again, caller_line, goodbye_while_asking, false_recall, wrong_language, third_person, offered_more_too_soon, stalled, same_opening, asked_done_too_soon, same_closing, too_long, brackets, formal_words, false_history, moved_on_unconfirmed (from step_progress), missed_lookup | real-call turns; the opening is judged as an opening | | C | Row, healer draft, alerts `call_mistake_seen`, `_new`, `_back` |
| `workers/step_progress` judge | An LLM reads redacted turns; a "reached" step needs a word-for-word caller quote (`quoted_in`); `moved_on_turn` must name an agent line | the transcript plus the script | any (model, Gemini only) | C, S | feeds `moved_on_unconfirmed`, `done_without_signal` |
| `agent_test_ai` judge (practice tests) | Judges the non-rule outcomes; strict schema with the reason first; `judge_leg` avoids grading with the agent's own model family where possible | Test Chat transcripts | any | owner-triggered | verdict and improvement draft |
| `call_words.json` plus console revisions (`ops/call_words_store.py`) | Every Indic word that any check listens for. An emptied entry switches the check off. Patterns rebuild live via `LivePattern` | | te, hi entries; en mostly in code | all | data |

### 1c. Probe results (`zz_probe04*.py`)

These matter because they show what the detectors actually do on Telugu.

1. **`opener()` reads at most 2 words** (`turn_checks.py:1722`). So "చాలా మంచిది అండి" and "చాలా సంతోషం అండి"
   both return None. `_stock_opener` also needs one IDENTICAL opener 3 times. Rotating reactions can
   therefore never fire `same_opening`. On the probe, `same_opener_twice` in the scorecard also
   returned None.
2. **`reaction_lead`** caught "సరే అండి" and "చాలా మంచిది అండి" but **missed "చాలా సంతోషం అండి"**. It is not
   in `_ACKNOWLEDGEMENT`.
3. **`same_closing`** DID fire on three replies ending "అయ్యాక నాకు చెప్తారా" (`_stock_closer`, at
   runtime). `asks_done_too_soon` returned None on every one, because that is an invitation, which
   the rule treats as correct by design.
4. **"Emayyaaka cheppaali"** (Latin-letter Telugu, "say it after what?") was read as `unclear=False`,
   `asks_question=False` and `done_signal=True`. **The Telugu-script "ఏమయ్యాక చెప్పాలి" is not a
   question either** (`asks_question=False`). So `moved_on_unclear` misses the move-on, and the
   scorecard's `done_without_signal` would accept that line as a done signal.
5. **`several_actions`** counts every non-question Indic sentence as an action (`scorecard._actions`).
   So "సరే అండి. ప్లే స్టోర్ ఓపెన్ చేసి … సెర్చ్ చేయండి." gives 2: the reaction plus one sentence that holds
   two actions. It fires for the wrong reason, and two actions inside one Telugu sentence count as 1.
6. **"Hmm... I see."** gives only `symbols` (the ellipsis) and `only_reaction=True`. Both
   `answers_in_english` and `wrong_language` returned None for it, because it is too short.
7. **A re-asked permission question** DOES fire `opened_again` through `asked_opening_again`, both
   word for word and paraphrased ("…ఇప్పుడు సమయం ఉందా?").

---

## 2. The 26 Nov 2026 test call: each failure against the check that would catch it

The source is rememory `d980cc9b` (prod call `01a2176a-…`, 16:03 IST). The stages are W (writing),
H (heal), C (after the call) and S (sim).

| # | Failure | Root cause per `d980cc9b` | Check at W / H | After the call (C) | Sim scorecard (S) |
|---|---|---|---|---|---|
| 1 | Rotating reaction openers "సరే అండి." / "చాలా మంచిది అండి." / "చాలా సంతోషం అండి." | `spoken_style.register_guidance` quotes the te fillers, with "సరే అండి" first. That is in the prompt, not the script | `reacted_line_problems` and `said_line_problem` catch a reaction only if the script line holds it, and "చాలా సంతోషం అండి" is not listed. `same_opener_problems` needs identical openers. **None at W if the lines are clean** | **None**: `same_opening` needs one identical opener of ≤2 words, 3 times | **None** (`same_opener_twice` needs two in a row, identical) |
| 2 | Every turn ends "… అయ్యాక నాకు చెప్తారా?" | PROCEDURE_LEAD, an empty wait_for, the screen bullet and HOW TO SPEAK all say "wait until they say it is done". Our own repair texts tell the writer the same: `mistake_lints._asked_done_too_soon` "end on … an invitation to say when it is done", `script_shape.several_action_problems` "wait until they say it is done", review `wrong_actor` "to say when it is done" | `same_ending_problems` fires only if ≥3 script lines carry the tag. **None if the model adds it on its own** | **`same_closing` YES** (≥3 replies). It is a SOUND kind, so it is a note, not a practice fail; it is in LESSONS, so it is a row and a healer fix, which targets script lines | YES, via `speech_problems` |
| 3 | Several actions per turn | The writer asks for ONE `sounds_like` per stage; the model copies it over the [STEP BY STEP] list | `stacked_actions` / `several_action_problems`: **English only**, and on `instruction` or English lines. The review `several_asks` reads any language, but it is an LLM, nondeterministic and capped by the repair passes | None (no `several_actions` kind in turn_checks) | `several_actions`, but crudely: it counts Indic sentences, not actions (probe item 5) |
| 4 | Asked "done?" too early, or moved on after "Emayyaaka cheppaali" | HOW TO SPEAK: '"OK" after one: the next' | `_asked_done_too_soon` reads only one line, so it cannot see the conversation | `moved_on_unconfirmed` only through the step_progress judge (LLM), and only if the judge marks the move. `asked_again` fired in the probe (the same "…చెప్తారా?" after "సరే") | `moved_on_unclear` **misses**: the line reads as clear and as done (probe item 4). `done_without_signal` would accept it as done |
| 5 | Permission re-asked 3× | The writer's first stage "confirms right person". OPENING_CONTINUES_RULE (D-864) is not enforced in the writer | `opening_redone_problems` reads English instructions (`_REDOES_OPENING`). `opening_redone_line_problems` partly covers Telugu (not verified here) | **`opened_again` YES** (`asked_opening_again` caught a paraphrase in the probe). SOUND kind, LESSONS row | YES |
| 6 | English "Hmm... I see" | Ear acknowledgements with `acknowledgementWords []` (the vendor picks them) and/or thinkingLines | No script cause | `symbols` only (the ellipsis). `wrong_language`: no. Whether ThinnestAI writes an Ear acknowledgement into the transcript is **UNKNOWN** | **Cannot reproduce**: the sim has no Ear and no fillers (`simulate.py:15`) |
| 7 | Wrong name ("Srinivas J") | `trial_calls._tester_name` used the tester's `users.name` | No check reads which name was dialled | None | None. The sim uses the fixture's `contact_name`. Fixed in data by `e5907ce43` (`contact_details.known_name`) |

**What this means.** Even a perfect replay of this call through the sim plus `turn_checks` would flag
#2 and #5, flag #3 crudely, and miss #1, #4 and #6. #7 is a data bug, outside any script gate. A gate
built on today's detectors needs these fixed first:

- `opener` and `_stock_opener`: read up to about 4 words and count the *class* of reaction (any match
  of `_ACKNOWLEDGEMENT`) rather than identical strings.
- `_ACKNOWLEDGEMENT` gets "చాలా సంతోషం అండి" (a `call_words.json` entry, which is the founder's to write).
- Question and confusion detection for Latin-letter Telugu and for "ఏమయ్యాక".
- Count Telugu actions by verb, not by sentence.
- A short-English-reply rule for a te-IN call.

---

## 3. Evaluation assets

### 3a. Simulated calls: `scripts/call_sim/` and `scripts/eval_calls.py`

**How a call runs** (`simulate.py:221-269`). On an outbound call the caller says "Hello."; the agent
says `first_words` (the composed opening); then up to `MAX_CALLER_TURNS = 12` caller turns
(`--turns`, default 12).

- Each turn is the caller model (`CALLER_MAX_TOKENS = 80`), then the agent model. The agent has up to
  `MAX_TOOL_ROUNDS = 2` tool rounds.
- Silence and garbled speech are injected on fixed turns for some personas.
- After the call there is one `read_steps` (the `workers/step_progress` judge's own `request_text` and
  `checked`, `JUDGE_MAX_TOKENS = 3000`).
- Turns are strictly sequential, and **personas run sequentially too** (`eval_calls.live_card`
  `for persona in personas`, `:155`).
- The budget check `--max-inr` (default ₹30, `:61`) runs *between* personas.

**Models.** The agent is `Settings.thinnest_own_model_default`, which is `gemini-3.1-flash-lite`
(`engine.py:1294`, `config.py:518`), on our Google key through the OpenAI-compat leg (`google_ask`).
The caller is the same model unless `--caller-model` is given. Both run with **no temperature and no
`reasoning_effort`** (`simulate.py:79-87`; `chat.complete` adds `reasoning_effort` only when it is
passed, `chat.py:466`). Production calls send thinking minimal or none (VENDOR-STATED, `f4ecc712`,
`9ab1bfa0`), so the sim does not match production thinking.

**The agent's prompt is the real compiled prompt** (`agent.py:72-76`):

- `compose_engine_prompt(cfg)`;
- plus `render_steps(cfg.script_steps)`, a STAND-IN for ThinnestAI's native step merge, which is
  unpublished;
- plus `register_eval.vendor_rules()`, ThinnestAI's speaking rules (VENDOR-STATED,
  `docs/vendor/thinnest-speaking-rules-2026-10-18.md`).

`cfg` comes from `agents/service.campaign_config` / `line_config` for `--holder`, or from a fixture.
`holder_agent(..., script=…)` takes a script override (`agent.py:249-286`, `stored = script or saved`),
which is the hook a draft gate would use.

**Tools.** DNC and callback give canned answers; the knowledge search returns the pinned facts; the
rest return `{"status":"done"}`.

**Personas** (`personas.py:57-170`, 15 of them): cooperative, silent, garbled, not_now,
not_interested, wrong_person (outbound), forgot_registering (outbound), iphone, business_question,
stuck, asks_repeat, english_letters (Latin-transcribed), impatient, asks_ai, remove_me. Against the
requested set:

- **There is no "confused / after what?" persona and no low-literacy persona.**
- busy = `not_now`; wrong person, Latin-transcribed (`english_letters`) and impatient all exist.

**Scoring** (`scorecard.py`):

- It reuses `test_conversations.speech_problems`, which is turn_checks per reply plus the whole call.
- It adds steps_short, moved_on_unconfirmed, moved_on_unclear, asked_known_value, several_actions,
  same_opener_twice, done_without_signal, missed_lookup and not_closed.
- Weights: JOB 15, SOUND 5, STEP 10, `asked_known_value` 10 (`:89-99`).
- The hard-rule-5 kinds `no_ai_answer` and `dnc_not_taken` score the persona 0.
- `script_findings` also runs `script_mistakes` on the script (`:392`).

**AI judge** (`judge.py`): register and naturalness, with evidence quoted before the score and both
orders on a compare. It runs on Azure if configured, else Gemini with an "UNCONTROLLED" note. It is
**UNCALIBRATED**, live-only, and never moves the score or the baseline.

**Recorded mode** (CI): `scripts/fixtures/call_sim/recorded/rytu/*.json`, 15 recordings.
`tests/call_sim_test.py` ratchets on `baseline.json`. Two recordings are evidence-based English
stand-ins: garbled is the 25 Nov 01:37 call and stuck is the 24 Nov 12:15 call. The other 13 are
hand-written (`c20a54dc`). Current recorded score: **1030/1500**
(`docs/evidence/call-sim/2026-11-25-recorded-fixture-rytu.md`).

**Measured cost per live run: UNKNOWN.**

- The ₹18.09 figure for "the lean compare" is in no file under `docs/` or `scripts/` of this tree,
  the main checkout or any worktree (searched with grep), and in no rememory memory (searched with
  several queries).
- `docs/evidence/call-sim/` holds only the recorded report.
- `01d9deb9` says the live A/B was "pending on VPS".
- If the founder has the run output, ₹18.09 is a founder-relayed figure, not yet in the repo.

### 3b. Script-writer eval: `scripts/eval_script_writer.py`

- **Cases** (`tests/fixtures/script_writer_cases/cases/`, 12 of them): bank_app_kyc, clinic_reminder,
  ecommerce_cod, fee_reminder, insurance_renewal, pharmacy_refill, real_estate_followup,
  rytu_khata_install, rytu_khata_owner_steps, school_admission, service_booking and solar_lead. All
  are English inputs.
- **Recorded outputs** are stand-ins: the Rytu script is the 25 Nov production script in English
  stand-in form, and the rest are hand-written fakes.
- **Layers**:
  1. Every repo lint, adopted by name.
  2. The `CHECKS` (`:620-636`): judged_field_asked, known_value_asked, multi_question_line,
     multi_action_line, fake_branch, steps_after_close, no_purpose_line, main_task_uncovered,
     register_in_line, agent_claims_caller_action, outcome_tailored and owner_plan_kept. `READS`
     (`:651`) states honestly that multi_action_line is "English lines only".
  3. An optional naturalness judge.
- **Baseline**: `tests/fixtures/script_writer_cases/baseline.json`.
- **Last report** (`docs/evidence/script-writer-eval/2026-11-25-recorded.md`): 11 cases, a
  deterministic **86.0%**, rytu_khata_install at 56.1%.
- **Live mode** runs draft, refine and `settled`, but *not* the review, the mistake repairs or the
  opening repair (docstring :55-60).
- **No live run is recorded in the repo.**

### 3c. `scripts/register_eval.py` (D-829)

- It composes the real in-call prompt for the Raghava retail starter in te, hi and en.
- It plays 20 code-mixed caller lines × 3 runs each, a single turn, scored by turn_checks.
- It stops at `--max-inr` (default ₹20) and gives 95% intervals on a compare.
- Measured result, from `01d9deb9` and REPORTED: 21 Oct 2026 showed 37% textbook words with the
  SWAPS_LEAD word pairs versus 56% without.
- `price_for` (`:537`) prefers the attested rate and falls back to the catalogue list price, and
  labels which one it used.

### 3d. Owner practice tests: `agent_test_*`, `agents/test_conversations.py`

- They talk to the **live saved agent through ThinnestAI Test Chat**
  (`workers/agent_test_conversations.py:1-25`). So it is the real engine with its real merge.
- `MAX_TURNS = 4` (`test_conversations.py:174`), `TRIALS = 3` (`trial_results.py:42`), and a
  `PAUSE_S = 4.0` pause between messages (`agent_test_conversations.py:131`).
- Hard checks are `hard_check` / `speech_problems`: JOB kinds fail, SOUND kinds are notes. An AI judge
  decides the rest (`agent_test_ai.judge_leg`, which avoids grading with the agent's own model family).
- **"No drafts: Test Chat runs the saved agent"** (VENDOR-STATED, `f4ecc712`). Testing a draft there
  needs a second agent. CLAUDE.md caps customer workspaces at 2 agents on pay-as-you-go; the developer
  workspace allows 100.
- Test Chat on `byok: llm` is ₹0.02 per reply (VENDOR-STATED, `f4ecc712`).
- **Judge calibration** (`scripts/judge_calibration.py`) has been built, but **the founder labels were
  never collected, so agreement is UNKNOWN** (`62444536`, `f50ad0ba`).

### 3e. The in-call model: production against the sim

| | Production | Sim |
|---|---|---|
| Model | `gemini-3.1-flash-lite` on our key, through ThinnestAI (`4c8af4fc`: "the in-call model stays gemini-3.1-flash-lite") | the same id |
| Thinking | minimal or none (vendor) | the model's default, so **it differs** |
| Steps | ThinnestAI's native step merge | `render_steps` text |
| Ear, acknowledgements, fillers, STT errors | present | **absent** |

---

## 4. Feasibility of a "simulated call before the owner sees the draft" gate

### 4a. What can be reused as it is

- `scripts/call_sim/agent.holder_agent(spec, script=draft)` builds the real compiled prompt for a
  draft on a holder's publish config.
- `simulate.simulate`, `read_steps` and `Spend`/`price`.
- `scorecard.score_recording`, `test_conversations.speech_problems` and `turn_checks`.
- The 15 personas.
- The `script_proposal._Fix` plus `_fixed_further` repair loop, which accepts a custom `check`
  (`script_proposal.py:252`), so sim findings could feed the same targeted repair.
- `campaign_script_ask.quoted_in`-style evidence checking for a judge.
- The `judge.py` rubric.
- Metering: `meter_assist` and `ASSIST_FEATURE_*`.

### 4b. What is missing

1. The sim lives in `scripts/`, which is not a worker. It needs moving into `apps/workers` with ARQ
   job registration, metering under hard rule 7, quota gating and D-127 handling. Personas carry no
   PII, but the draft does.
2. A separate job after `finish_written`, or in parallel with it. Today's campaign job already chains
   draft, refine, restructure, shorten, review, 2 repairs and the opening repairs inside 300 s.
3. Parallel personas, since `live_card` runs them in sequence.
4. Personas for confused/"after what?", low-literacy and wrong-name, plus a te-IN Latin-letter variant
   of each.
5. The detector fixes from section 2. Without them the gate misses the founder's top complaint, #1.
6. A pass threshold plus N repetitions per persona. There is no temperature, so outputs vary (register
   eval uses 3 runs plus intervals).
7. A mapping from a sim finding (kind, turn) back to a script path for the repair. `mistake_lints`
   does this for script-caused kinds, but prompt-caused kinds such as #1, #2 and #4 have no script
   path. **That is the main design gap: the gate would find faults the script repair cannot fix.**
8. Sending `reasoning_effort` "minimal" in the sim, to match production.

### 4c. Cost (ESTIMATE)

The basis:

- Production input tokens per call are 35k-57k over 6-8 turns, about 5.9-8.4k per turn (`4c8af4fc`,
  measured on 9 prod calls, 23 Oct).
- gemini-3.1-flash-lite costs $0.25/M input and $1.50/M output (Google pricing pages read 15 and
  27 Oct; REPORTED in `cea94c7c` / `fad8a72f`, not re-read this session).
- The exchange rate is ₹95/$ (D-768).

The per-persona sum at 12 turns:

- The agent side is about 12 × 7k = 84k input, roughly ₹2.0.
- The caller side is about 12 × 1-2k, roughly ₹0.3-0.6.
- The step judge, one call of about 5-8k, is roughly ₹0.15.
- Output is about 12 × ~150 tokens, roughly ₹0.25.

| Run | ESTIMATE, uncached |
|---|---|
| One persona | **about ₹2.5-3** |
| 6 personas × 1 run | about ₹15-18 |
| 6 personas × 3 runs (for stability) | about ₹45-55 per draft |
| An optional cross-family judge | not estimable here (UNKNOWN Azure rate) |

`DEFAULT_MAX_INR = ₹30` for 15 personas is a budget, not a measurement.

### 4d. Latency (ESTIMATE)

The basis:

- The production model share of a reply has a median of 0.93-1.15 s (`4c8af4fc`).
- The caller-model latency is UNMEASURED; I assumed it matches the agent.
- Tool rounds add about 1 s each.

Per persona, 12 sequential turns × about 2-2.5 s (agent plus caller) plus the judge comes to about
**25-40 s**. If 6 personas run in parallel, that is still **about 30-45 s per draft**, before repair
rounds. Each repair round adds a writer pass (up to 50 s) plus a re-simulation. Sequential, as the code
runs today, it is about 3-4 min. Google rate limits for our project are UNKNOWN.

### 4e. Risks

1. **Fidelity.** The sim is not ThinnestAI: no Ear, acknowledgements, fillers, STT or native step
   merge, and different thinking. Failure #6 cannot appear. A green sim can still give a bad call,
   which `d980cc9b` #1 and #6 show.
2. **The detectors are blind to Telugu shapes** (section 1c). The gate would pass the 26 Nov call on
   #1 and #4.
3. **Judge reliability.** Every judge is UNCALIBRATED. The practice judge's agreement is UNKNOWN, and
   the sim judge is same-family Gemini unless Azure is configured. The step_progress judge decides
   `moved_on_unconfirmed`. A false block costs the owner a draft, and the mistake_lints doctrine
   (`mistake_lints.py:18-20`) is that "a line that MAY cause a mistake must never cost the owner a
   whole draft".
4. **Flakiness.** No temperature plus 12-turn compounding means a single run can flip a verdict, so N
   runs multiply cost.
5. **Unfixable findings.** The prompt-caused kinds (#1, #2, #4) need platform-prompt changes (lane P),
   not script repair. A per-draft gate would loop or warn without ever fixing them. They fit better as
   a **CI or release gate on platform-prompt changes**: `eval_calls --live --compare` on the VPS, with
   the recorded ratchet in CI.
6. **Cost and quota.** About ₹15-55 per draft against a Pip allowance. Who pays (absorbed, or metered
   to the client) is a founder decision.
7. **Time budget.** It cannot fit in the existing 300 s job.

**Recommendation** (a judgement, not a measurement):

1. First fix the detectors (section 2).
2. Run the sim as a platform-prompt release gate, with fixtures recorded from real te-IN calls.
3. For drafts, run a cheap async sim (3 personas × 1 run, about ₹8 ESTIMATE) after the draft is
   stored. Show the findings as warnings, and send script-caused kinds through the existing `_Fix`
   repair. Do not block the owner's review until the judges have been calibrated against labels.
