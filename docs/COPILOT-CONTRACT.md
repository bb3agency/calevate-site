# The assistant's tool contract

How to add a tool to the in-app assistant (the copilot). Every Phase 2 lane follows this
exactly. The decision behind it is D-694 (docs/ROADMAP.md §6); the code it describes lives
in `apps/api/copilot/`.

A tool is one of four kinds. Pick the kind first; everything else follows from it.

| Kind | What it does | Where it is registered | Runs |
|---|---|---|---|
| **Read** | Looks something up. Changes nothing. | `tools.py` `READ_TOOLS` or `console_reads.py` `CONSOLE_READ_TOOLS` (client; composed in that order by `service.realm_read_tools`), or `admin_tools.py` `ADMIN_READ_TOOLS` | at once, many per turn |
| **Immediate action** | A reversible change that reaches no caller and spends nothing. | `write_tools.py` `WRITE_TOOLS` or a module joined into it (`agent_actions.py`, `console_actions.py`) | at once, with an Undo |
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

The tool array is **byte-identical within a realm** (prompt caching): never add, remove or
reorder a tool by screen, tenant or role. New tools APPEND to their registry. Permission is
checked inside:

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
