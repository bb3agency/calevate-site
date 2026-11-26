# 01: Every path that creates or changes a call script

Calevate, `feat/agent-four-tabs` at `b5613a0b3`, worktree `D:\Agency\calevate\.claude\worktrees\agent-tabs`. This was read-only: no repo file was edited.

## How this was produced, and how much to trust each part

**How the work was split.** Four read-only research lanes each read one cluster of files in full:
- the campaign and line writer;
- `script_assist` and Pip's entry points;
- heal, mistakes and lints;
- openings, step outcomes, first run, starters, owner plan and training.

The lead then:
- re-checked the highest-impact claims at source (marked **[re-verified]**);
- measured the prompt sizes in Docker (section 4);
- read the git history (section 6).

**How far to trust the rest.** Every other `file:line` comes from a lane reading the code at this HEAD, not from memory. Anything nobody could verify is marked **UNKNOWN**, with the reason.

**Memories used as pointers only.** These were checked against the code:

| Memory | What it covers | State |
|---|---|---|
| d95ec1ab | 25 Nov writer fixes and the Pip rewrite | **Stale on one point:** it says `heal-4`, the code says `CHECKS_VERSION = "heal-5"` (`apps/api/agents/script_heal.py:66`) **[re-verified]** |
| 1d6ff902 | D-1031 refine | |
| 8a49f9d4 | `finish_written` | flagged SUSPECT by rememory: the files changed since |
| c6646953 | D-1004 asks | |
| bb5886b0 | repair rounds and the Sarvam standby | |
| 0d8ab716 | D-1038 script_heal | |
| 75d45c47 | D-1017 practice-test fixes | |
| c48fe5eb | retired agent `/script` routes | |
| 40b86511 | D-992..994 campaign workspace | SUSPECT |
| 7f9ef306 | the four-tab model | |
| f401ec53 | D-1034 company training | |
| c88d93c0 | D-1036 step outcomes | |
| 7f0ea46f, 8ba43b11 | D-971 | |
| 395cf7a5 | owner plan | |

**Size figures.** All character counts in section 4 are runtime `len()` values from Docker (`ghcr.io/astral-sh/uv:python3.12-bookworm-slim` with the `calevate-test-venv-ct` venv, run on an exported copy of the tree). The script is at `C:\Users\jumes\AppData\Local\Temp\claude\a50a3f0a872c1724\0c51a750-0b23-4950-961e-84972febca40\scratchpad\measure\m.py`. Sizes are characters, not tokens.

---

## 0. The shared engine every model-written path goes through

### The ladder: `ask_json` (`apps/workers/script_assist.py:2036-2271`)

**Leg 1, the paid leg.** It is `account_assist_leg(session)` (`apps/api/agents/assist_leg.py:49-98`):
- the account's Gemini, where it serves; else `google_assist_leg()` = `copilot_fast_model`, default `gemini-3.1-flash-lite` (`packages/shared/src/calevate_shared/engine.py:1281`); else Azure `gpt-4o-mini`;
- no script path uses `background_leg`.

**Repair rounds** on the same leg:
- The default is `repair_rounds=1` (`:2050`).
- The note is `REPAIR_NOTE` (156 chars) or `TARGETED_REPAIR_NOTE` (343) for edits; `SHAPE_PROBLEM` (291) when the parse crashed.
- A targeted answer is merged by step id (`merged_repair`, `:1921-1950`).

**Then `salvage`, then the Sarvam standby.** The standby is `sarvam-105b`, `max_tokens` capped at 4096 (`:2232-2243`), asked once with no repair and read leniently.
- `standby_after_answer=False` stops the standby only after a paid answer that came back unusable (`:2211-2215`).
- A truncated or non-JSON paid answer still falls through to Sarvam (`:2155-2161`, `:2232`). That is from reading the code; nobody has seen it happen.

**Defaults:**
- `max_tokens=4096` (`_DRAFT_MAX_TOKENS`, `:1036`);
- `temperature=0.4` (`:2045`), but no temperature at all is sent to Gemini 3 models (`:1621-1622`; `engine.py:1662-1670`). On the default leg, therefore, every "temperature" below is ignored and Google's default applies;
- `timeout_s=ASSIST_TIMEOUT_S=15` per request (`apps/workers/extraction.py:268`), with `ASSIST_LADDER_LEGS=3` budgets (`:274`).

**Job overrides:** `PROPOSAL_REQUEST_TIMEOUT_S=50` (`apps/workers/script_proposal.py:62`), `PROPOSAL_MAX_TOKENS=16_384` (`:69`). The job ceiling is `WORKER_JOB_TIMEOUT_S=300` (`apps/api/core/queue.py:62`).

### `draft_script` (`script_assist.py:2274-2412`)

**A new script:**
- System: `_SYSTEM_INSTRUCTION`.
- User: `ScriptBrief.user_message()` + "In the owner's words: <description>".
- Then `playbook_guidance(...)` is appended **when there is no owner plan** (`:2363-2370`).
- Strict json_schema `calevate_script_draft` (`_DRAFT_SCHEMA`, `:1060-1107`).
- Parser: `drafted_script` → `_script_from_model_json` (`:627-663`, `:1397-1506`).
- Repair rounds: 1 unless overridden.
- Standby after an answer: True unless overridden.

**An edit** (`edit_of=`):
- System: `EDIT_INSTRUCTION`.
- User: user_message + "The owner's change: <change>" + "Current script (JSON):" + the script JSON (`:2321-2326`) **[re-verified]**.
- Format: json_object.
- Parser: `salvaged_edit` (`:832-938`), strict first, then lenient. The lenient read puts back the parts that break a rule, and they become `left_out` warnings.
- Rounds: `script_edit_repair_rounds` (default 2, `packages/shared/src/calevate_shared/config.py:1533`).
- Standby: False.

**There is no `edit()` function.** An edit is `draft_script(edit_of=…)`.

### Checks inside the parse (`language_problems`, `:442-548`)

While repair rounds remain, these **block and repair**. A lenient edit puts the part back instead. Only problems Pip introduced count (`before=`).

**Spoken lines:**
- `english_problem`, `instruction_problems`
- `textbook_problem`, `provider_problem` (D-679), `said_line_problem`, `latin_word_problem`
- `introduced_opening_problem`, `retired_line_problem`
- `spoken_line_problems`, `woven_notice_problems`, `placed_opening_problems`

**Shape** (`shape_problems`, `:551-583`):
- `flow_problems`, `opening_redone_line_problems`, `reacted_line_problems`;
- a guide stage with an empty `sounds_like` (`:569-574`) **[re-verified]**;
- a close removed in an edit.

**Ways out:** `way_out_problems` (`:603-624`), only when `places_calls`.

**Owner plan:** `plan_problems` (`apps/api/agents/owner_plan.py:471-621`), when a plan is present.

**Fixed by code, no repair needed:**
- `with_spoken_swaps`, `with_owner_plan`, `without_echo_ways` (`:1506`)
- `ways_to_kept_steps`, `without_placeholder_steps`
- the outbound opening blanked unless the agent is `both`

### Dead or never-filled code (do not rebuild around it)

- `CONVERT_INSTRUCTION` (`:311`), `edited_script` (`:705`) and `_draft_via_azure` / `_draft_via_sarvam` (`:1787-1810`) are reached only by tests.
- `ScriptBrief.answers` is never filled (`campaign_script.py:150` passes `{}`).
- The agent-level proposal job is retired (`apps/api/agents/script_proposals.py:10-11`, D-1005).
- `script_lint.script_problems` (`:568`) has **no production caller**: only `scripts/eval_script_writer.py:738`. Its readiness-card caller is gone.

