# The assistant's tool contract

How to add a tool to the in-app assistant (the copilot). Every Phase 2 lane follows this
exactly. The decision behind it is D-694 (docs/ROADMAP.md §6); the code it describes lives
in `apps/api/copilot/`.

A tool is one of four kinds. Pick the kind first; everything else follows from it.

| Kind | What it does | Where it is registered | Runs |
|---|---|---|---|
| **Read** | Looks something up. Changes nothing. | `tools.py` `READ_TOOLS` or `console_reads.py` `CONSOLE_READ_TOOLS` (client; composed in that order by `service.realm_read_tools`), or `admin_tools.py` `ADMIN_READ_TOOLS` | at once, many per turn |
| **Immediate action** | A reversible change that reaches no caller and spends nothing. | `write_tools.py` `WRITE_TOOLS` or a module joined into it (`agent_actions.py`, `console_actions.py`, `script_actions.py`) | at once, with an Undo |
| **Confirm action** | An irreversible or costly change. | same registry, `tier="confirm"` | only after a person clicks Confirm (or Approve, in a background job) |
| **Admin action** | A change to PLATFORM state, by an operator. | `admin_actions.py` `ADMIN_ACTIONS` | confirm only, with the console button's step-up |

## 1. The tier

The tier answers one question: **can this be taken back, and does it reach a caller or spend
money?**

* `immediate` — reversible, reaches no caller, spends nothing. Examples: edit a lead's
  fields or notes, set a status, tag, assign, draft or edit an agent before publishing,
  create a draft campaign, book or move a callback, rename, add knowledge as a draft.
* `confirm` — anything that dials or reaches a caller, launches or resumes a campaign,
  publishes an agent, buys or releases a number, spends credit, deletes anything, changes
  DNC (hard rule 5), or changes KYC.
* Neither, and never registered: accepting legal documents or the no-cold-calls pledge.
  Only the owner accepts those, on their own screen.

Rules that bind every tool:

1. `ActionTool.tier` and `ActionTool.undo` have **no default**. `ActionTool.__post_init__`
   refuses an `immediate` tool with `undo=None` and a `confirm` tool with an `undo`.
2. The tier is read only from the registry (`write_tools.tier_of`), never from arguments or
   from anything the model says.
3. When in doubt, it is `confirm`. A mis-tiered action is an incident.
4. `actions_test.py` enumerates the registry; a new tool that reaches a caller or moves
   money must appear in its confirm list.

## 2. The planner, `prior_state` and the inverse

Every action tool has two halves and, if immediate, an `Undo`:

```python
ActionTool(
    name="...",  # snake_case, unique in the realm
    tier="immediate",  # or "confirm"
    permission="...",  # the permission the console BUTTON for this act declares
    object_type="...",  # "lead", "agent", "campaign", ...
    audit_action="...",  # the audit_log action name the button writes, or a new one
    where="...",  # where a person finds the result, in their words
    schema=action_schema(name, description + DOES_IT | PROPOSES_ONLY, properties),
    plan=_plan_x,  # READS ONLY; returns Plan with canonical args
    execute=_execute_x,  # calls the SAME service function the button calls
    undo=Undo(capture=_capture_x, invert=_invert_x),  # or None for confirm
)
```

* **`plan`** reads under the caller's RLS session, resolves every id, normalises the
  arguments and returns a `Plan`: `title`, `summary`, `current`, `proposed`, `cost` (`None`
  means "costs nothing"), `reversal` (never `None`, never softened), and the canonical
  `args`. What executes is `plan.args`, never the model's raw JSON. A refusal the model can
  fix is `WriteRefusedError(reason)`; a fact about the world is a `ProblemError`.
* **`execute`** calls the service function the console button calls — never a copy, never
  a fast path — so every gate that button meets is met here. It returns `Executed(applied,
  detail, audit_summary, object_id)`. `applied=False` means the world was already in that
  state.
* **`capture`** (immediate only) reads the fields `execute` is about to overwrite and
  returns them as a small dict. It runs twice, in the same transaction:
  immediately BEFORE `execute` (stored as `prior_state`) and immediately AFTER it (stored as
  `result_state`; for a create, `args` gains `<object_type>_id` = the produced id first).
  Ids, statuses and names only — never a caller's data.
* **`invert`** (immediate only) receives an `UndoRecord(object_id, args, prior_state,
  result_state)`. It must:
  1. lock the row (`SELECT ... FOR UPDATE`);
  2. compare it with `result_state` and raise `UndoRefusedError("<sentence>")` if anything
     changed since (the CAS);
  3. restore `prior_state` through the button's own service function;
  4. return the sentence the person reads ("The lead is back to Contacted.").
  It may read only IDS from `record.args`: the stored arguments are redacted.

If you cannot write an exact inverse, the tool is `confirm`.

**The description** (D-779) is written for a new hire and is paid on every request, because
the whole realm's tool array is the cacheable prefix:

* what it does, in one sentence, then when to use it;
* when NOT to use it, by naming the sibling that does that job in backticks, whenever two
  tools overlap (`leads_search` / `leads_semantic_search`, `agent_edit` /
  `agent_edit_live`, ...). The pairs are listed in `tests/copilot_tool_eval_test.py::SIBLINGS`;
  add yours there;
* what each argument means and where its value comes from (an id "from `agents_list`");
* then `DOES_IT` or `PROPOSES_ONLY`, which already say which kind it is and what to say
  afterwards. Do not restate them, and do not use capitals for emphasis.

Keep it short: every sentence is repeated in every request of the realm.

## 3. The permission check, inside the tool

