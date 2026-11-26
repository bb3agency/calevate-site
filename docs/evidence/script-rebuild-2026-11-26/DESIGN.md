# How scripts are made: the rebuild (26 Nov 2026)

Founder, 26 Nov 2026, after the Rytu Khata test call at 16:03 IST: "fix how scripts are made… proper
research, don't assume anything, map everything, then build everything end to end". Founder on the
same day: the in-call model copying what we show it is "the most informative thing" and should be
turned into an advantage. That makes this rebuild example-led.

Evidence, in this folder:

- `01-write-paths.md`: every path that creates or changes a script, measured prompt sizes, and the
  rules that conflict.
- `02-in-call-compilation.md`: what the in-call model reads on every turn, rendered from a real
  script.
- `03-external-research.md`: vendor guides and published research, every source cited.
- `04-checks-and-evals.md`: every check, what it catches, and the simulated-call gate.

Rememory: d980cc9b (the call), d9155474 (founder direction).

## 1. What is wrong, in one page

1. **18 paths write a script, and each applies its own subset of rules** (01 §1–2).
   - Only the main writer runs the full set, and only on lines Pip itself wrote.
   - The repair pass runs a subset. Owner save and Keep check only length. Practice-test fixes use
     their own prompt with about 3 checks.
   - Since 21 Nov every quality fix landed in the writer and nowhere else (01 §6).
   - There are 5 parsers, at least 6 ways to apply changes, at least 6 repair loops and 2 version
     stores (01 §7).
2. **One model pass writes a whole script against a huge, self-contradicting rulebook.**
   - A first script sends 32–72k characters per request and about 150–190k before any repair round
     (01 §4).
   - At least 14 rules conflict (01 §5). Examples:
     - "the example line stays empty" against a check that refuses an empty one;
     - "never write about call backs" against rules that require them;
     - the playbook's "check it is a good time" step against three rules forbidding it.
   - Published research: models follow long instruction lists less reliably, and favour what comes
     early (03 §2).
   - Planning, then writing each part, then checking against something outside the writer beats a
     single pass (03 §2, Re3; self-correction alone fails, Huang 2024).
3. **The in-call model copies what the prompt shows, and the prompt shows it bad lines** (02).
   - On every turn it reads about 21k characters, with all the steps at once. ThinnestAI pastes the
     steps inside our instructions and has no field for examples.
   - The only Telugu inside a step is "It sounds like". 6 of the 8 lines open with a reaction, and
     several bundle two actions.
   - The filler list, the style examples and "[EXAMPLE CALL] Copy the style" all show reaction
     openings or "tell me when it's done" endings.
   - Research and vendor guides agree that examples outweigh rules, and that the model copies sample
     phrases closely unless they are varied (03 §5).
4. **Our checks would not have stopped the 16:03 call** (04).
   - Only 2 of its 7 failures are caught, both after a call. Nothing blocks "Put it live".
   - Most detectors are English-only, or read only the English instruction.
   - Three of our own repair messages tell the writer to end a turn with "say when it is done".
5. **Repairs lose context** (01 §3).
   - A repair rebuilds its brief without the call direction, grounding, the owner's plan, the
     fields to collect, or the language.
   - The healer's check and the heal pass judge differently, so a fix can run out of attempts.
6. **The 25 Nov "Pip rewrites every script it owns" pass** (01 P5, `campaign_script.py:358-406`):
   - it saves drafts that still carry warnings, then deletes those warnings;
   - it never puts the result live, although it says it does;
   - it treats a script the owner reviewed and kept as Pip's own, and rewrites it.

## 2. Principles

1. **Code decides structure; the model writes words.**
   - Code fixes the steps, their order, outcomes, ways out, side steps and what each step must
     collect. The sources are the owner's step plan, the plan read from the main task, or the trade
     playbook. This already exists as `owner_plan`.
   - The model never re-plans.
2. **One step at a time, with a short brief.**
   - Each step is written by its own small request: about 2–4k characters, holding only what that
     step needs.
   - Steps are written in parallel.
   - A step that fails its checks is rewritten alone.
3. **Show it, don't tell it (example-led).**
   - Each step carries at least 3 varied example turns in the call's language. Each turn is one
     action, with no reaction at the start and no "tell me when it's done" at the end.
   - Each step also carries example turns for the hard moments: a confused caller ("after what?"),
     a busy one, and one stuck on the action.
   - Examples replace rules. They are good examples only, never a "don't say" list (03 §5).
   - Every example passes the same checks as the script, because examples outweigh rules.
4. **One set of checks, everywhere.**
   - There is one language-aware check registry, with detection words in `call_words.json`.
   - The same checks run with the same severity on every path: write, repair, heal, owner save,
     Keep, Put it live, and after a call.
5. **One writing path.**
   - Every entry point builds one request: first draft, Pip ask, part or flow ask, rewrite, heal,
     mistake fix, practice-test fix, first run.
   - Context is always loaded by one loader, so no request is written without the call direction,
     grounding, plan, fields to collect or language.
