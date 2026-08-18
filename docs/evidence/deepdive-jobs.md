# Deep dive: the background fleet — jobs, cron ticks, and the reliability triad

**Date:** 18 Aug 2026 · **Scope:** `apps/workers/**`, every `enqueue_*`/outbox producer in
`apps/api/**` and `apps/voice-runtime/**`, the cron schedule and its overlap protection,
`scripts/` guardrails for the above · **Decisions taken:** D-199, D-200, D-201.

**Verified against `abcd59c`** (session head at the time of writing) after a rebase — the
first pass was made from a base 136 commits behind it, and ten of the sixteen files
touched had moved in between. Every finding below and every sabotage in the matrices was
re-run on the rebased tree; where upstream had changed the answer it is said so by name.
Database: `calevate_replay` (the shared `calevate` database is internally inconsistent and
cannot reach head).

Findings are labelled **PROVEN** (executed here) or **REASONED** (read). Sub-surfaces that
were clean are said to be clean, by name.

---

## 1. The three-way sweep

Previous waves proved individual pipelines. Nothing had swept the agreement between what is
**defined**, what is **registered** with the worker, and what is **enqueued or cronned**.
That sweep is now `scripts/check_job_wiring.py`, derived rather than hand-listed, in
`make guardrails` and in `.github/workflows/ci.yml`.

**Result on the live tree (PROVEN, `uv run python -m scripts.check_job_wiring`):**

```
JOB WIRING: OK (22 job functions, 10 queued + 12 cron registrations,
                17 enqueue site(s), 1 dynamic site(s) recorded)
```

| Job | Defined | Registered | Reached by | Verdict |
|---|---|---|---|---|
| `ingest_engine_event` | `pipeline.py:288` | FUNCTIONS | `voice-runtime/webhook_routes.py:748`, `pipeline.py:2217` | ✅ |
| `run_post_call_pipeline` | `pipeline.py:587` | FUNCTIONS | `pipeline.py:381` | ✅ |
| `notify_hot_lead` | `notifications.py:92` | FUNCTIONS | `pipeline.py:1880` (outbox-once) | ✅ |
| `deliver_outbound_webhook` | `outbound_webhooks.py:227` | FUNCTIONS | `integrations/service.py:267` (outbox) | ✅ |
| `execute_deletion_request` | `retention.py:1091` | FUNCTIONS | `compliance/deletion.py:611` (outbox) | ✅ |
| `execute_tenant_erasure` | `retention.py:1519` | FUNCTIONS | `compliance/tenant_erasure.py:472` (outbox) | ✅ |
| `notify_hot_lead_whatsapp` | `whatsapp.py:514` | FUNCTIONS | `whatsapp.py:728` (outbox-once) | ✅ |
| `escalate_campaign_contact` | `whatsapp.py:824` | FUNCTIONS | `whatsapp.py:1141` (outbox-once) | ✅ |
| `record_in_call_optout` | `optout.py:74` | FUNCTIONS | `voice-runtime/tool_routes.py:165` | ✅ |
| `deliver_auth_email` | `auth_email.py:87` | FUNCTIONS | `authn/service.py:630` (outbox) | ✅ |
| `dispatch_outbox` | `dispatcher.py:54` | CRON 10s | schedule | ✅ |
| `reconcile_executions` | `pipeline.py:2156` | CRON 10min | schedule | ✅ |
| `report_stalled_pipeline` | `dispatcher.py:198` | CRON :05,:35 | schedule | ✅ |
| `report_overdue_erasures` | `dispatcher.py:312` | CRON :25 | schedule | ✅ |
| `dispatch_campaign_tick` | `campaign_dispatch.py:327` | CRON 30s | schedule | ✅ |
| `sweep_expired` | `dispatcher.py:123` | CRON 03:17 | schedule | ✅ |
| `draw_qa_samples` | `qa_sampling.py:110` | CRON Mon 02:20 | schedule | ✅ |
| `apply_retention` | `retention.py:384` | CRON 03:40 | schedule | ✅ |
| `prune_reliability_tables` | `retention.py:1719` | CRON 04:10 | schedule | ✅ |
| `sweep_engine_drift` | `engine_reconciliation.py:260` | CRON :07,:37 | schedule | ✅ |
| `sweep_kb_drift` | `kb_reconciliation.py:367` | CRON :23 | schedule | ✅ |
| `issue_one_time_charges` | `billing.py:141` | CRON 02:05 | schedule | ✅ |