The tool array is **byte-identical within a surface** (prompt caching): never add, remove or
reorder a tool by screen, tenant or role. There are three surfaces, each one fixed list
(D-816, `service.tool_array`): the client realm; the admin realm with an account open; the
admin realm on a console screen, which leaves out the account-scoped read tools (they refuse
with no account). The admin realm carries no client write tool: every one refuses an admin
principal (no tenant, or a view-as session where `copilot:use` is withheld);
`copilot/tool_surfaces_test.py` proves both. New tools APPEND to their registry. Permission
is checked inside:

* `plan_write` / `run_immediate` / `confirm` / `approve` each call
  `actions.may_act(session, actor, tool.permission)` — the role table, the view-as rule and,
  for `kb:write`, the owner's curation switch. You add nothing: declare `permission`.
* The client assistant is closed to a view-as session (`assistant_closed_to`).
* An agent-subject tool is refused on a deleted agent before it plans
  (`_refuse_a_deleted_agent`) — keep the `agent_id` argument name.
* Admin actions use `role_has(actor.role, tool.permission)` and refuse an impersonating
  operator; set `confirm_action` to the step-up string the console button sends, and the
  admin confirm door demands that header plus a fresh second factor. Set it to `None`
  only when the button asks for no step-up.
* An admin action on ONE client's account is `scope="tenant"`: it acts on the account whose
  page is open (`viewing_tenant_id`, signed into the token as `viewing`), plans, executes
  and writes its audit row inside that account's own `tenant_session`, and is refused when
  no client's page is open. Platform state is `scope="platform"` (an untenanted session).
  Never take a tenant id from the model.

### Services that open their own transaction

Some console functions push to the voice platform inside a session they open themselves
(`set_agent_voice`, `set_disclosure_posture`, `apply_to_live`, `purchase_engine_number`).
Call them BEFORE the action's own session touches the same row, and compare without
`FOR UPDATE` in the inverse — a row lock held by the outer transaction deadlocks the inner
one. The service's own lock is then the swap's guard.

### When the button's logic lives in its route

Extract it into a service function both doors call (`crm/lead_dial.place_lead_call`,
`compliance/kyc_review.decide_kyc_review`, `healer/decisions` for the healer screen's two buttons), or, for a READ whose route holds only a query,
call the route function itself with a narrow `Principal` (`console_reads._principal`). Never
copy the body.

## 4. Redaction

* **Consent decides (D-788).** Pip runs on a client account only after its owner turned it
  on (`copilot/consent.py`; the ask, upload and job paths refuse `copilot_consent_required`
  before), and the admin console never asks. Every run then carries
  `ToolContext.unmasked`, and `tools._clean` skips `redact()` while it is set, so a tool
  result reaches the model as stored. A tool that reads RAW transcript text must write the
  `transcript.read_raw` audit row with `context.unmasked.actor` and `.ip` in the same
  session, as `call_detail` does. Without `unmasked` (a test, an eval) `_clean` still masks:
  never return a value that `_clean` would not see.
* Never send a tool result, a file or the raw question to the Sarvam standby;
  `service.masked_messages` masks everything that leg receives.
* Name a person's record by id where you can; let the server resolve a number itself (see
  `dnc_add`).
* Strip invisible characters from anything you interpolate (`strip_invisible`).
* The action log stores `args` through `workers.redaction.redact` (ids untouched) and
  never stores a refusal's arguments. Do not put a value into a refusal reason.
* Log ids and tool names only (hard rule 6).
* **Files a person attaches (D-781).** A picture or the text of an attached
  file reaches the model whole and unredacted (`copilot/attachments.py`), fenced in
  `<attachment>` like screen content, and never reaches the Sarvam standby. A tool must not
  read, store or log an attachment; the transcript keeps only `[N files attached]`.

## 5. Tests every tool ships with

1. **Plan**: the canonical args, the 404 for another tenant's id (RLS), and each
   `WriteRefusedError`.
2. **Execute** through `run_immediate` (immediate) or `confirm` (confirm): the change, the
   `audit_log` row (`via: copilot`), the action-log row (`status`, `tier`, `prior_state`,
   `result_state`).
3. **Undo** (immediate): the restore; the CAS refusal after a concurrent change; a second
   undo answered `copilot_action_already_undone`; another person's or another tenant's id is
   `404`.
4. **Permission**: a role without the button's permission is refused inside the tool; the
   refusal is logged without arguments.
5. **Tier**: add it to `actions_test.py`'s enumeration if it reaches a caller or spends.
6. **Wire**: `tools_test.py`'s byte-identity per realm still holds and the new schema is
   appended, not inserted.
7. A new tenant table ships with RLS in the same migration and a cross-tenant zero-rows
   test.
8. **Tool choice** (D-779): add one or two questions the tool should answer to
   `tests/fixtures/copilot_tool_choice.json` (and one it must not, as `forbid`, if it
   overlaps a sibling). CI checks the fixture against the live arrays with no model
   (`make copilot-eval`); an operator with a key scores the real model with
   `make copilot-eval PROVIDER=google MODEL=<fast or planning tier id>` (or
   `PROVIDER=azure`), before and after a prompt or description change, on both tiers.
   For whole answers and their cost (D-816), run the live eval on a deployment with the real
   keys and a demo account, never in CI: `uv run python -m scripts.copilot_tool_eval --live
   --spend --tenant=<demo account id> --record=before.json`, change, run again into
   `after.json`, then `--compare before.json after.json`. Per question it records the tools
   used, the answer (redacted), input, cached and output tokens and the rupee cost; writes
   are refused (no principal), and it prints its total spend.

## 6. Stream events (`POST /v1/copilot/ask`, `POST /v1/admin/copilot/ask`)