6. **A rehearsal before the owner sees a draft.** Simulated calls run through the REAL compiled
   prompt, with these callers:
   - cooperative;
   - confused, typing Telugu in Latin letters ("after what?");
   - busy;
   - stuck on an action;
   - wrong person.
   - Findings the script caused go back to rewrite that step. Findings the prompt caused are reported
     as platform issues.
   - The rehearsal starts as warnings. It blocks only after its judgements are checked against the
     founder's labels (04 §3; vendor practice is a pass rate over repeated runs, 03 §4).
7. **Fewer rules in the call prompt.**
   - HOW TO SPEAK keeps only what an example cannot show: numbers and amounts, reading back,
     language switching, the truthful answers (hard rule 5), confidentiality, and the rules about
     tools.
   - About 3.5–4k characters of rules are replaced by per-step examples, with about 10.5–11k
     characters of room overall (02 addendum c, an ESTIMATE).

## 3. The design

### 3.1 Structure (code): `ScriptPlan`

- `apps/api/agents/script_plan.py` builds a `ScriptPlan`.
  - **Steps:** each has a name, an outcome, an English intent, ways out, side steps and the fields
    to collect.
  - **Order:** fixed by code.
  - **Sources, in order:** the owner's plan from the request, then the plan read from the main task
    (`owner_plan` with `task_steps`), then the trade playbook's steps, then a model-proposed outline
    for a free-form request. The outline is checked by code before any words are written.
- Deterministic rules move out of the prompt and into code:
  - renumbering;
  - side steps placed as scenarios of the step after the one that reaches them;
  - call back and end call kept as end points only;
  - the required ways out;
  - the first step never asks again whether now is a good time.

### 3.2 Words (model, per step): `StepWriter`

- **The request.** Each step gets one request, holding:
  - the step's plan entry;
  - the business facts relevant to the step, with the grounding sources it needs;
  - the language and register (a short register note, not the whole spoken-style file);
  - the opening line, so the step never repeats it;
  - the previous step's intent.
- **The answer** (strict JSON schema):
  - an English `instruction` of one or two sentences;
  - `procedure` actions, one action each, with `wait_for` meaning what the caller says or sees once
    the action is done;
  - per language, `examples`: 3 to 5 normal turns, one confused turn, one stuck turn, and a busy
    turn on the first step;
  - optional `qa`.
- **No "sounds_like" line.** It is replaced by the examples, and an old `sounds_like` is migrated
  into the first example.
- **The opening and the close** get the same small-request treatment.
- **Each step is checked as soon as it is written.**
  - The checks are:
    - one action;
    - no reaction at the start;
    - no request to say when it's done;
    - no repeated endings across steps;
    - no permission asked again;
    - correct language and script;
    - no textbook words;
    - no brackets or symbols;
    - length.
  - A failing step is rewritten up to 2 times, with the exact problems listed.
  - Whatever still fails becomes a warning on that step.
- **Spend.** Requests are metered and run in parallel, within the job's time limit.

### 3.3 One writing path: `write_script(request)`

- **Modes:**
  - `whole`: build the plan, then write every step;
  - `steps(ids)`: rewrite those steps, keeping the rest;
  - `lines(paths)`: targeted line repair, still through the step writer;
  - `outcomes`;
  - `opening`;
  - `notices`.
- **Callers move onto it:**
  - the campaign and line writer (P1–P4);
  - the rewrite (P5);
  - first run (P6);
  - the heal and mistake repairs (P8 and P9);
  - step outcomes (P10);
  - practice-test fixes (P13).
  - The notice weave (P11 and P12) and company training (P16) keep their own prompts, but run the
    shared checks.
- **One loader, `script_context(holder)`,** gathers direction, grounding, owner and task plan,
  fields to collect, languages, the opening and the business facts, for every mode.
- **One parser** turns the model's answer into a `CallScript`, and one applier lays a change onto a
  script. The duplicate parsers and appliers are deleted, not kept beside the new ones.

### 3.4 One check registry: `script_checks`

- `script_lint`, `mistake_lints`, `script_shape`, `turn_checks` (the per-line half) and
  `owner_plan.plan_problems` are folded behind one registry.
- **Every check is defined once,** with:
  - its id;
  - the fields it reads (`instruction`, `procedure`, `examples[lang]`, `opening`, `qa`);
  - its languages;
  - its detector (`call_words.json` patterns, per language and script);
  - its severity (block or warn);
  - its repair message, written in the new form: "give one action and stop", never "ask them to
    say when it's done".
- **The same registry runs on every path:**
  - writing and repair;
  - heal;
  - owner save and Keep, as warnings;
  - Put it live, where block-level checks refuse;
  - the after-call `turn_checks`, which uses the same detectors on the agent's real turns.
- **Lane W's 26 Nov checks become the first entries.** They cover:
  - requests to say when it's done;
  - shared endings;
  - rotating reaction openings;
  - several actions in one line, by per-language verbs;
  - confusion read as a question, in both scripts;
  - permission asked again.

