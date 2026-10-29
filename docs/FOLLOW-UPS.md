# Follow-ups (D-940): per-lead journeys, built by Pip, run through our own gate

A Follow-up takes one lead at a time through steps the client chose: call them, read how the
call went, wait, send a WhatsApp, call again, hand them to a teammate, tell the team, push
them to the CRM. Each lead goes through on its own, and the client can see where each one is.

## Why our own engine, not ThinnestAI's Workflows

ThinnestAI shipped Workflows on 28-29 Oct 2026
(`thinnest-findings/mirror/snapshots/2026-10-29/pages/agent/workflows.md`). We use none of
its engine, for four reasons:

1. **Its builder is in ThinnestAI's console only.** The API can list, read, start a run and
   send an event (`api-reference/workflows/*`); it cannot create or change a workflow. Our
   clients never see ThinnestAI (D-679).
2. **Its calls are placed by ThinnestAI, not by us**, so they would skip `check_dispatch`
   (hard rule 5): KYC, the no-cold-calls pledge, the credit stop, the big red switch,
   holidays, our concurrency pool and trial limits.
3. **Its WhatsApp needs the client's WhatsApp connected inside ThinnestAI.** Ours is the
   client's own number through our Meta Tech Provider set-up (D-784). Its SMS needs DLT, and
   messaging is WhatsApp only (D-700).
4. **Its CRM and calendar connections duplicate ours** (D-700).

We build the same idea out of what we already run: the gate, `dispatch_call`, the call-back
dial path, the post-call outcome, the client's WhatsApp, after-call actions and team alerts.

## Founder decisions (30 Oct 2026)