**Nothing was found in any of the three columns.** Every worker module also has a live
importer (checked separately: no orphan module in `apps/workers`). The wiring was already
correct; what did not exist was anything that would keep it correct.

### Why the third shape needed a static gate (PROVEN)

Read out of the installed `arq` 0.28.0 (`Worker.run_job`), an enqueue for a name no worker
registers is answered with (quoted verbatim, hence the plain fence — a `python` fence would let `ruff format` rewrite a vendor's source in a place that claims to be its source):

```text
logger.warning('job %s, function %r not found', job_id, function_name)
return await job_failed(JobExecutionFailed(f'function {function_name!r} not found'))
```

No retry, no alert. Executed end to end against real Redis on its own queue name
(`tests/worker_terminal_alert_test.py::test_a_real_worker_drops_an_unregistered_job_…`):
two jobs enqueued, `jobs_complete = 1`, `jobs_failed = 1`, and before D-200 the only trace
of the dropped one was a log line.

### The guardrail's own blind spots, and how they are closed

| Hole | Closure |
|---|---|
| a job name the scan cannot resolve | FAILS unless recorded in `DYNAMIC_ENQUEUE_SITES` with a reason. One entry: `apps/workers/dispatcher.py::message.job`, the outbox drain, covered at its producers. |
| an exemption for a site that no longer exists | `stale_exemptions()` — the registry only shrinks. |
| a seam signature change (`enqueue_outbox` growing a positional `job`) | `_assert_the_seams_still_look_like_this()` reads the real signatures with `inspect`. |
| a scan matching nothing | `blindness()` — four floors plus `WorkerSettings.functions is FUNCTIONS`. Refuses rather than printing OK. Same shape and same argument as `check_wiring.blind_spots()` (D-176), followed rather than re-invented. |
| a lifecycle hook counted as a job | subtracted from `WorkerSettings`' own hook attributes, not from a hardcoded list. |

**Sabotage (PROVEN, all on the real tree, restored after each):**

| Mutation | Result |
|---|---|
| add `async def reap_abandoned_widgets(ctx)` to `optout.py` | `FAIL — jobs defined and never registered`, exit 1 |
| drop `notify_hot_lead_whatsapp` from `FUNCTIONS` | `FAIL` on shape 1 **and** shape 3, exit 1 |
| point `pipeline.py`'s hot-lead producer at another name | `FAIL` on shape 2 **and** shape 3, exit 1 |
| force each of the four blindness floors | each refuses with its own message (parametrised test) |
| `ENQUEUE_SEAMS["enqueue_outbox"] = 1` | seam assertion goes red |

---

## 2. Idempotency of every registered job — what happens on the SECOND delivery

| Job | Second-delivery hazard | What actually protects it | Verdict |
|---|---|---|---|
| `ingest_engine_event` | duplicate call row, duplicate pipeline | webhook inbox CAS on `(provider, event_key)` + arq job id `ingest:{engine}:{exec}:{status}`; call upsert; inbox closed LAST | REASONED clean |
| `run_post_call_pipeline` | double metering (money) | `lock_call_writes` + append-only `usage_events` + `crm_notified_at`; arq id keyed on `call_id` | REASONED clean |
| `notify_hot_lead` | email sent twice | `_already_delivered` asks whether the email REACHED someone, scoped `channel='email'` — deliberately not "an attempt row exists" | REASONED clean |
| `notify_hot_lead_whatsapp` / `escalate_campaign_contact` | message sent twice, WABA report | `enqueue_outbox_once` partial-unique `dedupe_key` + per-channel `_already_delivered` | REASONED clean |
| `deliver_outbound_webhook` | duplicate POST into a client CRM | `delivery_id` minted at ENQUEUE, so a retry replays the same id rather than minting one | REASONED clean |
| `record_in_call_optout` | duplicate suppression evidence | `record_call_optout` dedupe; arq id keyed on execution | REASONED clean |
| `execute_deletion_request` | re-erasing | every statement is an idempotent UPDATE to a fixed value; certificate is written once | REASONED clean |
| `execute_tenant_erasure` | restamping an issued certificate | `_MARK_ERASED_SQL` is single-shot (`deleted_at IS NULL AND status='churned'`); zero rowcount raises | REASONED clean |
| `deliver_auth_email` | **no ladder at all** | **FIXED — see below** | ⚠️ was broken |
| `dispatch_outbox` | double publish | claim is conditional UPDATE + `SKIP LOCKED` + `locked_until`; publish keyed `job_id_for(job, message.id)`; ARQ dedupe within `keep_result` | REASONED clean |
| `dispatch_campaign_tick` | **a person rung twice** | claim COMMITS before the first dial, one transaction per dial, `_reap_stuck_dialing` after 30 min. Explicitly reasoned about `CancelledError` being a `BaseException` | REASONED clean |
| `issue_one_time_charges` | **double charge** | `ux_one_time_charges_tenant_kind_ref` + unconditional insert; the probe is a cost filter the write does not trust | REASONED clean |
| `draw_qa_samples` | duplicate sample rows | keyed hash draw + unique constraint | REASONED clean |
| `apply_retention` / `prune_reliability_tables` / `sweep_expired` | — | idempotent DELETE/UPDATE to fixed values, batched with a per-tenant budget | REASONED clean |
| `reconcile_executions` / drift sweeps | duplicate repair | fixed arq id per execution + `keep_result` 3600 → one repair attempt per execution per hour | REASONED clean |

### The one non-idempotent job found: `deliver_auth_email` (PROVEN, fixed)

Its docstring said *"RAISING is what makes arq retry it … `WORKER_MAX_TRIES` then bounds it
and the DLQ catches what is left."* Both halves were false:

* it raised `RuntimeError`, and arq 0.28 retries only for `Retry`, `RetryJob` and
  `CancelledError` (`Worker.run_job`, read from the installed package). `max_tries = 3`
  never applied — **a password-reset email lost to one slow minute at the mail provider
  was lost for good**, while the sign-in screen truthfully reported it was on its way;
* there is no arq DLQ (`WorkerSettings`' own docstring), so the trace was a `log.warning`.

Fixed to the shape the other four delivery jobs already use: `Retry(defer=…)` on a
10s/30s ladder, then `alert("WORKER_DELIVERY", "auth_email_exhausted")` with the
recipient's DOMAIN and never the mailbox or the secret.
**Sabotage:** restoring the `RuntimeError` turns 4 of the 8 tests in
`tests/auth_email_delivery_test.py` red; restoring the fix turns them green.

---

## 3. Cron ticks — lease, fit, and cancellation

`arq` gives a cron job an id embedding its INTENDED run time, so two workers cannot run the
same tick — but the :30 tick and the :00 tick are different ids and will overlap. Every
scheduled function was checked for what it needs.

| Cron | Interval | Overlap protection | Fits? |
|---|---|---|---|
| `dispatch_outbox` | 10s | none needed — per-row claim is a conditional UPDATE + `SKIP LOCKED` + `locked_until` lease | yes |
| `dispatch_campaign_tick` | 30s | Redis `SET NX PX` `_tick_lease` (330s > `job_timeout` 300s), plus an overrun alert AND an overlap alert | yes, and it says so when not |
| `reconcile_executions` | 10 min | none needed — fixed arq id per execution + `keep_result` 3600. **it gained `max_tries=WORKER_MAX_TRIES` upstream while this audit was in flight**, which is why a retried tick is safe: the fixed re-drive id means it cannot double-drive what the previous attempt queued | yes |
| `sweep_engine_drift` | 30 min | **import-time assertion** that `SWEEP_BUDGET_S + 60 < SWEEP_INTERVAL_S` | asserted |
| `sweep_kb_drift` | 60 min | same, `KB_SWEEP_BUDGET_S` | asserted |
| `report_stalled_pipeline` | 30 min | read-only counts | yes |
| `report_overdue_erasures` | 60 min | read-only counts | yes |
| `sweep_expired`, `apply_retention`, `prune_reliability_tables`, `draw_qa_samples`, `issue_one_time_charges` | daily/weekly | idempotent statements; per-tenant row budget defers the remainder to the next tick | yes |

**`CancelledError` mid-loop (REASONED, clean, and it is clean deliberately):**

* `campaign_dispatch._dispatch_for_campaign` commits the claim BEFORE the first dial and
  gives each dial its own transaction, explicitly because `CancelledError` is a
  `BaseException` that a shared transaction would roll the claim back under — which would
  ring a person a second time thirty seconds later. Its docstring argues exactly this.
* `retention.sweep_tenants` and `qa_sampling.draw_for_tenants` catch `Exception`, not
  `BaseException`, so a cancel propagates rather than being counted as one tenant failing.
  Both are batched with per-batch commits, so a cancel leaves a partial-but-consistent
  sweep the next tick continues.
* `dispatch_outbox` cancelled between `enqueue` and `mark_outbox_published` leaves the row
  claimed; the next tick re-enqueues with the same `job_id_for(job, message.id)` and ARQ
  dedupes it inside `keep_result`.

**The gap this surfaced, and how it is closed (D-200):** arq requeues a `CancelledError`
as a retry, so a cron cancelled at `job_timeout` three times running exits through
`job_try > max_tries` — a path checked BEFORE `on_job_start`, where the job's own code
never executes and its own `alert()` cannot fire. That is `apply_retention` gone until
tomorrow with nothing but a log line. See §4.

---

## 4. The DLQ

**There are two, and they are not the same thing.**

* **Enqueue leg — the outbox's `status='failed'`.** Fully wired and clean: depth and
  per-job breakdown on `GET /v1/ops/platform`, a step-up-confirmed, job-scoped, audited
  `POST /v1/ops/outbox/replay`, and `defer_outbox_claim` so a Redis outage defers the batch
  instead of dead-lettering the whole outbox in under a minute. **A replay re-runs the
  side effect**, which the endpoint's own description says in terms ("the outcome to be
  sure of before sending this is a second delivery"); the consumers are idempotent per §2,
  and `failed` rows keep their payload (asserted in `tests/outbox_payload_scrub_test.py`)
  because the replay publishes from it.
* **Execution leg — there is none.** An exhausted arq job is written to a result key
  nothing in `apps/` or `scripts/` reads. The repo's answer (P6.5) is per-job alerting, and
  that answer had **two holes**, because it assumes the job's code runs:
  `function not found` and `max retries exceeded` both return from `Worker.run_job` before
  `on_job_start`.

**Fixed (D-200):** `install_arq_terminal_alerter()` routes arq's own two warnings into the
one `alert()` as `WORKER_TERMINAL / job_function_not_registered` and
`job_retries_exhausted`. It is a call site, not a mechanism — no store, no Postgres, no
Redis, so it still works on the night the queue is what broke. It matches on the logging
FORMAT STRING, and `tests/worker_terminal_alert_test.py` asserts both templates still
appear in the installed `arq.worker` source, so an arq upgrade that rewords them fails the
build instead of silently unhooking the backstop.

**Sabotage (PROVEN):** reword one template → 4 tests red (including the real-Worker one);
delete the `install_…()` call from `startup` → the wiring test goes red. Restored: 9 green.

---

## 5. Outbox / inbox

**The transactional property holds at every producer (REASONED, clean).** All six write
through `enqueue_outbox`/`enqueue_outbox_once` on the CALLER's session with no commit of
their own:

| Producer | State change it shares a fate with |
|---|---|
| `compliance/deletion.py:609` | the `deletion_requests` row |
| `compliance/tenant_erasure.py:470` | the tenant erasure request |
| `authn/service.py:628` | the `auth_email_tokens` row |
| `integrations/service.py:265` | the domain write that produced the event |
| `pipeline.py:1878` | the lead status flip, under `lock_call_writes` |
| `whatsapp.py:726 / :1139` | the alert/escalation decision |

The drain is at-least-once with a keyed consumer: claim by conditional UPDATE with
`SKIP LOCKED` and a `locked_until` lease, publish keyed `job_id_for(job, message.id)`, mark
published by CAS on `status = 'pending'`. `enqueue_outbox_once` makes at-most-once a
database fact (partial UNIQUE on `dedupe_key`) rather than a check-then-write.

**Defect found and fixed (D-201): a published outbox row kept its payload for 90 days.**
`authn/service._enqueue_auth_email` bounded the exposure of a LIVE credential — reset
token, invite link, OTP — on the sentence *"the row is deleted on successful dispatch"*.
It is not deleted; it is UPDATEd to `published` and kept until
`prune_reliability_tables` reaches it at `RELIABILITY_PRUNE_AFTER` = 90 days.
`mark_outbox_published` now clears the payload in the same statement as the status flip.
This also shortens the DPDP exposure `retention.py` had already written down — that column
carries lead names, phone numbers and call summaries, outside every tenant retention policy
and outside the erasure path — from ninety days to one dispatch tick, for every job.

**Re-verified on the rebased tree, and it got WORSE upstream, not better.** `mark_outbox_published`
was untouched by the intervening 136 commits, `RELIABILITY_PRUNE_AFTER` is still 90 days, and
no competing scrub exists anywhere in `apps/`. D-190 meanwhile routed every MEMBER INVITATION
through `_enqueue_auth_email` — making it the only way an invitation reaches anybody — so a
72-hour invite token joined the reset token and the OTP in that column.

**PROVEN end to end** on `calevate_replay`, through the real producer and the real dispatcher
(`_enqueue_auth_email` → `dispatch_outbox`), with the fix reverted and then restored:

```text
WITHOUT the scrub
  BEFORE : pending   {"to": "victim@example.com", "kind": "password_reset", …, "secret": "tok_reset_e649…"}
  AFTER  : published {"to": "victim@example.com", "kind": "password_reset", …, "secret": "tok_reset_e649…"}
  rows still holding the plaintext token: 1     ← for the next ninety days

WITH the scrub
  AFTER  : published {}  job_id=deliver_auth_email:01a01348-…  published_at?True  attempts=1
  rows still holding the plaintext token: 0
```

**Sabotage:** remove the scrub → 2 unit tests red and the run above leaks the token; restore →
4 green and zero rows.

---

## 6. Retention and erasure (the ones whose bug is a legal problem)

**Countdown — clean.** `_due_tenants()` resolves from `engine_agent_routes`, unfiltered on
`active` and on `organizations.deleted_at`, precisely because offboarding is where the
countdown STARTS (FLOWS §9). `_call_clock` dates a call from `ended_at` with a fallback to
our own `created_at + metered duration`, so a call the vendor never dated still ages out.

**The certificate — clean, and honest about what it does not know.** `engine_deletion` is
recorded `unconfirmed` rather than asserted (Bolna's deletion API is an unresolved pilot
gate — external blocker, named below). The TRAI-floor collision is counted into the proof
(`recordings_within_trai_floor`, `recordings_destroyed`, `recording_hold_until`) rather
than resolved by a worker.

**Nothing re-creates erased data (REASONED, clean — and clean by construction).** The one
mechanism that could is `reconcile_executions`: it lists executions from the last 30
minutes and re-drives anything `_pipeline_settled` calls unfinished, which would re-fetch
and re-write a transcript. It cannot, because the erasure path **anonymizes rather than
deletes**: `execute_deletion_request` marks `transcript_turns.text/text_redacted` to
`[erased]` and blanks `call_extractions.data`, leaving the ROWS in place — so
`has_transcript` and `has_extraction` stay true and the probe answers `settled`.
`usage_events` and `crm_notified_at` are untouched for the same reason. The only arm that
truly DELETEs turns is a `transcript` policy with `action = 'delete'`, which fires at TTL
age — days, far outside the poller's 30-minute window. The anonymize-not-delete choice was
made for a billing reason (`usage_events` FK RESTRICT); it happens to be what makes this
safe, so it is worth recording that the two are now linked.

**And a SECOND barrier arrived upstream while this was being written, for the tenant half
only.** D-189 made `execute_tenant_erasure` set `engine_agent_routes.active = false`
(`_WITHDRAW_ROUTES_SQL`), and `pipeline._resolve_agent` selects `AND active` — so after a
tenant erasure the poller cannot resolve the tenant at all and never reaches the probe. The
distinction matters and is worth keeping straight: a per-SUBJECT DPDP §12 erasure leaves the
routes active, so there the anonymize-not-delete property is still the only thing standing
between an erasure and a re-driven transcript. It holds — but it holds on one mechanism, and
that mechanism was chosen for a billing reason, not this one.

**One residual exposure, named:** an outbox row still PENDING when an erasure runs will be
delivered afterwards carrying the erased person's lead fields. The window is one dispatch
tick (10s) and the delivery is to the client's own already-authorised endpoint. Closing it
would mean the erasure scanning `outbox_messages` — an infra table with no `tenant_id` and
no index on the payload — for a 10-second window. Not taken; the D-201 scrub removes the
much larger 90-day half of the same problem.

---

## 7. Still open

* **Engine-side deletion (external blocker: Bolna).** `engine_deletion` stays
  `unconfirmed` in every erasure certificate until the vendor commits to a documented
  deletion API (OPERATIONS §2, pilot gate 12(f)). Nothing in this repo closes it.
* **The shared `calevate` database is unusable and it is not a base problem.** The first pass
  read it as "behind head" from a stale base; on the rebased tree it is internally
  inconsistent — `alembic upgrade head` fails on a partial index. This work is verified
  against `calevate_replay` (same cluster and roles, seeded). Nothing here repairs the
  original: it is shared with concurrent sessions and migrating it under them is not this
  agent's call. One test still fails against `calevate_replay` and is neither this work's nor
  fixable from this branch: `guardrail_audit_test::TestRlsCoverage::test_live_schema_is_clean`
  reports `platform_engine_health` as a platform-scoped table absent from
  `RLS_EXEMPT_TENANT_COLUMNS`. That table is created by a migration on a SIBLING's branch
  (`1b3abda`) which is not an ancestor of this one — the shared database has it, this tree
  does not. Naming it in the exemption registry is a tenancy decision about code that is not
  here, and `db/registry.py` is explicit that each entry "costs a visible argument"; it
  belongs to whoever added the table.
* **Fixed in passing, found only by rebasing:** `auth_email.py`'s invite template said it was
  "kept in step with `members.INVITE_PATH` by `tests/auth_email_test.py`" — a file this repo
  does not have. A guard promised in a comment and never written is the same defect class as
  an unmounted router, and it guards a link that D-190 made the only way an invitation
  reaches anybody. The assertion now exists in `tests/auth_email_delivery_test.py`, reading
  the path out of the TypeScript source, and the comment names it.
* **Also fixed in passing:** `scripts/check_image_paths.py` ran in `make guardrails` and in CI
  and appeared in no row of ENGINEERING-PRACTICES §2's catalogue, so
  `TestMakefileWiring::test_every_guardrail_script_is_named_in_the_catalogue` was red on the
  branch before this work touched it. Catalogued rather than left, because a red gate that
  is "somebody else's" is how a gate stops being read.
* **`outbox_messages.queue` still routes nothing** (D-162's open fork). Out of this
  session's fence; the decision names what closes it.
* **`OPTOUT_JOB` and `INGEST_JOB` each have two homes** (`apps/workers/*` and
  `apps/voice-runtime/*`). Deliberate and argued at the call site — voice-runtime may not
  import `apps.workers` — and `check_job_wiring` now compares BOTH spellings against the
  registry, so the two cannot drift apart silently. Left as is.