`text`, `fill`, `step`, `proposal`, `action`, `navigate`, `job`, `done`, `error`.
`copilot/schemas.STREAM_FRAMES` is the single declaration and
`copilot/stream_contract_test.py` pins it; the browser's twin is `lib/copilot/types.ts`.

* **`action`** — an immediate action that has already happened:
  `{tool, title, detail, object_type, object_id, applied, reversal, where, action_id,
  undoable_until}`. While `undoable_until` is in the future, show Undo, which posts to
  `POST /v1/copilot/actions/{action_id}/undo` (admin: `/v1/admin/copilot/actions/...`).
* **`proposal`** — a confirm action, nothing has happened:
  `{token, tool, title, summary, object_type, object_id, current, proposed, cost, reversal,
  expires_at, confirm_action}`. Post `token` unchanged to `POST /v1/copilot/confirm` (admin:
  `POST /v1/admin/copilot/confirm`, sending `confirm_action` as `X-Confirm-Action`).
* **`job`** — the request became a background job: `{job_id, status, goal, detail}`.
* **`navigate`** — open a screen: `{tool, screen, route, where, detail, reversal}`; the
  browser checks `route` against its own sidebar list.
* **`step`**, **`text`**, **`fill`**, **`done`**, **`error`** — unchanged (route
  descriptions in `copilot/routes.py`).
* **Attachments (D-781)** are not a frame: the browser uploads each file first
  (a PDF goes as it is, with its browser-extracted text as a sibling naming it in
  `X-Upload-Text-Of`; a PDF turn runs only on Gemini: native first, then its text on the
  usual leg, else `copilot_pdf_unavailable` — `service._answer_pdf_turn`)
  (`POST /v1/copilot/uploads`, raw body, `X-Upload-Name`; admin twin under
  `/v1/admin/copilot/uploads`) and sends their ids as `CopilotAskIn.attachments`. A file is
  read back only by its owner through `GET .../uploads/{id}/content` and removed with
  `DELETE .../uploads/{id}`.

## 7. The action log, approvals and jobs API

All client routes require `copilot:use`; all admin routes `copilot:admin` on the admin realm.
A row is visible only to the person who asked (RLS scopes the account, the query scopes the
person).

| Route | Does |
|---|---|
| `GET /v1/copilot/actions?limit&before` | The activity log, newest first: `{actions: [CopilotActionOut], has_more}`. Each row: `id, realm, tool, tier, status (done/undone/refused/pending_approval/rejected/expired), source (interactive/job), object_type, object_id, args (redacted), summary, refusal_reason, can_undo, undoable_until, undone_at, decided_at, job_id, created_at`. |
| `POST /v1/copilot/actions/{id}/undo` | Runs the inverse. `200 {action_id, tool, detail}`; `409 copilot_action_changed_since / copilot_action_not_undoable / copilot_action_already_undone`; `404` for anything not yours. |
| `GET /v1/copilot/approvals` | The Approvals inbox: rows with `status = pending_approval` (older than 24 h expire on this read). |
| `POST /v1/copilot/approvals/{id}/approve` | Re-plans against the world as it is now, executes through the button's function, writes the audit row (`approval: true`) and decides the row, in one transaction. Answers `CopilotConfirmOut`; `applied: false` with a sentence when the step no longer applies. |
| `POST /v1/copilot/approvals/{id}/reject` | Declines; nothing runs. |
| `GET /v1/copilot/jobs`, `GET /v1/copilot/jobs/{id}` | Background jobs: `{id, status, goal, screen_route, progress[{at, kind, text, action_id}], result, error_code, created_at, started_at, finished_at}`. |
| `GET /v1/copilot/jobs/{id}/events` | The same job as an SSE stream of `job` frames, ending with `done`. |
| `POST /v1/copilot/jobs/{id}/cancel` | Stops a job before its next step. |
| `GET /v1/admin/copilot/actions`, `POST /v1/admin/copilot/actions/{id}/undo`, `POST /v1/admin/copilot/confirm` | The admin twins. |
| `GET /v1/copilot/approvals/{id}/preview` | What approving would do NOW: the tool's planner re-run on the pending arguments under the person's session — `{title, summary, current, proposed, cost, reversal, still_applies, refusal, expires_at}`. Changes nothing; the inbox shows it before Approve. (`copilot/approval_preview.py`) |
| `GET/POST /v1/copilot/routines`, `PATCH/DELETE /v1/copilot/routines/{id}` | The person's routines: `{name, instruction, schedule: {days: ["mon"..], time: "HH:MM" IST}, enabled}`; at most 20 per person. Switching one on, or changing its schedule, re-derives `next_run_at` from now. |
| `POST /v1/copilot/routines/{id}/run`, `GET /v1/copilot/routines/{id}/runs?limit` | Run once now (the schedule is untouched; `409 copilot_routine_not_started` when the person already has two tasks running), and the run history with each run's task status. |

Limits: an interactive answer keeps `MAX_TURNS` 6, `TOTAL_BUDGET_S` 90 and three immediate
actions (`service.INTERACTIVE_LIMITS`, held under nginx's read timeout by
`deadline_test.py`). A background job runs `service.job_limits`: 16 turns, 240 s, 20
changes; inside it a confirm action is STAGED in the inbox
(`write_tools.stage_for_approval`), never proposed and never run.

## 8. A complete worked example: `lead_set_status`

`apps/api/copilot/write_tools.py`, immediate since D-694.