---

## 1. The paths, one by one

Every path that writes a script, found by a grep of `save_script(`, `script_history.record(`, `UPDATE … script` and `insert_prompt_version`:

| # | Path | Model? | Writes to |
|---|---|---|---|
| P1 | Campaign first script (Generate on an empty campaign; first run; Pip `script_draft`) | yes | `campaigns.script_proposal` (draft) |
| P2 | Line first script | yes | `inbound_lines.script_proposal` |
| P3 | Generate again / "Ask Pip to change it" (tone, instruction; owner steps) on an existing script | yes | proposal |
| P4 | Part ask (`PART_ASK`) and flow ask (`FLOW_ASK`), campaign only | yes | proposal |
| P5 | The 25 Nov Pip rewrite (`_ask_rewrite` → writer → `_save_if_rewrite`) | yes | **`script` itself**, with no review |
| P6 | First-run `auto_save` (`_save_if_asked`) / ready-made fallback | yes / no | `script` itself |
| P7 | Owner manual save (PUT script) and Keep (keep-live) | no | `script` + `script_versions` |
| P8 | script_heal line repair (`repair_holder_script`) | yes | `script` itself (CAS) |
| P9 | mistake_fix (healer playbook) | no; it queues P8 | fix rows only |
| P10 | Step-outcomes writer (`write_step_outcomes`) | yes | `script` (CAS) + `step_outcomes_pip` |
| P11 | Notice weave, holder (`weave_holder_opening_notices`) | yes | `script` via `save_script` |
| P12 | Notice weave, agent (`weave_opening_notices`) | yes | `prompt_versions` (agent level) |
| P13 | Practice-test fixes (`improve_agent_test_run` → `test_fixes.write_holder_draft`) | yes (own prompt) | holder `script_proposal` |
| P14 | Starters: `apply_starter`, `replace_unedited_starter`, `ready_made_script` | no | `prompt_versions` / holder |
| P15 | Agent-level opening line: `PUT /opening-line`, `/put-back`, admin `write_prompt_version`, `/apply`, `/undo`, `rollback_prompt` | no | `prompt_versions` |
| P16 | Company training (`draft_company_training`; owner PUT `/training`) | yes / no | `company_trainings.training` (composed into every call) |
| P17 | Starter step plans (`write_starter_steps`) | yes | `organizations.starter_plans` (feeds P1/P2 via the playbook) |
| P18 | Minor `system` writers: first-run rename, `campaigns/improve.py:236,279,361`, `engine_retirement.py:220`, `copy_workspace` (`copied`), `restore_version` (`restored`), `create_line` (`owner`) | no | `script` + `script_versions` |

### P1 / P2 / P3 / P4: the holder writer (`apps/workers/campaign_script.py`)

#### Trigger

- Every enqueue goes through the outbox:
  - `workspace.request_proposal` (`apps/api/campaigns/workspace.py:415-487`), job `draft_campaign_script`;
  - `lines.request_proposal` (`apps/api/inbound/lines.py:426-485`), job `draft_line_script`.
  - Both are registered at `apps/workers/settings.py:484-485`.
- Callers:
  - the campaign route `POST /{id}/script/proposal` (`workspace_routes.py:687-739`; gates `assert_view_as_may` + `require_ai_assist`; audit `campaign.script_requested`);
  - the line route (`inbound/routes.py:615-653`);
  - Pip's `script_draft` tool `_execute_draft` (`apps/api/copilot/script_actions.py:528-560`). It runs `require_ai_assist`; `assert_view_as_may` is **UNKNOWN** (not in this function);
  - the first run (`apps/api/first_run/work.py:317-323`, `:352-358`, `auto_save=True`);
  - the P5 rewrite.
- A second request while one is drafting gets a 409 (`workspace.py:450-455`, `lines.py:452-457`).

#### Inputs

These are read when the job runs, not when it was asked for (D-1031). The sources are `campaign_inputs` (`campaign_script.py:584-660`) **[re-verified]** and `line_inputs` (`:663-720`):
- `main_task`;
- `knowledge_words(only=sources or None)`: none picked means all knowledge;
- `settings_overrides.language_primary`, `focus`, `ask` (tone, instruction), `name`, `purpose`, `goal`, `consent_source`;
- `campaign_details().placed()` (the name ask is dropped);
- `brief_for(...)` with `direction="outbound"` and `collect`;
- the account leg and quota;
- `base` = `proposal.base_script` (None for P5);
- `budget` (the engine box × 0.85);
- `situation_block`.

The documents are `documents_block(words, budget=KNOWLEDGE_DOCUMENT_CHARS)`, where `KNOWLEDGE_DOCUMENT_CHARS = 40000` (`apps/api/first_run/models.py:69`) **[re-verified]**.

#### How the ask is composed

`campaign_change` (`apps/workers/campaign_script_ask.py:676-714`) **[re-verified]** builds it in this order:
1. lead: `ask` + `REFINE_TAIL` | `EDIT_TAIL` | "" (or `part_ask` alone)
2. `TONE:`
3. `THE OWNER ASKS:`
4. `LENGTH:`
5. `MAIN TASK:`
6. `owner_plan_block` (`PLAN_HEAD` + plan + `PLAN_RULE`), or `items_block`
7. `situation`
8. notes (always "")
9. documents
10. `TASK_REMINDER` (not for a part ask)

#### The passes inside `_write` (`campaign_script.py:1144-1354`)

**1. Task-plan reading, `_task_plan` (`:1092-1131`).** Runs only for a first or whole script with no owner plan, when the main task has numbered items. Added 26 Nov in `a23ff08ca`.
- Call: `ask_json(TASK_STEPS_INSTRUCTION (954 chars), max_tokens 1500, temp 0.2, timeout _late_timeout)`.
- The standby is allowed.
- The reading is used only if `owner_plan(answer)` keeps exactly one step per item; otherwise it is only logged.
- Metered at once.

**2. Draft (`:1198-1252`).**
- A whole script: `draft_script(replace(context, description=asked, grounding=change, placed_calls=campaign, owner_plan=plan))`. An existing script (P3): `edit_of=base, change=asked`.
- Settings: 50 s, 16,384 tokens, `campaign_script_repair_rounds` (default 2, `config.py:1536`), `standby_after_answer=False`, `owners_words`.
- `keep_with_warnings` is set on attempt ≥3 or when less than 240 s is left.
- Retried up to `WRITE_ATTEMPTS=3` (`:158`) with `retry_change` (`:176-196`) on `assist_answer_unusable`, when not truncated and at least 120 s is left.
- After that it **blocks** (`_fail`, `:453-468`).

**3. Refine, `_refined` (`:743-793`).** Whole scripts only (D-1031). It is an edit of Pip's own first draft, with the ask `CAMPAIGN_ASK + REFINE_TAIL`. A refusal or crash keeps the first draft.

**4. Restructure, `_restructured` (`:842-897`).**
- Runs when `built_wrong` (`:796-812`) finds anything Pip introduced:
  - first code mends a probe copy: `without_judged_asks` + `collected`;
  - then it counts `plan_problems` + `script_shape.structure_problems`.