### 3.5 Compile (what the in-call model reads)

- **Per step, in the instructions:**
  - a short header and the step's English intent;
  - the action list, each action with the evidence that it is done;
  - then `Examples (vary your words; never repeat a turn):` followed by tagged example turns, with
    their order rotated per publish.
  - The native ThinnestAI step `detail` keeps the intent and the actions, within the 600-character
    limit.
  - The native `collect` field carries the step's exit evidence, not CRM fields. This is done only
    if ThinnestAI confirms it uses `collect` that way; until then it stays as it is.
- **Removed from the prompt:**
  - the "It sounds like" bundle;
  - the register's filler list and its booking examples. The reviewed `spoken_style.json` is NOT
    edited; we only stop quoting it.
  - "[EXAMPLE CALL] Copy the style";
  - the duplicate opening line with its bracket placeholder.
- **HOW TO SPEAK is trimmed** to the rules in principle 7. The one-action and "only their own 'done'
  moves on" rules stay, because examples show them but do not enforce them.

### 3.6 Rehearsal: `script_rehearsal` worker job

- **What it reuses:** `scripts/call_sim` (`holder_agent(..., script=draft)` accepts a draft), moved
  into an ARQ job of its own. It does not share the writer's 300-second job.
- **Callers:** 5 types, run in parallel, about 10 to 12 turns each.
- **Scoring:**
  - the deterministic checks from the registry, on the agent's turns;
  - the step-progress reader: did it move on before "done";
  - one judge question per call: did it reach the step outcomes.
- **Cost:** about ₹8–18 per run of 3 to 6 callers. This is an ESTIMATE from the 23 Oct token counts
  (04 §3). The first real run measures it, and a console setting caps it.
- **Results:**
  - they appear on the review card as "In a practice call, …";
  - a script-caused finding queues `write_script(steps(ids))` once;
  - a prompt-caused finding raises an operator alert.
- **It also gates prompt releases:** any change to the shared call prompt runs the rehearsal on
  fixture scripts before release. This is a script plus a CI target.

### 3.7 Examples that improve over time

- **On a call page,** an owner or operator can mark an agent turn as "good". It is redacted, stored
  per agent and language, and offered to the step writer as an example for that kind of step.
- **Nothing is mined automatically** (03 §5: no vendor documents it, and prompt data can leak).
  Marked turns are versioned and removable.

## 4. What changes for existing scripts

- **Scripts already saved keep working.** The compiler reads both the old `sounds_like` and the new
  `examples` fields.
- **A one-time migration job** re-writes each holder's steps through `write_script`, as a DRAFT the
  owner reviews. It never auto-saves.
- **The 25 Nov auto-rewrite (P5) stops now.** It saves without review and it touches scripts the
  owner kept. It is replaced by that reviewed migration (founder decision, §6).

## 5. Build plan

Parallel lanes, each owning its own files. They start after lanes W and P land.

| Lane | Owns | Depends on |
|---|---|---|
| R1 Structure + one path | `script_plan.py`, `write_script`, `script_context`, one parser, one applier; the callers moved over (P1–P10, P13) | — |
| R2 Step writer | the per-step prompts and schema, the examples fields in `CallScript` (shared), migrating `sounds_like` | R1 interfaces (agreed first as a typed contract) |
| R3 Check registry | `script_checks` and moving the existing checks into it; severity on save, Keep and Put it live; the after-call reuse | — |
| R4 Compile | the `call_script` and `engine` compile of examples; trimming HOW TO SPEAK; the budget tests | R2 schema |
| R5 Rehearsal | the `script_rehearsal` job, the callers, scoring, the review card, the prompt-release gate | R3, R4 |
| R6 Web | the review card: per-step examples (editable), warnings, rehearsal results, "mark as good example" | R2, R5 |

Every lane gets tests. One more is required before release: the eval set gains Telugu and Hindi
guided-call cases, and the rehearsal scorecard on fixture scripts must beat today's scorecard.

## 6. Decisions for the founder

1. **Stop the 25 Nov auto-rewrite now.** (Recommended.) It saves unreviewed drafts that still carry
   warnings, and it rewrites scripts the owner kept.
2. **The rehearsal warns, and does not block,** until its judgements match the founder's labels on
   about 20 calls. (Recommended.)
3. **Examples are written by the writer.** They are checked, then shown on the draft for the owner
   to keep or edit, like any other line. The founder's reviewed style list is never edited.
4. **Ear acknowledgement words in the call's language.** Lane P sends reviewed lines from the style
   list. This is the feature deferred on 23 Oct.

## 7. Questions for ThinnestAI

1. Does the engine track which step the call is on, or does the model see all the steps every
   turn? Is `collect` enforced as exit evidence?
2. What does the ~4.7k-character wrapper say about examples and steps?
3. Does `callInstructions` replace the separate speaking rules?
4. Thinking lines and acknowledgements on a caller transcribed in Latin letters: which language is
   the fallback?
5. The three dial questions from the outage work (rememory 8a865710).