```python
class _LeadStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_id: UUID
    status: LeadStatus


async def _plan_lead_status(session, actor, args) -> Plan:
    parsed = parse_args(_LeadStatusArgs, args)
    lead = await crm_service.get_lead(session, parsed.lead_id)  # 404 for a neighbour's id
    current = _LEAD_STATUS_LABELS[lead.status]
    proposed = _LEAD_STATUS_LABELS[parsed.status]
    return Plan(
        object_id=str(parsed.lead_id),
        title="Change this lead's status",
        summary=f"Mark this lead as {proposed}. It was {current}.",
        current=current,
        proposed=proposed,
        cost=None,
        reversal=f"Undo puts it back to {current}; you can also change it on the lead's screen.",
        args={"lead_id": str(parsed.lead_id), "status": parsed.status},
    )


async def _execute_lead_status(session, actor, args) -> Executed:
    parsed = parse_args(_LeadStatusArgs, args)
    before = await crm_service.get_lead(session, parsed.lead_id)
    after = await crm_service.update_lead(  # the PATCH /v1/leads/{id} function
        session, parsed.lead_id, status=parsed.status, name=None, actor=str(actor.user_id)
    )
    applied = before.status != after.status
    return Executed(
        applied=applied, detail=..., audit_summary={"to_status": parsed.status, "moved": applied}
    )


async def _capture_lead_status(session, actor, args) -> dict[str, Any]:
    lead = await crm_service.get_lead(session, parse_args(_LeadStatusArgs, args).lead_id)
    return {"status": lead.status}


async def _invert_lead_status(session, actor, record: UndoRecord) -> str:
    lead_id = UUID(str(record.args["lead_id"]))  # ids only from args
    row = (
        await session.execute(
            text("SELECT status FROM leads WHERE id = :lid AND deleted_at IS NULL FOR UPDATE"),
            {"lid": lead_id},
        )
    ).first()  # 1. lock
    if row is None:
        raise UndoRefusedError("that lead has been deleted, so there is nothing to put back")
    if str(row[0]) != record.result_state.get("status"):  # 2. compare
        raise UndoRefusedError(
            "that lead's status has been changed since, so it was left as it is now"
        )
    prior = str(record.prior_state["status"])
    await crm_service.update_lead(
        session, lead_id, status=prior, name=None, actor=str(actor.user_id)
    )  # 3. restore via the button's fn
    return f"The lead is back to {_LEAD_STATUS_LABELS.get(prior, prior)}."  # 4. sentence


LEAD_SET_STATUS = WriteTool(
    name="lead_set_status",
    tier="immediate",
    undo=Undo(capture=_capture_lead_status, invert=_invert_lead_status),
    permission="leads:write",  # PATCH /v1/leads/{id}'s permission
    object_type="lead",
    audit_action="lead.status_set",
    where="on the lead's own screen",
    schema=action_schema(
        "lead_set_status",
        "Change one lead's status (new, contacted, interested, hot, won, lost). The person "
        "can undo it from the receipt." + DOES_IT,
        {...},
    ),
    plan=_plan_lead_status,
    execute=_execute_lead_status,
)
```

What the framework then does with it, without the tool doing anything more:
`run_immediate` checks the permission, claims an idempotency record, plans, captures
`prior_state`, executes, captures `result_state`, writes the `audit_log` row and the
`copilot_actions` row (with `undoable_until` 24 h ahead when `applied`), and emits the
`action` frame with `action_id`. `POST /v1/copilot/actions/{id}/undo` locks that row,
checks it is the caller's, `done` and inside its window, re-checks the permission, runs
`_invert_lead_status`, marks the row `undone` and writes a `copilot.action_undone` audit
row — all in one transaction. Its tests are in `apps/api/copilot/undo_test.py`.

## 9. Routines (`copilot/routines.py`)

A routine is a standing instruction with a schedule in IST (`copilot_routines`, migration
`d3a7f5c19e42`). It adds no gate and no tool of its own:

* **A due slot becomes an ordinary background job.** `workers/copilot_routines.fire_due_routines`
  runs every minute at :30s, reads the due routines in one untenanted query (the table's
  `copilot_routines_ops_read` policy), and fires each in its own tenant session with
  `routines.fire_due`: lock the routine `SKIP LOCKED`, claim the slot in
  `copilot_routine_runs` (unique on `(routine_id, slot_at)`), `jobs.create_job` through the
  outbox, advance `next_run_at` — one transaction.
* **So it meets every gate a typed request meets**: the fair-use cap and the platform brake
  in the job worker, the permission ladder re-read when the job starts, and calling hours,
  DNC, KYC and the pledge, credit, the trial rules and the big red switch inside the
  service functions the actions call. A confirm-tier step is STAGED in the Approvals inbox;
  nothing irreversible runs unattended. A new dial or spend gate belongs in the service
  function the button calls, never in a route — that is what makes it reach routines too.
* **A slot is skipped, not fired, and the run says why** when the author has left the
  account (the routine is switched off), already has two tasks running, or the tick reached
  the slot more than an hour late (`routines.LATE_LIMIT`; a 9 am routine is not run at 4 pm).
* Alarms: `copilot_routines_tick_failed`, `copilot_routine_fire_failed`
  (`runbooks/alarm-index.md`). Tenant erasure deletes both tables.

## 10. Script suggestions (`copilot/script_actions.py`, D-820)

Pip is the one AI assistant: AI help that a person asks for on a screen is a Pip ability
reached by a "Let Pip do it" button that prefills the ask box (`AskAssistant`), with the
review kept on the screen where the result lands. The Script page's helper panel is the first
one moved; `agent_script_suggest` is its tool.