- It is one edit (`RESTRUCTURE_TAIL` + the problems), run once.
- What is left becomes `built_wrong_left` **warnings**.
- Not run for a part ask.
- **Composition bug:** `EDIT_TAIL` begins with a space and is appended after the last `- problem` bullet (`campaign_script_ask.py:357`, `:697-698`).

**5. Shorten, `_shortened` (`:900-933`).**
- Runs only if `compiled_preview(...).size` does not fit.
- It is one edit with `SHORTEN_ASK`, `repair_rounds=1`. The openings are put back by code (`_openings_of`).
- If the script is still long: a `too_long_left` **warning**.
- **No `except Exception`**, unlike refine and restructure. A crash would leave earlier spends unmetered (PLAUSIBLE, not executed).
- **Measurement mismatch:** this pass measures the **agent's** compiled preview, while both saves block with `refuse_job_if_too_long` on the **job's** config (`script_builder.py:608-651`; `workspace.py:215-221`, `lines.py:363-366`). A draft that "fits" here can be refused at Keep.

**6. Review, `_reviewed` (`:936-978`).**
- Covers only the parts Pip changed.
- Call: `ask_json(REVIEW_INSTRUCTION (2,911), REVIEW_FORMAT, 4000 tokens, temp 0.2)`; the standby is allowed.
- Code decides each claim: `quoted_in` is required for "sourced", provider names are dropped, at most 3 findings per part (`parsed_review`, `campaign_script_ask.py:1046-1113`).
- Findings on repairable paths become `noted` and are **repaired** in step 7. The rest become `still_warned` **warnings**.
- Never blocks.

**7. `finish_written` (`script_proposal.py:476-519`).**
- `settled()` (`script_structure.py:359-380`) mends Pip's steps in code, in this order: renumbered, without_stray_outcomes, reached, without_echo_ways, without_judged_asks, without_empty_titles, collected, time_taken, ways_out_wired, pronounced.
- `_Fix.problems` (`:253-269`) = `script_mistakes` + `empty_title_problems` + `script_shape.line_problems` + `unasked_problems` + the review's `noted`. Only the problems Pip introduced count.
- `_fixed_further` (`:332-389`) runs up to `script_mistake_repair_passes` (default 2, `config.py:1530`). Each pass is `_repair_draft` → `draft_script(edit_of, fix_change(...))` → `kept_to_paths`.
- What is left becomes `left_out` **warnings**.
- `_opening_repaired` (`:115-183`) runs `opening_problems` → `write_opening` (`OPENING_WRITER_INSTRUCTION` 1,629 chars, 600 tokens, temp 0.5, 15 s) with `placed_rules=dialled`.
- Every step is crash-guarded.

**8. Policies, `_job_policies` (`:1066-1084`).** Deterministic: prices off without sourced prices, bookings off without a calendar.

#### Repair-context defect

`_repair_draft` (`script_proposal.py:306-329`) **[re-verified]** builds a **fresh** `brief_for(..., language=language)` with none of `_write`'s overrides: no `direction="outbound"`, no `grounding`, no `placed_calls`, no `owner_plan`, no `collect`. In addition, `_mistakes_checked` never passes `language` (`:453-460`).

So for a campaign, every mistake repair (and every heal repair, P8) is written and judged with:
- the **agent's** direction and language, not the campaign's;
- no main task or documents as grounding for figures;
- no owner plan check.

`_opening_repaired` builds its own brief as well.

#### Storage and going live

- **Stored:** only the proposal jsonb, through a compare-and-set on its id (`_store`, `:251-263`): `status: ready`, `script`, `disclosure`, `left_out`, `why`; or `failed` with `note` and `reason`. A row still drafting after 15 minutes reads as `stale`.
- **Metering:** `ASSIST_FEATURE_SCRIPT_DRAFT`, in the storing transaction (`:283-302`, `:1333-1338`).
- **Going live:** not until the owner keeps the draft (P7).
- **P2 differences:** no focus, so no P4; `LINE_ASK` (5,463 chars) in place of `CAMPAIGN_ASK` (8,249); `placed_calls=False`; inbound direction unless the agent is `both`.
- **P4:** a part ask replaces the whole lead with `PART_ASK`/`FLOW_ASK`, skips the task plan, refine and restructure, and leaves out the items, plan and `TASK_REMINDER`. The shorten and review passes and `finish_written` still run.
- **P3 with an owner plan in the instruction:** the script is rewritten whole from the owner's steps (`replans`, `campaign_script.py:494-512`), and refine and restructure run.

### P5: Pip rewrites every script it still owns (25 Nov, `9d35ee352`)

**Trigger.** Every script_heal pass (`apps/workers/script_heal.py:242-283`), meaning after any save and in the hourly sweep. `_rewrite_wanted` (`:286-305`) is true when all of these hold:
- there is no `REWRITE_KEY = "pip_rewrite:2026-11-25"` in `script_heal_fixed` (`api/agents/script_heal.py:69`) **[re-verified]**;
- the main task is not empty;
- `script_history.pip_owns` (`apps/api/campaigns/script_history.py:75-100`): a `pip_draft` row exists with no `owner_made`/`owner`/`restored`/`copied` row after it.

**A script the owner reviewed and kept still counts.** Keep writes `pip_draft`, so that script is Pip's and is rewritten unasked.

**How it runs.**
- `_ask_rewrite` (`:308-343`) calls `request_proposal(ask={"rewrite": "2026-11-25"}, requested_by=None)` and writes the key **before** the writer runs, so the rewrite is never retried.
- The writer runs as P1 with `base=None` (`campaign_script.py:625`, `:702`): task plan, draft, refine, restructure, shorten, review and finish.
- `_save_if_rewrite` (`:358-406`) runs under FOR UPDATE. It saves only if the script still equals `base_script` and `pip_owns` still holds, through `save_script(author="pip_draft", reason=REWRITE_REASON)`.
- Then `_dropped_if_rewrite` clears the proposal.

**Defect 1: warnings discarded.** It saves whatever `left_out` holds: on the last attempt `keep_with_warnings` keeps a rule-breaking draft. Then the proposal holding those warnings is deleted. Nothing the owner can see records them.

**Defect 2: not put live.** The `_save_if_rewrite` docstring says it "puts a live holder live again" (`:361`). **[re-verified]** that `campaign_script.py` has no put_live or publish call, and that neither `workspace.save_script` (`workspace.py:202-244`) nor `lines.save_script` (`lines.py:348-392`) puts anything live; they only queue `queue_job`, step_outcomes and script_heal.
- The heal pass that follows republishes only if it repairs something (`script_heal.py:268-272`, `:529`).
- So a live campaign or line keeps its **old** engine script after a rewrite, unless some later save or heal puts it live.
- Whether `field_suggestions.queue_job` ever republishes is UNKNOWN (not traced to the end).

### P6: first run

- With Pip allowed to spend: P1/P2 with `auto_save=True`. `_save_if_asked` (`campaign_script.py:305-339`) saves while `script IS NULL`, with author `pip_draft`. Its default reason, "You kept a script Pip wrote.", is **untrue** here.
- On a save refusal or a failed draft: `first_run.work.save_ready_made` (`work.py:376-440`). It uses `starters.ready_made_script`, author `system`, `READY_MADE_REASON`, and no model.
- The ready-made script keeps the starter's opening (`starters.py:758-761`), which nothing checks at save (see C14).

### P7: owner's manual save, Keep, and Put it live