| # | Decision |
| - | - |
| 1 | Our own engine; every call through `check_dispatch` + `dispatch_call`. |
| 2 | Version 1 triggers: a new lead arrives, a call ends, leads the client picks, a date on the lead. |
| 3 | Pip builds a Follow-up from a sentence. No canvas in version 1. |
| 4 | Without Pip the client can make small edits: change a wait, a WhatsApp template or the calling agent, remove a step, pause, resume, turn off. Bigger changes: "Ask Pip to change it". |
| 5 | Paying and trial accounts alike. A trial's limits are the gate's (`TRIAL_DIAL_REFUSALS`, trial minutes). |
| 6 | "How did the call go" uses OUR call outcome (the agent's business outcomes, D-836; `derive_outcome`, D-718). No extra model call. |
| 7 | The fixed new-lead plan's call part (agent, wait, retries, D-716) is retired into a ready-made **Call new leads** Follow-up for every client, with identical behaviour. The calling hours, days, holidays, after-hours choice and the answering-machine switch stay on **Leads & hours** as the account's calling hours, which every Follow-up call keeps to. |

## What a Follow-up is

```
follow_ups            one per journey; trigger, settings, status, the live version
follow_up_versions    the steps, frozen at publish (INSERT-only); runs keep their version
follow_up_runs        one lead going through one version
follow_up_run_events  what happened at each step (INSERT-only), ids and short codes only
```

Every table carries `tenant_id` with FORCEd RLS and a cross-tenant zero-rows test (hard rule 1).
No column holds a phone number except `follow_up_runs.phone_e164` (the number the run calls,
needed when a run has no lead row yet); nothing holds transcript text or message bodies.

### `follow_ups`

| column | |
| - | - |
| `id`, `tenant_id` | uuid7 |
| `name` | up to 80 characters |
| `status` | `draft` · `live` · `paused` · `off` |
| `trigger` | jsonb, see Triggers |
| `settings` | jsonb, see Settings |
| `draft` | jsonb: the steps being edited, NULL when equal to the live version |
| `live_version_id` | FK `follow_up_versions`, NULL until first publish |
| `starter` | NULL or the ready-made key it came from (`call_new_leads`, ...) |
| `created_by`, `created_at`, `updated_at` | |

`live` and `paused` require `live_version_id`. At most one `live` Follow-up per tenant may have
the `new_lead` trigger for a given lead source (or "any source"); publish refuses an overlap
(`follow_up_trigger_overlap`), because a lead is never started twice by two Follow-ups.

### `follow_up_versions` (INSERT-only)

`id, tenant_id, follow_up_id, number (1, 2, ...), steps jsonb, trigger jsonb, settings jsonb,
published_by, published_at`. Publishing writes a new row; a run started on version 3 finishes on
version 3.

### `follow_up_runs`

| column | |
| - | - |
| `id`, `tenant_id`, `follow_up_id`, `version_id` | |
| `lead_id` | the lead (NULL only for a call-ended trigger whose caller has no lead yet: the run makes one before its first step, as the pipeline already does) |
| `phone_e164` | |
| `status` | `running` (a step is executing) · `waiting` (for a time or a call) · `done` · `stopped` |
| `step_id` | the step it is on |
| `wake_at` | when a waiting run is due (a wait ending, a retry) |
| `waiting_call_id` | the call it is waiting to end |
| `attempt` | tries of the current call step |
| `trigger_ref` | what started it: the lead source delivery, the call id, the date (`visit_date:2026-11-02`), or the manual start's id |
| `started_at`, `ended_at`, `end_reason`, `goal_reached` | |

Unique: one run per (`follow_up_id`, `lead_id`) while `status IN ('running','waiting')`
(nobody is in the same Follow-up twice at once); unique (`follow_up_id`, `lead_id`,
`trigger_ref`) so a date or a call starts a lead once.

`end_reason`: `finished`, `goal`, `stopped_by_client`, `follow_up_off`, `do_not_call`,
`lead_won`, `lead_lost`, `replied`, `max_days`, `lead_erased`, `refused:<rule>` (a gate
refusal that will never clear, e.g. `kyc_missing` is NOT one: it retries; `dnc` is).

### `follow_up_run_events` (INSERT-only)

`id, tenant_id, run_id, step_id, kind, result, call_id NULL, at`. `result` is a short code
(`answered`, `no_answer`, `busy`, `blocked:dnc`, `sent`, `not_sent:no_consent`,
`branch:interested`, ...). Never a phone number, a name or text the caller said.

## Triggers

`trigger` is one of:

| kind | fields | starts when |
| - | - | - |
| `new_lead` | `source_ids: [uuid] \| null` (null = any source) | `ingest_lead` stores a lead |
| `call_ended` | `agent_ids: [uuid] \| null`, `calls: "inbound" \| "outbound" \| "both"`, `outcomes: ["missed", "answered", ...] \| null` | the post-call pipeline finishes a call (test calls never) |
| `manual` | — | the client (or Pip, through an approved plan) starts picked leads, a leads lens or a campaign's contacts |
| `lead_date` | `field` (a lead detail holding `YYYY-MM-DD`), `offset_days` (-30..30), `at` (`HH:MM` IST) | the date falls due; once per lead per date |

Only if: `only_if` (optional) narrows any trigger by lead status, lead source or a lead detail
equal to a value.

## Steps

`steps` is an ordered list; each step has an `id` (short, stable, `s1`, `s2`, ...), a `kind`
and its own fields, and says where to go next. A step with no `next` ends the run as
`finished`.

| kind | fields | exits |
| - | - | - |
| `call` | `agent_id`, `wait_minutes` (0..1440, before the first try), `retries` (0..3), `retry_minutes` (15..1440) | `answered`, `not_reached` (every try ended without an answer) |
| `decide` | branches on the call this run last placed (or, for `call_ended`, the call that started it): `on: {<outcome key>: step_id}` over the agent's business outcomes, plus `other` | one per outcome named, `other` |
| `wait` | `minutes` / `hours` / `days`, or `until_field` + `offset_days` + `at` | `next` |
| `whatsapp` | `template_id` (one of the client's approved templates), `values` (each blank: a lead field, the agent name, the business name, or fixed text) | `sent`, `not_sent` (no consent, blocked, not connected) |
| `assign` | `user_id` (a teammate) | `next` |
| `set_status` | `status` (`contacted`, `interested`, `hot`, `won`, `lost`) | `next` |
| `tell_team` | `contact_id` (NULL = the account default), `why` (up to 120 characters) | `next` |
| `action` | `action_id` (one of the agent's after-call actions: CRM push, custom API, sheet), run for this lead | `done`, `failed` |
| `end` | `goal: bool` | — |

Each exit names a step id or `null` (end). Version 1 has no loops back to an earlier step
except `call` retries, so a run always ends: the longest path is bounded by the step count,
and `settings.max_days` (default 14, at most 30) ends anything still waiting.

### How a step runs

* **`call`**: books a `scheduled_callbacks` row with `source_execution_id` =
  `follow-up:<run_id>:<step_id>:<attempt>`, due `now + wait_minutes` (moved to the account's
  next opening by the existing `align` logic). The call-back tick dials it through
  `check_dispatch` and `dispatch_call` exactly as every call-back is dialled, so every refusal,
  busy line, uncertain dial and calling-hours deferral is handled by code that already
  exists. The run waits on the call. The post-call pipeline, on finishing a call whose
  call-back row carries a `follow-up:` key, advances the run with the call's outcome. Not
  answered and tries left: another call-back after `retry_minutes`. A dial refused for good
  (`ENGINE_PERSON_REFUSALS`, DNC, opted out) ends the run `do_not_call`; a refusal that clears
  (hours, lines, halt) is the call-back's own deferral.
  **A new lead's first call stays inline in `ingest_lead`** when the first step is a `call`
  with `wait_minutes = 0`: speed-to-lead is the product, and that path's hardening (stale
  submissions, consent, uncertain dials, busy lines) is kept as it is. The run is created in the
  same transaction and `book_retry`'s job becomes the run's retry.
* **`decide`**: reads `calls.outcome` / the business outcome the pipeline stored for that call
  (and the ThinnestAI insight outcome when present). An outcome not named goes `other`.
* **`whatsapp`**: `crm.lead_message.send_lead_whatsapp` (gate, consent, idempotency key
  `follow-up:<run_id>:<step_id>`), as the system actor `follow-up:<follow_up_id>`.
* **`assign`**, **`set_status`**: `crm.service.set_lead_assignee` / `set_lead_status`, audited
  as the follow-up.
* **`tell_team`**: `team_alerts` delivery (email or the client's own WhatsApp), keyed on the run
  and step so a retry never alerts twice.
* **`action`**: the after-call action executor (`actions/execution.execute_action`) for this
  lead's latest call.

Every step is idempotent on (`run_id`, `step_id`, `attempt`): a worker retry finds the event
row and moves on.

## Stopping

A run stops (`stopped`, with the reason) when:

* the lead or number is added to the do-not-call list or opts out (the DNC addition path stops
  that number's runs before the next dispatch tick, as it already cancels call-backs);
* the lead is marked won or lost (unless the run itself set it, and then only after its step);
* the lead replies on WhatsApp, when `settings.stop_on_reply` (the WhatsApp webhook records that
  a message arrived from that number; it never stores the text);
* the client pauses (runs wait where they are), turns the Follow-up off (runs stop) or stops
  one run;
* `settings.max_days` passes;
* the lead or the account is erased.

## Settings

| key | default | |
| - | - | - |
| `goal` | NULL | an outcome key; a run whose `decide` lands on it, or an `end` with `goal: true`, counts as reached |
| `stop_on_reply` | true | |
| `stop_on_won_lost` | true | |
| `again` | `after_last` | `never` · `after_last` · `after_30_days`: can a lead go through it again |
| `max_days` | 14 | 1..30 |
| `starts_per_hour` | NULL | a cap; the rest wait their turn |

Calling hours are not a Follow-up setting: every call keeps to the platform window, the
account's **Leads & hours** and the campaign-free gate, and every WhatsApp to the gate.

## Ready-made Follow-ups (starters)

| key | trigger | steps |
| - | - | - |
| `call_new_leads` | new lead, any source | call (the account's calling agent, wait, retries from the old plan) |
| `qualify_new_leads` | new lead | call → decide: interested → assign + tell team; call back → wait 1 day → call; not interested → set lost; not reached → WhatsApp "we tried to reach you" |
| `missed_call_callback` | call ended, inbound, missed | wait 5 minutes → call → decide |
| `appointment_reminder` | lead date `visit_date`, -1 day, 10:00 | WhatsApp reminder → wait 3 hours → call |
| `payment_reminder` | lead date `due_date`, -2 days, 11:00 | WhatsApp → wait 1 day → call |
| `win_back` | manual | call → decide → WhatsApp |

## The migration of the new-lead plan

For every organisation, one `call_new_leads` Follow-up, `live`, version 1, with
`call.agent_id = lead_call_policies.calling_agent_id` (or the account's default calling agent),
`wait_minutes = ceil(wait_seconds / 60)`, `retries = retry_attempts`,
`retry_minutes = retry_interval_minutes`. An organisation with no plan row gets the default
plan's behaviour (call at once, no retries). `wait_seconds` below a minute keeps its seconds:
the step stores `wait_seconds` too, and `ingest_lead` honours it exactly as before.

`lead_call_policies.calling_agent_id`, `wait_seconds`, `retry_attempts`,
`retry_interval_minutes` stop being written in this release and are dropped in a later one
(hard rule 8). The hours, days, holidays, after-hours choice and `detect_machines` stay.

Turning **Call new leads** off means new leads are stored and not called, and **Leads & hours**
says so with a button to turn it back on.

## HTTP contract (`/v1/follow-ups`, client realm)

Permissions: read `leads:read`; create, edit, publish, pause, resume, turn off, start, stop a
run `leads:dispatch`. View-as: reads allowed; writes follow `rbac.withheld_from_view_as`.

| method | path | body / answer |
| - | - | - |
| GET | `/v1/follow-ups` | `FollowUpListOut {items: [FollowUpSummaryOut]}` |
| POST | `/v1/follow-ups` | `FollowUpCreateIn {name, trigger, steps, settings?, starter?}` → `FollowUpOut` (status `draft`) |
| GET | `/v1/follow-ups/{id}` | `FollowUpOut` |
| PATCH | `/v1/follow-ups/{id}` | `FollowUpEditIn` — small edits only: `{name?, step_edits?: [{step_id, wait?, template_id?, values?, agent_id?, remove?}], settings?}` → `FollowUpOut` (edits the draft) |
| PUT | `/v1/follow-ups/{id}/draft` | `FollowUpDraftIn {trigger, steps, settings}` → `FollowUpOut` (Pip's full rewrite) |
| POST | `/v1/follow-ups/{id}/publish` | `{expected_updated_at}` → `FollowUpOut`; 422 `follow_up_invalid` with `problems: [{step_id, code, message}]`; 409 `follow_up_trigger_overlap` |
| POST | `/v1/follow-ups/{id}/pause` · `/resume` · `/turn-off` | → `FollowUpOut` |
| POST | `/v1/follow-ups/{id}/start` | `{lead_ids?: [uuid] (≤200), lens?: LeadLensIn, expected_count?}` → `{started, skipped, plan_id?}` (over 200: an approved plan, like the leads bulk route) |
| GET | `/v1/follow-ups/{id}/runs` | `?status=&cursor=` → `{items: [FollowUpRunOut], next_cursor}` |
| GET | `/v1/follow-ups/{id}/runs/{run_id}` | `FollowUpRunOut` with `events: [{step_id, kind, result, at, call_id}]` |
| POST | `/v1/follow-ups/{id}/runs/{run_id}/stop` | → `FollowUpRunOut` |
| GET | `/v1/follow-ups/{id}/results` | `{days: 30, started, finished, goal_reached, steps: [{step_id, reached, exits: {<exit>: n}}]}` |
| GET | `/v1/follow-ups/starters` | the ready-made list with their filled-in steps for this account |

`FollowUpOut`: `{id, name, status, starter, trigger, settings, steps (the draft if any, else
live), has_unpublished_changes, live_version: {number, published_at} | null, counts: {running,
waiting, done_30d, goal_30d}, problems: [{step_id, code, message}], updated_at}`. Every step in
`steps` also carries `summary`: one plain line the screen and Pip both show ("Call with Riya,
try 3 times, an hour apart").

Errors are RFC-9457 with these codes: `follow_up_invalid`, `follow_up_trigger_overlap`,
`follow_up_not_live`, `follow_up_changed` (409, `expected_updated_at`), `follow_up_run_not_running`.

## Pip

Pip builds and changes Follow-ups through the area dispatch (`copilot/areas.py`), so the client
tool array grows by an entry line, not by whole schemas:

* `follow_ups_list`, `follow_up_read` (reads, `leads:read`).
* `follow_up_draft` (write, confirm): Pip turns the person's sentence into `{name, trigger,
  steps, settings}` and the server validates it; refusals come back as the `problems` list, so
  Pip fixes and retries before the person sees a card. The confirm card shows the step
  summaries.
* `follow_up_publish`, `follow_up_pause`, `follow_up_resume`, `follow_up_turn_off` (confirm).
* `follow_up_start` (a plan over leads, like the bulk route).

Pip never invents an agent, a template or a teammate: the tool descriptions point at the reads
that list them, and the server refuses an unknown id.

## The screen

`/c/[slug]/follow-ups` (sidebar, under Leads):

* **List**: each Follow-up as a row: name, what starts it, On/Paused/Off, running now, reached
  goal in 30 days. **New Follow-up** opens Pip with "Describe what should happen to a lead";
  under it, the ready-made ones as buttons.
* **Detail**: the steps as a vertical list, branches indented under their `decide`, each step
  one line with a ⋯ menu for the small edits (change wait, change template, change agent,
  remove). **Ask Pip to change it**. **Publish** when there are unpublished changes, with the
  problems listed as buttons that open the step. Tabs: **Steps**, **Runs** (lead, where they
  are, last result, Stop), **Results** (count per step and per exit, last 30 days).
* Phone width: the same list, one column; menus become sheets.

## Where it touches existing code

* `apps/api/ingest/service.py::ingest_lead`: reads the live `new_lead` Follow-up for the source
  instead of `lead_policy.load_plan`'s agent, wait and retries; starts the run.
* `apps/api/ingest/lead_policy.py`: keeps hours, days, holidays, after-hours and
  `detect_machines`; `book_retry` becomes the run's retry.
* `apps/workers/callbacks.py`: a `follow-up:` call-back is dialled like any other; refused for
  good → the run ends.
* `apps/workers/pipeline.py`: after outcomes are stored, `call_ended` triggers and waiting runs
  advance (a job, never inline work in voice-runtime).
* `apps/api/whatsapp/webhooks.py`: an incoming message stops that number's runs when
  `stop_on_reply` (the text is never read or kept).
* DNC additions and opt-outs; lead won/lost; tenant and lead erasure (`retention`).
* Registries: tenant tables, `APPEND_ONLY_TABLES` (versions, events), `QUIET_TABLES` or live
  topics, `BOUNDED_LISTS`, the RLS tests, OpenAPI, the coverage ratchet surfaces.