* **Confirm tier**, permission `org:manage` (the Script page's own), object `agent`, audit
  action `agent.script_assist`. It spends the AI allowance, so it is not `immediate` under
  §1, and it reaches no caller.
* **Arguments**: `agent_id`; `mode` — `change` (one change, `change` = the person's words),
  `whole` (the whole script from `answers`, the five `script_assist.OWNER_QUESTIONS`; the
  description tells Pip to ask them together first, and each answer must be the person's own
  words, §14), `steps` (a hand-written script turned into steps). Unused arguments are null;
  the canonical arguments drop them, strip invisible characters and cap each text at 600
  characters.
* **Planner refusals** (`WriteRefusedError`): steps asked of a stepped script, a change or a
  whole draft asked of a hand-written one, fewer than 10 characters of request
  (`script_proposals.MIN_REQUEST_CHARS`), or a request still being written for this agent.
  Then `require_ai_assist` — a refusal there (used up, paused) is a `ProblemError` Pip
  relays before any card. The deleted-agent and view-as refusals are the framework's (§3).
* **Executor**: `require_ai_assist` again, then `script_proposals.request_proposal` records
  the request on `agents.script_proposal` with the script it is made from and queues
  `draft_script_proposal` in the same transaction. It never writes the draft.
* **The job** (`workers/script_proposal.py`) claims the request once, writes it with
  `script_assist.draft_script` (repair, ladder, disclosure unchanged), meters every paid leg
  under `script_draft`, and stores the suggestion or a failure note; every write after the
  request is a compare-and-set on the request's id.
* **Review** is the Script page's: `GET /v1/agents/{id}/script/proposal` (`agents:read`)
  and `DELETE /v1/agents/{id}/script/proposal/{proposal_id}` (`org:manage`, after keeping or
  to discard). Tests: `apps/api/copilot/script_actions_test.py`; tool choice: the
  `c-script-*` cases in `tests/fixtures/copilot_tool_choice.json`.
* **`agent_tests_fix`** is the Test section's "Improve my agent" / "Suggest a fix for this",
  moved the same way: confirm tier, `org:manage`, audit `agent.tests_improvement`,
  arguments `agent_id` and `test_keys` (null for every failure; keys from the screen's
  `failed_tests` fact). The planner resolves the latest finished run and signs its id into
  the canonical arguments, refuses unknown keys, a run with nothing to fix or one already
  being worked out, then asks the allowance; the executor runs
  `test_conversations.request_improvement` (the queued job, D-748). Review stays in
  `ImprovementReview`.

## 11. The remaining helpers (`copilot/assist_actions.py`, D-821)

Every AI request a person makes on a client screen is now asked of Pip. The screens keep only
"Let Pip do it" buttons that prefill Pip and the review of what comes back.

| Tool | Tier, permission, audit | Executor (the old button's function) | Review |
|---|---|---|---|
| `knowledge_teach` | confirm, `kb:write` (curation switch included), `kb_teaching.start` | `teach/teaching.start_teaching` (text); Pip passes the words of a photo or file the person attached | the teach box on Knowledge base, through `GET /v1/kb/teach/open` |
| `lead_fields_draft` | confirm, `org:manage`, `lead_fields.draft_requested` | `agents/lead_fields.request_draft` (absorbed cost, no allowance gate, as before) | Lead details: `POST /v1/lead-fields/draft/review {keep}` writes the kept fields onto agents with none |
| `call_summarise_again` | confirm, `org:manage`, `call.ai_assist`, `external_spend` | `crm/resummarise.second_reading`: redacted transcript, allowance gate, metering under `resummarise` | the confirmation itself; nothing is stored |
| `business_copy_refresh` (D-827) | confirm, `org:manage`, `organization.business_copy_refresh_requested` | `tenancy/business_copy.queue_generation` after `require_ai_assist`; the worker meters by tokens under `business_copy` | none: the examples replace only the AI's earlier ones, and the Business profile screen shows when they were refreshed |

* **Planner refusals.** Teach: empty words, an unknown `gap_id`. Lead fields: a business type
  with standard details, a draft queued or running, a draft already made. Second reading: the
  call (404), no transcript or a turn without a redacted copy, then `require_ai_assist`, all
  before a card. Examples refresh: a run already in progress; the allowance is checked at the
  confirm, so a person at the ceiling meets the ceiling notice.
* **`Executed.recorded`.** What the activity log keeps instead of `detail` when `detail` holds
  content it must not (the second summary). The confirmation shows `detail` once.
* **`ActionTool.external_spend`.** The executor pays a provider before it returns. `confirm`
  then keeps the token spent if anything after the executor fails (the money did not roll back),
  and `stage_for_approval` refuses the tool, so a background task never stages it.
* **The ceiling.** A Confirm refused with `ai_quota_exceeded` opens the panel's wallet notice
  (`ProposalCard.onCeiling`), the same one an ask refused there opens.
* **Retired:** `POST /v1/kb/teach`, `POST /v1/kb/teach/{id}/words`, the photo and file kinds of
  `POST /v1/kb/teach/upload` (a voice note is still heard there and its words return to the
  teach box), the client `POST /v1/lead-fields/draft` (the operator's twin stays) and
  `POST /v1/calls/{id}/assist`. Tests: `apps/api/copilot/assist_actions_test.py`,
  `tests/call_assist_test.py`, `tests/lead_fields_test.py`, `tests/teach_loop_test.py`.
* **Left where it is, and why.** The English "Try again" retries a background step. Test runs,
  saved tests and Try chat test the agent itself. The operator's lead-details draft and
  business-type "Suggest again" are admin console controls. "Make this call a test" uses no AI
  and was left here too, until D-822 moved it to Pip for one entry point (§12).

## 12. Making a call a test (`call_test_prepare`, D-822)

"Make this call a test" is asked of Pip, and the call page's form is where the result is
reviewed. No model is called, so nothing is metered and no allowance is checked.

| Tool | Tier, permission, audit | Executor | Review |
|---|---|---|---|
| `call_test_prepare` | immediate with Undo, `agents:write` (the save route's), `agent_test_case.prepared` | `teach/test_cases.write_pending`: one row in `call_test_case_drafts` per call and person, holding only `expected` and `title` | the call page's "Make this call a test" form opens filled in; the person saves it through `POST /v1/calls/{call_id}/test-case` or discards it (`DELETE /v1/calls/{call_id}/test-case-draft/pending`) |

* **Why immediate.** It saves no test, reaches no caller and spends nothing; the form's Save is
  the click. Undo restores what the form held before (or empties it), and refuses once the
  form was saved, discarded or prepared again (compare and swap on `expected` and `title`).
* **Planner refusals.** A call this person cannot see or one erased (404), a call where the
  caller said nothing, an agent that already keeps 20 saved tests.
* **What is stored.** Not the caller's lines: the form reads them redacted from the call
  (`draft_from_call`) as it always did. `GET /v1/calls/{call_id}/test-case-draft` adds
  `pending`. Saving the form deletes the row; subject and tenant erasure delete it
  (`workers/retention.py`).
* **Not retired.** The GET and POST routes are the review form's own reads and save.
* Tests: `tests/call_test_prepare_test.py`, `apps/api/copilot/assist_actions_test.py`, web
  `teachLoop`.

## 13. The latest message, the present screen, and how fills are kept (D-832)

* **Only the latest message is a request.** History replays text only (no fill, proposal or
  confirm is in it), so an earlier "I am drafting your script" is the last thing Pip would
  otherwise know. The client prompt and both realms' closing rules say: act only on the latest
  message; a "yes" or "thanks" with a new question answers that question; a question about
  how Pip talks (a language, shorter replies) changes nothing on the screen; where an earlier
  turn and the SCREEN STATE disagree, the screen is current. Tool-choice cases may carry a
  `history` (`c-talk-language-after-kept`, `c-script-after-kept`, `c-talk-language`).
* **A screen states the present.** A screen whose state can move under the conversation
  declares it as facts. The Script tab sends `pip_suggestion` (none waiting / kept into the
  draft / being written / waiting for review / could not be written) and `draft` (saved as a
  draft, not live until "Put it live", or why it is not saved), from `scriptSurface.
  scriptCopilotFacts`.
* **How fills are kept.** `CopilotScreen.saves` is `button` (held until the screen's save
  button; the default when a surface does not say), `autosave` (kept as a draft at once;
  `live_step` names the control that puts it live), `immediate` (each change saved as it is
  made) or `view` (a filter). The browser sends it only when the screen has a writable field
  (`lib/copilot/keeping.ts`), the prompt renders it on `<screen>`, and the panel's notices
  read it (`filledNotice`, `panelNotice`). Script tab: `autosave`. Lead page: `immediate`.
  Filters (calls, leads, callbacks, billing, performance, quality, attention, lead sources,
  admin alerts, reply times, QA queue): `view`. Every other filling screen: `button`.
* **Lines callers hear.** `CopilotField.spoken_language` marks one (the Script tab's opening
  line and each step's example line). `service.spoken_line_problem` refuses a fill of it that
  uses a word from the language's spoken-style list (`turn_checks.formal_swaps`, the test
  loop's own check), naming the word and what people say; a word the field already held or
  the person typed is theirs and passes. The refusal goes back to the model like any refused
  fill. Pip's chat replies are never checked.

## 14. A request rests on the person's own words (D-833)

* **The screen is already last.** The per-request SCREEN STATE, live block, attachments,
  closing rules and question are one user message after the replayed history
  (`prompt.build_messages`, `admin_prompt.build_admin_messages`). The system prompt and tool
  array come first and are the same bytes on every request of a surface, which is the
  implicitly cached prefix (`prompt_budget_test`). Nothing per-request sits in it.
* **A fill quotes the latest message.** `set_fields` takes `because` before `items`: the
  words of the person's latest message that ask for the fill, copied exactly.
  `service.validate_fill` refuses the whole call when `because` is not a run of whole words
  of `payload.question` (`quotes.quoted_in`: NFKC, casefold, invisibles out, punctuation and
  symbols by Unicode category to spaces). The refusal (`UNQUOTED_FILL_REASON`) goes back to
  the model like any refused fill. It works in any language and accepts a bare answer to
  Pip's own question ("10 to 8, closed on Sundays"). It cannot tell whether the quoted words
  ask for a change; it stops a fill that rests on an earlier, answered request.
* **An action may declare `grounded`.** `ActionTool.grounded(arguments, said)` checks the
  model's arguments against the person's messages in this conversation
  (`service.person_said`: the user turns of the history, then the question). `plan_write`
  and `stage_for_approval` run it, given `said`, after the permission and deleted-agent
  checks and before the planner; the loop always passes `said`. An approval re-plans with
  no conversation and does not run it: the person's click on a card that showed the
  arguments is their own word. `write_tools.grounding_problem` is the pure form the
  tool-choice eval asks.
* **`agent_script_suggest` mode `whole`** is grounded: at least one answer, and each answer
  copied from the person's words. Otherwise it is refused with "ask the person the five
  questions" (`script_actions._whole_rests_on_the_owner`). Modes `change` and `steps` are not
  held to exact words.
* **Only these two.** The other write tools carry no `because`: each is either a confirm
  card the person clicks or an immediate act with an Undo shown in the panel, and a quote
  argument on every write schema would push the client prefix past its budget
  (`prompt_budget_test.PREFIX_BUDGET_TOKENS`).
* **The eval reports what the server refuses.** `scripts/copilot_tool_eval.py` scores the
  model's first-turn choice as before, and puts each call through these database-free
  checks: a wrong call the server refuses is listed `refused_by_server` and counted on the
  "refused by the server, reaching nobody" line.

## 15. A screen that leads the conversation (D-854)

* **Per-screen guides ride the last user message.** `copilot/screen_guides.screen_guide(route)`
  returns Calevate's own instructions for a screen built around a chat with Pip, and
  `prompt.build_messages` places it after the live block and before the closing rules. It is
  trusted text, so it is never sent as SCREEN STATE, and it is per-screen, so it never enters
  the cached prefix. Today only `/c/{slug}/agents/first` has one.
* **The first-agent tools.** `agent_create` takes `job` (`answer_calls`, `call_new_leads`,
  `call_leads`, or null; `answer_calls` with direction `both` is widened after the starter is
  written). Since D-855 the chat is "Talk it through with Pip instead" inside "Meet your
  agent", not a door of its own.
  `agent_edit` and `agent_edit_live` take `opening_line`, applied through
  `script_builder.replace_opening_line` (D-846's budget) and checked against the language's
  spoken-style list; the Undo puts the previous line back. `knowledge_facts_pin`
  (`fact_actions.py`, confirm, `kb:write`) pins up to three question and answer pairs on one
  card through `teach/pinned.add_pinned`.
* **Screens learn of an immediate action as it lands.** `useCopilotConversation` refreshes
  the queries in `lib/api/copilot.INVALIDATES` when an `action` frame arrives, as a confirm
  already did, so a card built from those reads ticks without a reload.

## 16. The agent page's remaining buttons (D-893, lane L4)

Every agent button a client can press is now also a Pip action, calling the button's own
service (`copilot/agent_setup_actions.py`, `copilot/agent_tool_actions.py`). Where the logic
lived in a route body it moved into a service both doors call.

| Tool | Tier, permission, audit | Service (the button's) |
|---|---|---|
| `agent_restore` | immediate, `org:manage`, `agent.restored` | `lifecycle.restore_agent`; Undo archives again while the agent is still paused with no number given to it (`ActionTool.acts_on_archived` exempts it from the deleted-agent refusal) |
| `agent_prepare` | confirm, `org:manage`, `agent.prepared` | `lifecycle.prepare_agent` ("Get it ready") |
| `agent_script_put_live` | confirm, `org:manage`, `agent.script_published` | `agents/script_publish.put_draft_live`, bound to the draft's `saved_at` and the version the card read |
| `agent_script_discard` | confirm, `org:manage`, `agent.changes_undone` | `publishing.undo_staged` |
| `agent_script_version_restore` | confirm, `org:manage`, `agent.script_version_restored` | `script_builder.restore_into_draft` |
| `agent_settings_set` | confirm, `agents:write` (owner settings also need `org:manage`, checked inside), `agent.settings_set` | `voice_tuning.set_voice_tuning`, `call_handling.set_agent_call_handling`, `publishing.set_call_cap`, `llm_tiers.resolve_agent_tier` + `lifecycle.update_agent`, `publishing.set_caller_memory` |
| `agent_handover_set` | confirm, `org:manage`, `agent.handoff.replace` | `handoff.replace_handoff` |
| `agent_action_set` / `_switch` / `_remove` | confirm, `org:manage`, `action_tool.saved` / `.switched` / `.deleted` | `actions/agent_tools` (each re-syncs a live agent's actions) |
| `lead_fields_keep_draft` | confirm, `org:manage`, `lead_fields.draft_reviewed` | `agents/lead_fields_writes.keep_draft` |
| `lead_fields_reset` | confirm, `org:manage`, `lead_fields.replaced` | `agents/lead_fields_writes.replace_with_standard` |
| `lead_suggestion_answer` | confirm, `org:manage`, `agent.lead_suggestion_answered` | `field_suggestions.accept` / `.dismiss` |

* **The read is `agent_settings`** (`copilot/agent_reads.py`, `agents:read`) with a `part`:
  `settings`, `script`, `handover`, `actions`, `lead_fields`. One schema instead of five keeps
  the prefix small. The hand-over part names people and their contact ids, never a number.
* **`agent_settings_set` takes `changes: [{setting, value}]`**, values as words (`on`/`off`,
  numbers, `default` to follow the account or the voice). Each value is parsed and checked by
  the writer's own range check while the card is drawn; volume and emotion are refused on a
  voice that is not Studio. AI model is a tier, so only `offerable_models()` can be chosen
  (`resolve_tier_choice`).
* **Never through Pip:** connecting an account (keys, OAuth), and switching caller memory on
  before the owner has confirmed its statement on the Settings tab — the planner refuses and
  sends the person there; `set_caller_memory` is always called with `attested_by=None`.
* **The prefix budget** rose to 25,100 tokens (with §17) while each action is its own tool;
  `docs/PIP-AGENT-PLAN.md` §3 F1's area tools replace the per-tool array.
* Tests: `copilot/agent_setup_actions_test.py`, `copilot/agent_tool_actions_test.py`; tool
  choice: the `c-agent-*`, `c-script-put-live`, `c-script-discard`, `c-script-version`,
  `c-lead-*` cases.

## 17. The account's own settings (D-893 lane L6, `copilot/account_actions.py`)

| Area | Tools (tier) | The button's function |
|---|---|---|
| numbers | `number_assign` (confirm), `forwarding_line_add` (confirm, code), `forwarding_line_change` (immediate), `forwarding_line_remove` (confirm), `forwarding_line_test` (confirm, code) | `number_catalog.assign_number_to_agent`, `forwarding.service.create_line` / `update_line` / `delete_line`, `forwarding.testing.start_test` |
| team | `team_invite` (confirm; code for an owner), `team_member_role` (confirm; code to make an owner), `team_member_remove`, `team_invitation` (resend or cancel) | `tenancy.members.send_team_invitation`, `change_member_role`, `remove_member`, `resend_and_mail_invitation`, `revoke_invitation` |
| settings | `line_protection_phone`, `lead_source_create`, `lead_source_edit` (immediate), `lead_source_switch` (immediate), `lead_source_rotate`, `lead_calling_rules`, `held_lead_decide` | `healer.protection.set_fallback_phone` / `clear_fallback_phone`, `ingest.service.create_lead_source` / `set_source_agent` / `set_active` / `rotate_secret`, `lead_policy.save_and_apply` / `release_held` / `drop_held` |
| integrations | `crm_endpoint_create` (confirm, code), `crm_endpoint_edit`, `crm_endpoint_act` (switch off, new secret), `crm_delivery_resend` | `integrations.service.create_webhook_endpoint` / `update_endpoint` / `deactivate_endpoint` / `rotate_endpoint_secret` / `resend_delivery` |
| billing | `spend_caps_set`, `auto_recharge_set`, `low_balance_alert_set` (immediate), `ai_allowance_extra` | `caps.apply_client_caps`, `auto_recharge.save_auto_recharge`, `billing.service.set_low_balance_line`, `ai_quota.purchase_ai_overage` |

Unmarked tools are confirm. Reads: `numbers_list` (numbers, forwarded numbers, calls at once,
backup phone), `team_members` (with pending invitations), `integrations_status` (lead sources,
the lead-calling plan, held leads, endpoints, Google Sheets connection, failed deliveries, each
with its id) and `billing_settings`.

* **Never here (PIP-AGENT-PLAN §1).** No payment, top-up order or payment-method approval;
  `auto_recharge_set` refuses to switch on without a method the person approved on Credits &
  billing. Connecting Google is the person's own sign-in; Pip only says whether it is connected.
* **Secrets are shown once, to the person.** A new lead source, endpoint or rotated secret goes
  in `Executed.detail` (the confirming person's response) and never in `recorded`, the audit
  summary or a Plan.
* **The emailed code (D-730).** `ACCOUNT_CODE_ACTIONS` names each tool whose button needs a code
  and builds its exact `X-Confirm-Action` (`add_forwarded_number:<slug>`,
  `forwarding_test:<slug>`, `invite_owner:<slug>:<email>`, `promote_owner:<slug>:<user id>`,
  `create_endpoint:<slug>`). While `CODE_GATE_ON_CONFIRM` is false (until Pip's confirm can ask
  for the code, PIP-AGENT-PLAN F4) those planners refuse and name the screen.
* **Areas.** `ACCOUNT_TOOL_AREAS` maps each tool to its area for the F1 facade.
* Tests: `apps/api/copilot/account_actions_test.py`, `tests/account_settings_routes_test.py`;
  tool choice: the `c-number-*`, `c-forwarding-*`, `c-team-*`, `c-invite-*`, `c-backup-phone`,
  `c-source-*`, `c-calling-hours`, `c-held-call`, `c-endpoint-off`, `c-delivery-resend`,
  `c-sheets-connected`, `c-spend-cap`, `c-low-alert`, `c-auto-recharge-off` and
  `c-topup-refused` cases.

## 18. Knowledge and training actions (D-893 lane L5, `copilot/question_actions.py`, `TRAINING_ACTIONS`)

| Tool | Tier, permission, audit | Executor (the page button's function) |
|---|---|---|
| `knowledge_questions` (read) | `calls:read` | `teach/questions.list_questions`, never queuing a draft |
| `knowledge_question_settle` | confirm, `kb:write` with curation, `teach_question.answer` | `questions.answer_question`; `answer` null is `dismiss_question` |
| `knowledge_fact_change` | confirm, `kb:write`, `kb_fact.edit` | `facts.update_fact` (edit, pin, unpin), `facts.remove_fact`, `pinned.reorder` (move) |
| `agent_tests_run` | confirm, `org:manage`, `agent.tests_requested` | `test_conversations.request_run` after `require_ai_assist`; `again` signs the latest finished run as `retest_of` |
| `agent_test_add` | immediate with Undo, `agents:write`, `agent_test_case.create` | `test_cases.create_case`; Undo deletes the test unless it is running |

* **Why confirm.** An answer or a changed fact is said to callers by every live agent on its
  next call, and a sentence said to a caller cannot be taken back (the reason
  `knowledge_facts_pin` is confirm). A test run spends the AI allowance.
* **Questions are keyed by topic** (`pricing`, `timings`, a phrase-derived `q_...`), the
  same word in every account, so answering closes every agent's open gap on that topic.
* **`knowledge_sources` lists facts** by their `fact:<id>` reference, which `knowledge_fact_change` takes as `fact_id` (a bare id works too).
* **Budget.** Adding these five without raising `PREFIX_BUDGET_TOKENS` cut the
  `PROPOSES_ONLY` and `DOES_IT` suffixes (repeated on every action) to their meaning and
  shortened the knowledge and training siblings' descriptions.
* Tests: `apps/api/copilot/question_actions_test.py`, `tests/teach_questions_test.py`; tool
  choice: the `c-question*`, `c-fact-*`, `c-tests-run` and `c-test-add` cases.