**Campaign `PUT /{id}/script`** (`workspace_routes.py:350-431`) → `workspace.save_script`:
- `refuse_job_if_too_long` **blocks**;
- then `UPDATE`, `script_history.record`, `queue_job` (field suggestions), `step_outcomes.queue_after_save` and `script_heal.queue_after_save` **[re-verified]**;
- it goes live only if the campaign holds an engine agent (`:427-428`); otherwise at Start.

**Line PUT** (`inbound/routes.py:378-429`) → `lines.save_script`:
- the same, plus `version+1`, and the heal and step-outcome queues run in the **opposite order** **[re-verified]**;
- it **always** puts live (`_put_live_after_save`).

**Keep** (`workspace_routes.py:459-476`; `routes.py:556-568`) → `script_draft.ready_script` (compare-and-set) → save with `pip_draft`. **No lint runs again on Keep. Nothing on save blocks except length.** Faults in the owner's own lines are left to P8.

**`script_versions`** (`script_history.record`, `script_history.py:144-205`):
- columns: author, `owner_made`, reason (`_REASONS`, `:48-58`), `made_by`, `restored_from`;
- the table is pruned to 30 rows, always keeping the newest `owner_made`.

**Put it live, Start and Schedule** (`inbound/publish.py:38-43`; `campaigns/service.py:1564-1587`; `engine_agent.py:86-132`): launch blockers, engine limits, publish, then the read-back `verify_publish` **blocks**. **None runs the writer's lints.**

### P8: script_heal line repair (D-1038)

**Triggers:**
- `queue_after_save` in both saves (`api/agents/script_heal.py:189-221`), with a 30 s debounce;
- `queue_now` from mistake_fix (`:224-232`);
- the hourly sweep `sweep_script_heal` at minute 23, 50 holders, a 120 s budget (`workers/script_heal.py:87-98`, `:537-572`), worklist SQL `script_heal_scan`.
- It is **not** queued on line creation (`lines.py:246-258`), so a new line waits for the sweep.

**Dedupe:** `md5(script::text || "heal-5")`.

**Flow.**
1. A Pip draft that is open means wait.
2. Lint context: `lint_context_for(agent)` with `collect=()` and `places_calls=False`, then the campaign language and `judged` (`:259-261`).
3. **Code first, over every step, the owner's included:** `wired_ways_out` = `ways_out_wired` → `without_echo_ways` → `without_judged_asks` (`api/script_heal.py:153-161`).
4. `heal_findings` (`:133-150`) = `flow_problems` + `opening_redone_line_problems` + `reacted_line_problems` + `script_mistakes` + `_textbook` + `line_problems`. It is filtered by `_repairable`: not `step_outcomes`, not `PROTECTED_PARTS`, and the node must be a string.
5. P5 check.
6. Consent and quota gate.
7. `_repair` (`workers/script_heal.py:346-404`):
   - `draft_script(brief_for(...), edit_of, fix_change(findings))` with `EDIT_INSTRUCTION`, 50 s, 16,384 tokens;
   - `kept_to_paths` (`script_proposals.py:249-301`): only string lines at the finding paths; for `order_problems` it takes the model's ways out and step order; a placeholder path **deletes the step**;
   - `_fixed_further` with `check=heal_findings`.

**Saving** (`_save` and `_write`, `:448-534`):
- meter;
- `refuse_job_if_too_long`;
- a compare-and-set UPDATE (a campaign on the script jsonb, a line on `version`);
- the `script_heal_fixed` kinds;
- `script_versions` author `pip_repair`;
- `queue_put_live`.

It **goes live without review**.

**Bypassed:** this save skips `save_script`, so field suggestions and step outcomes are not queued.

**Leftover faults are only logged.** Unlike the writer, which warns the owner, heal records the digest as checked, so nothing is retried until the script or `CHECKS_VERSION` changes.

**Race:** `draft_open` is checked only at read time, not in `_write` (`:152`, `:247`).

### P9: mistake_fix (healer `call_mistake_fix`, `apps/workers/mistake_fix.py`)

- **Opening a fix:** `mistake_fixes.open_fixes` (`api/agents/mistake_fixes.py:239-292`) runs in the call pipeline, `found_by='call'` only.
- **ACT** (`_act` / `_request_repair`, `:269-364`):
  - `mistake_findings(upgrade_to_v2(script), lint_context_for(agent), kind)`, then `fix_paths`;
  - if there is a path: compare-and-set the fix row and call `script_heal.queue_now`;
  - if not: `needs_person`.
- **VERIFY** (`:367-401`): re-checks; clear means `fixed`; else re-ask, up to `call_mistake_fix_max_attempts` (2).
- **No model call and no script write of its own.**
- **Inconsistencies with P8:**
  - VERIFY uses bare `lint_context_for`: the agent's language and no judged details. Heal uses the campaign language and judged details;
  - VERIFY filters only with `fix_paths`, not `_repairable`;
  - VERIFY checks `upgrade_to_v2(script)` while heal returns `[]` for a script with no stages.

  Each of these can make heal report clean while VERIFY still faults, which burns the attempts and ends `attempts_spent`.
- `moved_on_unconfirmed` cannot clear in one heal pass. Its finding is on `.instruction`, but the check reads the branches, and `ways_out_wired` runs before the model.

### P10: step-outcomes writer (D-1036, `apps/workers/step_outcomes.py`)

**Triggers:**
- `campaigns/step_outcomes.queue_after_save` in both saves (30 s debounce);
- the hourly sweep at minute 47 (50 holders, 120 s);
- `hand_back_to_pip`.

**Inputs:** the holder's script, main task, purpose and goal, its knowledge, `business_context` and documents, all redacted.

**Model call** (`:685-704`):
- system `ASK` (`:126-150`, about 1,986 chars as counted by a lane; not run);
- strict `_FORMAT`; `MAX_TOKENS=4000`; temperature 0.2; 50 s; `salvage=accepted`.

**Checks** in code (`judged`, `:417-478`), each **repaired**, then dropped on salvage:
- the subject holds;
- the outcome is at most 300 chars and starts "The <subject>";
- it does not name a single case of a set;
- the quote is in the material;
- figures and providers are a subset of the material.

**Storage:**
- the column is written directly by compare-and-set, with `script_versions` author `pip_outcomes`;
- `step_outcomes_pip`;
- it **blocks** on `refuse_job_if_too_long`;
- `put_holder_live`.

**Overlap:** the main writer (P1) never writes `step_outcomes_pip`. Its outcomes are therefore treated as the **owner's** (`workspace.py:172-174`): never rewritten by this pass and never held to its code checks.

### P11 / P12: notice weave (D-971, D-1021)

**P12, per agent.**
- **Trigger:** `queue_opening_notices` (`api/agents/opening_notices.py:139-165`), at the end of `publish_agent` (`service.py:3800`, `:3878`) and when a switch flips (`publishing.py:1921-1935`).
- **Model call:** `write_opening` (`opening_line.py:330-385`), `OPENING_WRITER_INSTRUCTION`, 600 tokens, temp 0.5, 15 s.
- **Checks:** `_writer_problems` = `opening_problems` + `provider_problem` + `said_line_problem` + `spoken_line_problems`, **repaired** once, then the standby.
- **Apply:** `script_builder.replace_opening_line` → `rewrite_script` → a `prompt_versions` row with `WEAVE_NOTE`; then `publish_agent`. It **blocks** on `refuse_opening_over_limit`.
- **Retries:** arq at 60 s and 300 s.

**P11, per holder.**
- **Trigger:** only `queue_account_holder_notices`, on a switch flip. **A holder save never queues a weave.**
- **Apply:** `save_script(author="pip_notices")`, then `put_holder_live`.

**Defect.** Both weaves call `opening_problems` and `write_opening` **without** `placed=` / `placed_rules` (`workers/opening_notices.py:130-147`, `:246-263`), so a campaign's placed opening is measured against the answering cap: 120 + woven room, not `min(160 + woven, 200)` (`call_rules.py:58-74`). On a switch flip, a valid 140–160-char campaign opening would be judged too long and rewritten. This comes from reading the code; it has not been observed.

### P13: practice-test fixes (D-1017)

- **Trigger:** Pip's `agent_tests_fix` or the Training tab → `improve_agent_test_run`.
- **Model call:** `propose_improvement` (`apps/workers/agent_test_ai.py:921-954`), with its **own** prompt `IMPROVE_INSTRUCTION` (`:625-677`; 3,234 static chars + `writer_rules` + `OPENING_LINE_RULE` + `SPOKEN_LINE_RULES`, so about 8.5k or more, not run), strict schema, 2,500 tokens, temp 0.3, `IMPROVE_TIMEOUT_S=120`.
- **Not used:** `draft_script` and `salvaged_edit`. It works on an op list through `script_edits.apply_edits`.
- **Checks:** `script_edits.language_problem` (only `english_problem`, `textbook_problem` and `said_line_problem`) and `fix_guard`. **None** of `settled`, the call-mistake lints, `shape_problems`, the opening rule, `plan_problems`, the review or `finish_written`.
- **Opening edits** are asked for and then dropped (`test_fixes.py:148-152`).
- **Storage:** `write_holder_draft` (`:175-226`) writes a ready `script_proposal` directly. It goes live via Keep.
- **History:** `agent_test_ai.py` was last changed 21 Nov (`0138c1d2c`), so **none of the 22–26 Nov writer fixes reached this path** (section 6).

### P14 / P15 / P17: deterministic writers and agent-level versions

- **`apply_starter`** (`starters.py:695-746`) runs from `lifecycle.create_agent` and calls `save_agent_script` (openings blanked) → `prompt_versions`.
- **`replace_unedited_starter`** (`:888-962`) runs when the business type is confirmed.
- **The agent-level opening routes** (`script_routes.py:1180-1260`) and the admin `write_prompt_version` (`prompts.py:189-226`) write `prompt_versions` with no model call and no `language_problems`. That is a second version store beside `script_versions`.
- **P17, starter step plans:** `starter_steps.py:196-210`. `SYSTEM_PROMPT` is about 954 chars, 4096 tokens, temp 0.3, 40 s. The checks are an all-or-nothing step count plus `clean_plan`/`_kept` code repairs. The result is stored in `organizations.starter_plans`, which reaches the writer via `brief_for.step_plans` → `playbook_guidance`.

### P16: company training (D-1034)

- **Composed** first into every call prompt with `TRAINING_LEAD` ("Where the script after it says something different, follow the script", `company_training.py:71-75`). `TRAINING_MAX=6000`.
- **Triggers:** `schedule_write` on first_agent / knowledge_changed / profile_changed / owner_words / owner_asked, with a debounce of 60 s capped at 600 s.
- **Model calls:**
  - write: `TRAINING_ASK` (about 1,575 chars), 16,384 tokens, temp 0.3;
  - review: `REVIEW_INSTRUCTION` (about 1,431 chars), 4000 tokens, temp 0.2;
  - one repair; still failing → **not saved**, with an alert;
  - the fit is checked with one shortening.
- **Storage:** a compare-and-set on `company_trainings.version`. It **blocks** if any agent would overflow, then `queue_live_apply(scope="tenant")`, so it goes **live at once**.
- **No `script_versions` and no `prompt_versions` row.**

---

## 2. Which checks each path applies

**Key:**
- **R** = repaired by a model pass;
- **B** = blocks the answer while repair rounds remain, then reverted or failed;
- **C** = fixed by code;
- **W** = a warning shown to the owner;
- **L** = logged only;
- **–** = not applied;
- **?** = UNKNOWN.

**Columns:**
- **P1** = the writer: draft, refine, restructure, shorten and `finish_written` (P2–P4 are the same unless noted);
- **P5** = the rewrite: P1, but the warnings are discarded;
- **P7** = owner save / Keep / live;
- **P8** = heal;
- **P9** = VERIFY;
- **P10** = outcomes;
- **P11/12** = weave;
- **P13** = test fixes;
- **P16** = training.

| Rule / check | P1 | P5 | P7 | P8 | P9 | P10 | P11/12 | P13 |
|---|---|---|---|---|---|---|---|---|
| Length vs engine box (`refuse_job_if_too_long`) | W (measured on the **agent**), B at Keep | B (draft dropped) | **B** | B | – | B | B (`refuse_opening_over_limit`, agent only) | B at Keep |
| `language_problems` (textbook, provider, latin, said line, retired, introduced) | B | B | – | B (inside `draft_script`) | – | – | partial (`_writer_problems`) | partial (`script_edits.language_problem`: 3 of ~9) |
| `spoken_line_problems` / `instruction_problems` | B | B | – | B (inside draft) | – | – | B (opening) | – |
| `flow_problems` (brackets, repeats, same opener/ending, order, placeholder, unreachable, outcomes) | B (`shape_problems`) | B | – | **R** (but `unreachable`/`step_outcomes` dropped) | – | – | – | – |
| `opening_redone_line` / `reacted_line` | B | B | – | R (twice: direct + via `script_mistakes`) | via kind | – | – | – |
| `script_mistakes` (19 kinds) | R (`_fixed_further`), then W; flow-duplicate kinds excluded | R, then **discarded** | – | R, then L | the decision | – | – | – |
| `line_problems` (several actions, caller-action claim, judged ask) | R, then W | R, discarded | – | R | – | – | – | – |
| `structure_problems` (piled, trailing, named way, coverage) | R once (restructure), then W | R, discarded | – | **–** | – | – | – | – |
| `plan_problems` (owner plan / task plan) | B + C (`with_owner_plan`) + W | B + C | – | – (`owner_plan` not given to the brief) | – | – | – | – |
| `unasked_problems` (detail no step asks) | R, then W | R | – | – (`collect=()`) | – | – | – | – |
| `empty_title_problems` | C + R | C + R | – | R | – | – | – | – |
| `way_out_problems` (not now / not interested) | B (placed calls) | B | – | – (`places_calls=False`) | – | – | – | – |
| `settled` mends (renumber, stray outcomes, reached, echo, judged, empty titles, collected, time taken, wired, pronounced) | C (Pip's steps) | C | – | partial C: wired, echo, judged only, on **all** steps | – | – | – | – |
| `opening_problems` (opening rule) | R (`_opening_repaired`, placed rules) | R | – | – (openings protected) | – | – | R (**answering-call cap even when placed**) | – (opening edits dropped) |
| Review (unsourced claims, wrong actor, purpose, several asks, broken line) | R / W | R, discarded | – | – | – | – | – | – |
| Grounding: figures and quotes must come from sources | review (model + `quoted_in`) | review | – | – (no grounding in the repair brief) | – | **C/R** (`quoted_in`, `figures_in`) | – | `fix_guard` |
| Outcome subject rule "The <subject> …" | prompt only | prompt only | – | – | – | **R** (code check) | – | – |
| Bracket rule (D-1038) | B (flow) | B | – | R | kind | – | – | – |
| Hard rule 5 notices | prompt + compose | same | compose | protected | protected | – | **writes them** | dropped |

**Company training (P16)** has its own grounding (`quoted_in`), a review, and a fit check (B). It shares none of the checks in the table.

**What the table shows:**
1. **Only the writer applies the whole set, and only to lines Pip wrote.** Owner saves and Keep apply nothing but length. Heal applies a subset. Test fixes apply about 3 checks.
2. **Structure checks never run on a saved script** except through the one-time P5.
3. **Leftover faults are handled in three different ways:** the writer warns, heal logs, and the rewrite discards.
4. **Grounding is checked in code in P10 and P16, and only by a model review in P1.**

---

## 3. Lint and check catalogue (where each is defined and who calls it)

**`script_lint.py`:**
- `flow_problems` (`:1501`) is called by heal (`api/script_heal.py:143`), `shape_problems` (`script_assist.py:561`) and `mistake_lints.py:464` (where it is used to **exclude** findings).
- It is made of: `placeholder_problems` 759, `order_problems` 944, `repeated_line_problems` 1008, `opening_redone_problems` 1051, `same_opener_problems` 1081, `same_ending_problems` 1158, `bracket_problems` 1227, `empty_title_problems` 1247, `unreachable_problems` 1266, `step_outcome_problems` 1296.
- **No production caller at all:** `step_number_problems` 1287, `untaken_time_problems` 1329, `unwired_way_out_problems` 1484 and `pronunciation_problems` 1377. They run only via `script_problems` (eval). Their code-fix twins exist in `settled`.
- **Eval-only wrappers:** `multi_question_line_problems` … `known_value_asked_problems` (`:1528-1588`).

**`call_rules.py`:** `opening_redone_line_problems` (`:418`) and `reacted_line_problems` (`:505`).

**`mistake_lints.py`:**
- `_CHECKS` (`:409-429`) has 19 kinds: `call_mistakes.LESSONS` minus `missed_lookup`.
- Entry points: `mistake_findings` 438, `fixable_findings` 448, `script_mistakes` 454.
- **Stale docstring:** `:14-22` claims `script_mistakes` runs on "the readiness card and in Put it live", but neither caller exists. The comment at `:407` says "The four that flow_problems already finds"; it is now five.

**`script_shape.py`:**
- `structure_problems` 267 is called only from `campaign_script.built_wrong`.
- `line_problems` 422 is called by heal and `_Fix`.
- `echo_branches` 73.

**`script_structure.py`:** `settled` 359 (writer only), `ways_out_wired` 226, `without_echo_ways` 271, `without_judged_asks` 249, `collected` 295.

**Other checks:**
- `owner_plan.plan_problems` 471 and `with_owner_plan` 665;
- `opening_line.opening_problems` 135 and `_writer_problems` 235;
- `spoken_guard.textbook_problem` (used by 7 callers);
- `script_edits.language_problem` 263, a subset reimplementation;
- `mistake_fixes.PROTECTED_PARTS` (`:54-56`).

**Duplicates:**
- The textbook check runs twice in `heal_findings`: `_textbook` and `formal_words` → `turn_checks.textbook_words`. The messages differ by a trailing "." (`spoken_guard.py:119` vs `mistake_lints.py:335`), so they are not deduped, and the model is told the same thing twice.
- There are three opening checkers: `language_problems` (introduced, woven, placed), `call_rules.placed_opening_problems`, and `opening_line.opening_problems`.

---

## 4. Writer prompt size for a real campaign (measured in Docker)

### Inputs

- **Campaign:** the Rytu Khata fixture (`tests/fixtures/campaign_script/farm_app_install.json`): Telugu, outbound, tone "brief", budget 6000.
- **Brief:** `ScriptBrief(business_name, agent_name, custom, outbound, te-IN, 2 collect labels, 1 fact)`.
- **Base script for edits:** the `call_leads` starter, serialised as `draft_script` does: `model_dump_json(exclude=_not_shown)`, **4,754 chars**.
- **What is missing from the brief:** a real account also carries capabilities, fit, the owner's facts and the style guide, so the real user message is **larger** than measured here.

### Constants (runtime `len()`)

| Constant | chars |
|---|---|
| `_SYSTEM_INSTRUCTION` (whole draft) | **13,647** |
| `EDIT_INSTRUCTION` (every edit, refine, restructure, shorten, repair, heal) | **12,445** |
| … of which `writer_rules()` | 3,689 (incl. `SCRIPT_FLOW_RULE` 3,163) |
| … `WAYS_OUT_RULE` | 2,832 |
| … `STEP_RULES` | 2,163 |
| … `OPENING_LINE_RULE` | 1,525 |
| `ScriptBrief.user_message()`, minimal brief | 6,943 |
| `CAMPAIGN_ASK` / `LINE_ASK` | 8,249 / 5,463 |
| … `CALL_KINDS_TEXT` | 1,943 |
| `REFINE_TAIL` | 1,353 |
| `playbook_guidance("custom","outbound")` | 2,520 |
| `REVIEW_INSTRUCTION` | 2,911 |
| `TASK_STEPS_INSTRUCTION` | 954 |
| `OPENING_WRITER_INSTRUCTION` | 1,629 |
| `FLOW_ASK` / `PART_ASK` | 1,500 / 1,172 |
| Other rules | DETAILS 1,014 · PLAN_RULE 932 · OUTCOMES 782 · SHAPE 717 · CONCISE 516 · GROUNDING 522 · OBJECTIONS 493 · PURPOSE 404 · PERSON 400 · SHORTEN_ASK 379 · SPECIFIC 306 · CLOSING_STEP 261 · RESTRUCTURE_TAIL 257 · LINE_FIRST 184 · TURN 122 |

### One request (system + user), by document size

The document cap is `KNOWLEDGE_DOCUMENT_CHARS = 40,000`.

| Request | small doc (542) | 10k doc | at the cap (40.5k) |
|---|---|---|---|
| First draft (`_SYSTEM_INSTRUCTION` + brief + `campaign_change` + playbook) | **32,480** | 42,389 | 72,437 |
| Refine (`EDIT_INSTRUCTION` + brief + change with `REFINE_TAIL` + script JSON) | **34,887** | 44,796 | 74,844 |
| Generate again (edit) | 33,611 | 43,520 | 73,568 |
| Mistake repair / heal, one finding (`EDIT_INSTRUCTION` + brief + `fix_change` + JSON) | 24,433 | 24,433 | 24,433 |

### A whole first script, before any repair round

This is an estimate added up from the measured parts. Each repair round re-sends the whole conversation plus the previous answer.

- task plan: about 2k
- draft: 32.5k
- refine: 34.9k
- restructure (if triggered): about 34k
- shorten (if triggered): about 30k
- review: 2.9k + the parts
- 2 mistake passes: 2 × 24.4k
- opening: about 8k

That comes to **about 150–190k characters of input per first script** with a small document, and roughly **+40k for each request** at the document cap.

### Notes

- **Rules sent twice.** In every edit pass the same rules arrive twice: `STEP_RULES`, `WAYS_OUT_RULE` and the opening rule sit in the system prompt, and `CAMPAIGN_ASK` restates parts of them (C3, C7, C8 below).
- **The documents are labelled as the owner's words.** In a whole draft the entire `campaign_change`, documents included, is presented as "In the owner's words:" (`script_assist.py:1259-1260`). It also becomes `allowed` / `owners_words` grounding, which exempts document wording from the textbook check (C12).

---

## 5. Rules in the writer prompts that conflict or overlap

Each pair is quoted from the code. **[V]** means the lead re-checked it at source.

**C1 [V]. `sounds_like` must be empty vs it must not be empty.**
- `VALUE_FACT_NOTE` (`script_assist.py:1127-1133`), sent in every non-inbound brief, every campaign included: "Its sounds_like stays empty: any example would be a fact."
- `shape_problems` (`script_assist.py:569-574`) **blocks**: "stages.{i}.sounds_like: is empty; write one short line in the call language showing how this step sounds."
- A model that obeys the note is sent back for repair.

**C2 [V]. Never write about call backs vs call backs are required.**
- `_SYSTEM_INSTRUCTION` (`:279`): "nowhere write about call backs or transfers, or about do-not-call requests". `EDIT_INSTRUCTION` (`:365-366`) says the same.
- `WAYS_OUT_RULE` (`:199-204`): "An instruction that says what to do if the person cannot or will not go on (offer a call back, end politely) has that as a way out too. A call back … is the last resort".
- `STEP_RULES` (`:237`): "offer_call_backs unless the owner says never".

**C3 [V]. Field names in the campaign ask do not match the whole-draft schema.**
- `CAMPAIGN_ASK` (`campaign_script_ask.py:335`) and `LINE_ASK` (`:348`): "quick facts (the faqs list…". `CONCISE_RULE` (`:324`) and `tone_line` (`:608`): "style.tone".
- The strict whole-draft schema has `quick_facts` (`script_assist.py:1099`) and a top-level `tone` (`:1067`), with `additionalProperties:false`.
- These names are correct only for an edit (the `CallScript` shape).

**C4 [V]. The playbook's "Check it is a good time" step vs no step asks whether now suits.**
- `trade_playbooks.py:228`: title "Check it is a good time" ("If they cannot talk now, ask when suits them"). It is sent through `playbook_guidance` on every whole draft with no owner plan, and it is built into the ready-made calling starters (`starters.py:400-405`, `:488`, `:512`), which the first-run fallback saves.
- Against it:
  - `STEP_RULES` (`script_assist.py:226-229`): "The first stage goes on from the person's answer to the opening line: no stage greets, says who is calling or asks whether now suits".
  - `OUTCOMES_RULE` (`campaign_script_ask.py:208-210`): "never greets, says who is calling or asks whether now suits again".
  - The step-outcomes `ASK` (`step_outcomes.py:135-137`) says the opening "is said before step 1 and is not a step".
- Likewise "Say why you called" (`trade_playbooks.py:235-243`) repeats what `PLACED_OPENING_RULE` (`call_rules.py:87-91`) puts in the opening.

**C5 [V]. One step per task vs the fewest steps vs cases as scenarios.**
- `OUTCOMES_RULE` (`:201-202`): "List every task the main task names … and give each its own step".
- `CONCISE_RULE` (`:321-322`): "and the fewest steps reach the main task. Say each thing once."
- `SHAPE_RULE` (`:281-282`): "a path for each device, plan or case it names is a scenario of the same step".

**C6. One sentence per line vs a two-part first line.**
- `TURN_RULE` (`:216-219`): "Each line the agent says is one short sentence with at most one question in it".
- `PURPOSE_RULE` (`:296-299`): "first says in one short sentence why the call is made … then asks one question". `OBJECTIONS_RULE` (`:177-179`) and `CLOSING_STEP` (`:34-36`) also ask for several clauses.

**C7 [V]. A verbatim duplicate in the same request.**
- `CONCISE_RULE` (`:320-321`): "Each step's instruction says in at most three short sentences what this scenario does toward its step's outcome, what to check or ask, and when it is done".
- `STEP_RULES` (`script_assist.py:225-226`): the same sentence.
- "never … asks whether now suits" appears three times: `STEP_RULES`, `OUTCOMES_RULE` and `PURPOSE_RULE` (`:300`).
- All of this sits in the same request as "Say each thing once".

**C8. The owner plan's ways out vs the system's required ways out.**
- `PLAN_RULE` (`:425-426`): "These are a step's only ways out; a step with none listed gets none". `PLAN_HEAD` (`:414-416`) says the plan wins over the ways-out rules.
- But `WAYS_OUT_RULE` stays in the system prompt ("for every stage that asks the person something … give each its way out", `script_assist.py:174-176`; "The person who does not remember it or asks who is calling gets a stage of its own", `:185-187`).
- Code still runs `way_out_problems` on placed calls (`:546-547`).
- Whether `plan_problems` ("one they did not name") and `way_out_problems` can demand opposite things at runtime is PLAUSIBLE, not executed.

**C9. Two step plans plus the trade playbook.**
- `CALL_KINDS_TEXT` (`campaign_script_ask.py:137-143`): "Where a step plan below differs from the kind of call, keep only its steps that serve the main task."
- The playbook (`trade_playbooks.py:408-409`): "Use these step titles as written".
- The code's own comment (`script_assist.py:2364-2366`) says "two plans in one ask is how the trade's steps replaced the owner's". Without an owner or task plan, the call kinds and the playbook are still both sent. Since 26 Nov (`a23ff08ca`), the task plan suppresses the playbook only when the main task is numbered.

**C10. "No offer" vs "before the offer".**
- `_SYSTEM_INSTRUCTION` (`:282-283`): "never an offer, discount, scheme or urgency".
- `VALUE_FACT_NOTE` (`:1129`): "in one sentence after the questions and before the offer".

**C11. A `hand_over` way out vs no way out for asking for a person.**
- `WAYS_OUT_RULE` (`:178-179`) lists `hand_over` as a target.
- `:192-193`: "Write no way out for asking for a person".

**C12. A label mismatch.** The whole `campaign_change` (rules plus documents) is shown as "In the owner's words:" (`script_assist.py:1259-1260`, `campaign_script.py:1222`), and it is the `allowed` and grounding text. So document wording is exempt from the textbook and figure checks as if the owner had written it.

**C13. The outcome rule is written three times, and only one copy is enforced in code.**
- `STEP_RULES` (`script_assist.py:218-245`), `OUTCOMES_RULE` (`campaign_script_ask.py:200-211`) and step-outcomes `ASK` (`step_outcomes.py:127-131`).
- Only P10 checks "The <subject>", the quote and the alternatives in code.
- `PLAN_RULE` ("Give each numbered step the owner's outcome, in the owner's words", `:420-421`) and `with_owner_plan` pin the owner's wording even when it breaks the subject rule.

**C14. The enquiry wording in the starter opening.**
- `call_new_leads` opening: "about the enquiry you just made" (`starters.py:501-504`).
- `OPENING_WRITER_INSTRUCTION`: "never that the person enquired, asked or showed interest" (`opening_line.py:91-93`).
- `ready_made_script` keeps the starter opening (`:758-761`); the first-run fallback saves it, and nothing checks the opening at save.

**C15. The improver is told how to write opening lines, which are then dropped.** `IMPROVE_INSTRUCTION` allows `set_part` on `opening_line` (`agent_test_ai.py:647-657`), and `test_fixes.writable_edits` drops it (`test_fixes.py:148-152`).

**C16. Instruction length is set two ways.** "at most three short sentences" (`STEP_RULES`, `CONCISE_RULE`) vs "under 500 characters" (`IMPROVE_INSTRUCTION`, `agent_test_ai.py:660`); the shared limit is `STAGE_DETAIL_MAX=600`.

**C17. Training vs script.** The training's objections and questions sections duplicate the script's objections and quick facts. Precedence is set only by `TRAINING_LEAD` ("follow the script").

---

## 6. History: which fixes reached which paths

This comes from `git log --since=2026-11-08` on the writer, heal, lint and auxiliary files, plus the touched-file list of each key commit (test files excluded). The last change to each auxiliary path:

| File | Last change |
|---|---|
| `agent_test_ai.py` (P13) | `0138c1d2c`, 21 Nov |
| `script_edits.py` | `3ac5715d0`, 23 Nov |
| `test_fixes.py` | `a740e2909`, 17 Nov |
| `opening_line.py` | `b893406d7`, 21 Nov |
| `opening_notices.py` | `f3172a1db`, 24 Nov |
| `step_outcomes.py` | `fcf5d8453`, 25 Nov |
| `company_training_draft.py` | `e08a9af1d`, 24 Nov |
| `starters.py` | `356b0ce14`, 21 Nov |
| `trade_playbooks.py` | `a120b24e3`, 16 Nov |

| Commit (date) | Fix | Reached | Did not reach |
|---|---|---|---|
| `73a49a612` (21 Nov) | Send back lines that open with a reaction or redo the opening | script_assist (P1–P5), mistake_lints | P13 |
| `1679debdb` (21 Nov) | Grounded in sources and the campaign | campaign_script, campaign_script_ask, script_proposal | heal/repair brief (no grounding), P13 |
| `47db4dd31` (21 Nov) | Ways out per step (not now, wrong person, who is calling, not interested) | script_assist, script_lint, campaign_script | heal (`places_calls=False`), P13, starters/playbook |
| `bffe3fc76` (21 Nov) | Placed-call openings say who and why | call_rules, opening_line, script_proposal, writer | weave P11 (`placed_rules` not passed), starters (C14) |
| `054940012` (22 Nov, D-1031) | First script refined; collect fields reach the writer | campaign_script(_ask) | heal (`collect=()`) |
| `9d244b403` (23 Nov) | Step outcomes, structural mends, wider review | writer, script_structure, script_lint, script_proposals | heal (only 3 of 10 mends), P13 |
| `262d5be86` (24 Nov) | Opening asked again, job's details asked, varied lines | writer, lints, turn_checks | P13 |
| `a0871c1b0` (24 Nov, D-1038) | script_heal; brackets as a finding | heal, mistake_fix, script_proposal, lints | P13 (no bracket check), P7 save (no lint) |
| `e2613d343` / `e08a9af1d` (24 Nov, D-1036) | Step outcomes: one subject, Pip rewrites only its own | step_outcomes, campaign_script_ask, script_assist (prompt only) | P1 outcomes not code-checked (C13) |
| `3299889b2` (24 Nov) | "Tell me when it's done" | call_rules, mistake_lints, script_heal, script_lint, turn_checks | P13 |
| `e53edc1e7` (25 Nov) | A way out written in words becomes a branch | script_structure, script_assist, script_heal, script_lint | P13 |
| `9d35ee352` (25 Nov) | Root fixes: judged asks, fake branches, steps after the close, items coverage, purpose line, Pip rewrite (memory d95ec1ab) | writer, heal, lints, script_shape, script_history | `structure_problems` not in heal; P13 |
| `c9dd2fb51` (25 Nov) | Lints read wider (judged asks, listed asks, close by role); `heal-5` | script_lint, script_shape, script_heal, script_proposal, script_builder | campaign_script_ask prompts unchanged |
| `0e06de2e3` (0.5.52) / `6a414bd7e` (0.5.55) | Retry a broken draft; swap textbook words; last try kept with warnings | campaign_script, script_assist | P5 discards those warnings |
| `83304a530` (0.5.59) / `533f51447` (0.5.63) / `d0dda3ae9` (0.5.64) | Keep the owner's step list; side steps; call back last resort; long last-resort ways out | owner_plan, script_structure, script_assist, campaign_script(_ask), mistake_lints | heal (no `owner_plan` in its brief) |
| `a23ff08ca` (26 Nov) | A numbered main task is read as a step plan | owner_plan, campaign_script(_ask) | P2 line? (shared `_write`, so yes); heal and repairs (no plan) |
| `bb5886b0` / `ad618f82e` (15 Nov) | Repair rounds per job; no standby after an answer | campaign writer | `_task_plan` and `_reviewed` still allow the standby; a truncated paid answer still falls through (§0) |

**Pattern:** since 21 Nov, every quality fix landed in the writer, and many in the lints. The heal pass inherits the lints but not the writer's context (no grounding, plan, collect, placed calls, or outbound direction). The practice-test fixer (P13), the starters and playbook, the notice weave, and the owner save and Keep received none of them.

---

## 7. Shared vs duplicated code (for the rebuild)

**Shared:**
- one ladder (`ask_json`);
- one writer `_write` for campaigns and lines;
- one tail `finish_written` / `_fixed_further`, also used by heal;
- `kept_to_paths`;
- `knowledge_words`, `documents_block`, `quoted_in`, `figures_in`.

**Duplicated or diverging:**
1. **Five model-JSON → script parsers:** `_script_from_model_json`, `salvaged_edit`, `script_edits.apply_edit`, `write_opening.parse`, `task_steps_text`/`parsed_review`.
2. **At least six "apply onto existing" mechanisms:** `merged_repair`, `_owners_fields`/`owners_where`, `kept_to_paths`, `apply_edits`, `with_owner_plan`, `_openings_of`/`openings_kept`.
3. **At least six repair loops, layered:** `ask_json` rounds, `WRITE_ATTEMPTS`, `_fixed_further`, single passes, `write_opening`, `_send_back_once`.
4. **Four holder-script write implementations:**
   - `workspace.save_script` and `lines.save_script` (different queue order; only the line bumps `version` and always goes live);
   - `script_heal._write`, which bypasses the save's queues;
   - `step_outcomes._save`;
   - plus two version stores (`script_versions`, `prompt_versions`).
5. **Two length measures:** the agent's `compiled_preview` in the worker vs the job's `refuse_job_if_too_long` at save.
6. **Two lint contexts for the same kind:** heal vs mistake_fix VERIFY.
7. **Three failure notes:** `UNUSABLE_NOTE`, `workspace.FAILED_NOTE`, `script_proposals.FAILED_NOTE`.
8. **Copied code:** `_meter` (`campaign_script.py:283-302` = `script_heal.py:407-427`); the job-time budgeting in `_late_timeout`/`_left_s` and `_repair_timeout`, each with its own `_JOB_MARGIN_S=30`.

---

## 8. UNKNOWN

- The runtime user-message size for a real account (capabilities, fit, facts, style guide). The measured 6,943 is a minimal brief.
- Whether `field_suggestions.queue_job` republishes after a P5 save. Not traced.
- Whether `draft_script` can raise a non-`ProblemError` in `_shortened`.
- Whether the plan vs ways-out conflict (C8) loops at runtime. Not executed.
- `assert_view_as_may` on Pip's `script_draft` tool. Not found in the function.
- The exact count of ladder requests per heal pass.
- `publishing.apply_to_live` / `undo_staged`: only their docstrings were read.
- Whether v1 holder scripts still exist. This matters for the P9 vs P8 mismatch.
