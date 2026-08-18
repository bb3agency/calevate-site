# Audit — reliability, workers, the voice path, operations

Find-and-document pass, August 2026. **Nothing here was fixed**; this file is the whole
deliverable. Scope: the reliability triad (idempotency / outbox / webhook inbox),
`apps/workers`, `apps/voice-runtime`, failure behaviour under dependency loss, the
operations surface (alerts, health, kill switch, runbooks), and the deploy mechanism.

**Not re-reported here** (known and recorded, per the audit brief): `docs/ROADMAP.md` §6's
decision log, `docs/OPERATIONS.md` §2's pilot gates, and the standing fact that nothing in
`infra/` or `scripts/vps-deploy.sh` has ever been applied to a host
(`infra/README.md` §5, `docs/DEPLOYMENT.md` §4d). `docs/evidence/our-gates-audit.md` and
`docs/evidence/raghava-deploy-teardown.md` do not exist in this tree.

**In flight, deliberately not audited**: a sibling agent is finishing a Clerk deletion
touching `apps/api/core/auth.py` and `apps/web`. Nothing below cites either.

**Baseline**: `uv run python -m scripts.check_docs_drift` passes on this branch
(149 command claims, 164 decisions, 0 deferred mirror).

---

## Severity counts

| Severity | Count |
|---|---|
| High | 2 |
| Medium | 4 |
| Low | 3 |
| **Total** | **9** |

---

## R-1 · HIGH · A dial the engine accepted but whose HTTP response was lost leaves no call row, and the same person is dialled a second time

**Where**
- `apps/api/agents/service.py:674` — `handle = await engine.start_outbound_call(...)`
- `apps/api/agents/service.py:683-706` — the `calls` INSERT, which needs `handle` and
  therefore runs *after* that await returns
- `apps/api/agents/service.py:638-641` — the docstring asserting the opposite ordering
- `apps/api/engine/bolna.py:83` (`REQUEST_TIMEOUT_S = 10.0`), `:632-641` — any
  `httpx.HTTPError` becomes `ProblemError(code="engine_unreachable")`
- `apps/workers/campaign_dispatch.py:667-681` — `except Exception` → `_record_failure`
- `apps/workers/campaign_dispatch.py:963-970` — `_record_failure` returns the contact to
  `pending` with `next_attempt_at = now() + 30 minutes`
- `apps/workers/campaign_dispatch.py:815-822` — the only link between a call and a
  contact is `campaign_contacts.last_call_id`

**The failure sequence**

1. The dispatcher claims a contact (`pending → dialing`, committed) and calls
   `dispatch_call`.
2. `POST /call` reaches Bolna, Bolna **accepts it and starts dialling**, and the response
   is lost — a read timeout at 10s, a reset connection, a proxy 502 after the vendor
   committed. `_request` raises `engine_unreachable`.
3. `dispatch_call` never reaches line 683, so **no `calls` row is written and
   `campaign_contacts.last_call_id` is never set**. The caller's phone is ringing and
   this platform holds no record of it.
4. The dispatcher's `except Exception` calls `_record_failure`, which — being under
   `max_attempts` — sets the contact back to `pending`, `next_attempt_at = +30 min`.
5. The reconciliation poller (10-minute tick) does discover the execution and
   `_upsert_call` creates a `calls` row, so the *charge* is recovered. But
   `resolve_campaign_contact` matches on `cc.last_call_id = :cid AND cc.status =
   'dialing'` (`campaign_dispatch.py:818`) and this contact has neither. The contact stays
   `pending`.
6. Thirty minutes later the contact is claimed again and **the same person is dialled a
   second time for one enquiry** — twice the money, and a second unsolicited call, which
   is the category of behaviour the whole compliance gate exists to bound.

The same hole exists on the D-21 "call this lead" button (`POST /v1/leads/{id}/call`),
which routes through the same `dispatch_call`; there the consequence is a lead the client
believes was never called, and a re-press that dials twice.

**Proven or reasoned**: proven by reading, not executed. The ordering is unambiguous —
the INSERT binds `:ecid` to `handle`, so it cannot precede the await that produces it.
The re-dial follows mechanically from `_record_failure`'s `pending` write plus
`resolve_campaign_contact`'s join key.

**Why this has not been caught**: three artefacts state the property the code does not
have. `apps/api/agents/service.py:638`, `apps/workers/campaign_dispatch.py:542`
("a call row that survives even when our side fails afterwards, rather than an invisible
charge") and `tests/lead_dial_routes_test.py:175-178` all claim the row is written before
the engine answers. The test asserts a row exists on the **success** path only, so it
passes while proving nothing about the claim in its own docstring.

**What would fix it (described, not implemented)**: mint the `engine_call_id` on our side
before the vendor call, or write a `calls` row in a `dialing`/`unconfirmed` state keyed on
a client-generated idempotency token before `start_outbound_call` and reconcile the
vendor's handle onto it afterwards. Whichever shape, the invariant to restore is the one
already written down: *a row exists before the vendor can have started a call*. The
dispatcher's `except` branch then needs a third outcome beside "retry" and "exhaust" —
"we do not know whether this rang" — which must not re-dial. If the vendor's `POST /call`
turns out to accept an idempotency key, that is the cheaper answer and belongs in
`OPERATIONS.md` §2 gate 2 as a question to ask.

---

## R-2 · HIGH · Two of the platform's own promised alarms do not exist, and every metric recorder writes to a stream nothing reads

**Where**
- `docs/OPERATIONS.md:332-334` — "**What triggers one**: webhook failures > 3/5min;
  pipeline lag > 5 min; latency p95 breach 15-min sustained; **cap approaching
  (80%)/breached**; **complaint-spike on campaign**; **engine 5xx spike**; nightly job
  failures; **cert/domain expiry**."
- `apps/api/core/alerting.py:522-604` — every `record_*` recorder is
  `metrics_log.info("metric", ...)`, i.e. a log line
- `apps/api/core/alerting.py:93` — `metrics_log = get_logger("calevate.metric")`
- `apps/api/billing/caps.py` — no `alert(` call anywhere in the module
- `apps/workers/campaign_dispatch.py:568`, `:877` —
  `record_compliance_block(rule="spend_cap")`, a metric and nothing else

**The failure sequence (spend cap)**

1. A tenant's usage crosses `plans.hard_cap_*`. `recompute_capped` sets
   `spend_state.capped = true` in the metering transaction.
2. Every subsequent dial is refused by `compliance.service.check_dispatch`
   (`apps/api/compliance/service.py:367-371`) with `rule="spend_cap"`.
3. The dispatcher records `compliance_blocks{rule="spend_cap"}` — into the application
   log. There is no Prometheus endpoint, no scraper and no alert rule (DEPLOYMENT §8
   defers metrics endpoints to M2+), so nothing anywhere fires.
4. The client's campaign stops dialling. The UI still says "running". Nobody is told —
   not the operator, not the client. `runbooks/calls-stopped.md` is the diagnostic, and
   it is entered only after somebody notices.

The 80% *approach* warning has no implementation at all. Note the asymmetry that proves
this is an omission rather than a decision: D-140 built exactly this alarm for the
*platform's own* AI spend (`apps/api/billing/ai_quota.py:626` announces 80% and 100%
through `alert()`), and the client-facing spend cap — the one that stops a paying
customer's campaign — got nothing.

Three further entries on that §4 list have no call site anywhere: **complaint-spike on
campaign** (no `alert(` in any complaint path), **engine 5xx spike** (`bolna._request`
logs `engine_error` at WARNING and raises; nothing counts a rate), and **cert/domain
expiry** (nothing in `scripts/` or `infra/` checks a certificate's remaining life —
certbot's own renewal timer is the only thing, and it is silent about failure here).

**Proven or reasoned**: proven by exhaustive grep of `alert(` call sites across `apps/`
and `scripts/`, cross-read against OPERATIONS §4's trigger list. The 61 distinct alert
codes in this tree contain no spend-cap, complaint, engine-5xx-rate or certificate code.

**What would fix it**: the cheapest correct shape is the one D-140 already uses — alert
on the *write that crosses the line*, in `caps.recompute_capped`, with a stable code
(`tenant_spend_capped`, `tenant_spend_cap_approaching`) and the tenant id, so the alerter's
per-fingerprint suppression collapses a busy tenant into one notice. The other three are
either a rate over a counter (which needs the metrics pipeline DEPLOYMENT §8 defers, and
should therefore be stated as *deferred with a named blocker* rather than listed as a live
trigger), or, for cert expiry, a systemd timer beside the backup units using the same
`notify.sh` relay. Whichever is chosen, OPERATIONS §4's list should stop naming triggers
that nothing implements — a promised alarm is worse than an absent one.

---

## R-3 · MEDIUM · The `api` container's graceful-shutdown window is longer than the grace Docker gives it, so every api deploy ends in SIGKILL

**Where**
- `compose.prod.yml:64-96` — the `api` service. It declares
  `--timeout-graceful-shutdown=25` (line 79) and **no `stop_grace_period`**.
- `compose.prod.yml:76-78` — the comment: "25s leaves 5s of the api's 30s grace for that
  shutdown to complete." The api has no 30s grace; Docker's default is **10 seconds**.
- `compose.prod.yml:131` (voice-runtime, 30s) and `:148` (workers, 60s) — the two
  services that *do* declare one.
- `tests/worker_reliability_test.py:48-95` — `_compose_grace_seconds` and
  `test_the_drain_window_fits_inside_the_grace_docker_gives_it` are parameterised on
  `"workers"` only, so nothing pins the api relationship.

**The failure sequence**

1. `scripts/vps-deploy.sh` swaps api: `compose up -d --no-deps api` recreates the
   container, sending SIGTERM.
2. D-101's fixed signal chain (`apps/api/core/bootstrap.py:55-100`) now works as
   documented: uvicorn's `handle_exit` sets `should_exit`, the sockets close, and the
   server **waits up to 25 seconds** for in-flight requests.
3. Docker's default `stop_grace_period` of 10s elapses and sends SIGKILL.
4. In-flight requests past the 10-second mark are severed mid-response, and the lifespan's
   `finally` — Redis pool close, OpenTelemetry span flush — never runs. This is precisely
   the outcome `bootstrap.py:70-74` describes as the defect it fixed; the fix is intact
   and the container-level budget undoes half of it.

**Proven or reasoned**: proven from the compose file. `stop_grace_period` appears exactly
twice in the repository and neither occurrence is the api service (grep across `*.yml`,
`*.yaml`, `*.py`, `*.sh`). Docker Compose's documented default when the key is absent is
10s.

**What would fix it**: give `api` a `stop_grace_period` strictly greater than 25s (30s,
matching voice-runtime, keeps the 5s headroom the comment already reasons about), and
extend `tests/worker_reliability_test.py`'s grace assertion to cover all three long-lived
services rather than `workers` alone — the test's own docstring argues the relationship,
not the number, which is exactly what generalises.

---

## R-4 · MEDIUM · One execution's error ends the reconciliation sweep for every execution behind it, silently

**Where**
- `apps/workers/pipeline.py:2210-2221` — the repair loop, with no `try` inside it
- `apps/workers/pipeline.py:2213` — `verdict = await _pipeline_settled(...)`, which opens
  an `untenanted_session` and then a `tenant_session` per execution
- `apps/workers/settings.py:127` — `cron(traced_job(reconcile_executions), minute={0,
  10, ...}, run_at_startup=True)` with **no `max_tries`**; `arq.cron()` defaults it to 1,
  as five sibling crons in the same file argue at length
- Contrast: `apps/workers/dispatcher.py:219-250`, `report_stalled_pipeline`, which was
  fixed for exactly this shape and carries the argument ("ONE TENANT'S FAILURE IS NOT THE
  TICK'S (P6.2) … An alarm that fails towards silence is worse than no alarm")

**The failure sequence**

1. The poller lists executions for the last 30 minutes. This is D-31's *guarantee of
   record* — the only mechanism that recovers a webhook Bolna never delivered.
2. Execution *k* in the listing belongs to a tenant whose `tenant_session` errors (a
   connection reset, a pool timeout at `_POOL_TIMEOUT_S`, an RLS/GUC problem, a row the
   query trips on).
3. The exception escapes the loop. Executions *k+1…n* are **never examined** and never
   repaired on this tick. The job raises; with `max_tries` at arq's default of 1 it is
   finished on its first attempt (`arq/worker.py::run_job` retries only for
   `Retry`/`RetryJob`/`CancelledError`).
4. Nothing alerts. The two `alert()` calls in this function cover the *listing fetch*
   (`pipeline.py:2182`) and *listing incompleteness* (`:2195`); an exception in the repair
   loop is covered by neither.
5. The next tick's 30-minute window still overlaps, so a *transient* fault self-heals. A
   *persistent* one — one tenant whose probe reliably errors, sitting early in a listing
   ordered by the vendor — means the guarantee of record silently stops guaranteeing,
   with the console green. `postcall_pipeline_stalled` is the only backstop, and it is
   half-hourly and reports a *count* rather than the fact that the repairer is dead.

**Proven or reasoned**: reasoned from the code, with the arq semantics taken from this
repo's own repeatedly-verified statement of them (`apps/workers/settings.py:360-366`,
`:176-188`). Not executed — running the poller needs an engine adapter and a populated
listing, and the audit brief forbids the full suite.

**What would fix it**: the shape is already in this repository three times
(`report_stalled_pipeline`, `retention.sweep_tenants`, `qa_sampling.draw_for_tenants`):
per-item `try/except`, an `unreached` counter, the counter on the job's return string and
in the alert body so the reported repair count reads as a floor rather than a total. Plus
`max_tries=WORKER_MAX_TRIES` on the cron registration, for the reason its five neighbours
already give.

---

## R-5 · MEDIUM · A tenant database transaction is held open across a third-party HTTP round trip on the CRM delivery path

**Where**
- `apps/workers/outbound_webhooks.py:237` — `async with tenant_session(tenant_id) as
  session:` opens the transaction
- `apps/workers/outbound_webhooks.py:265-271` — `await _deliver_to_endpoint(...)` inside
  it: either a signed POST to the client's own endpoint
  (`apps/api/integrations/service.py:568`, `timeout=DELIVERY_TIMEOUT_S = 10.0`) or a
  Google Sheets append (`apps/workers/google_sheets.py:279-281`, same timeout)
- The transaction is not closed until after `record_delivery` and `_retain_body`, the
  latter of which makes an **object-store** round trip
  (`outbound_webhooks.py:205-213`)
- Comparable: `apps/workers/campaign_dispatch.py:668-676` holds a tenant transaction
  across `dispatch_call`'s engine POST (10s), though that one is bounded to one dial at a
  time by the tick lease

**The failure sequence**

1. A client's CRM endpoint goes slow — not down, slow: it accepts the connection and
   answers in 9 seconds. This is the ordinary shape of an overloaded receiver.
2. Each `deliver_outbound_webhook` job holds one pooled Postgres connection, inside an
   open transaction, for the whole 9 seconds plus the object-store PUT.
3. arq's default `max_jobs` is 10, so up to 10 of the worker's 16 connections
   (`WORKERS_DB_POOL_SIZE: 16`, `compose.prod.yml:143`) are parked on a third party's
   latency. There is no overflow by design (`apps/api/db/session.py:107-120`), and
   `_POOL_TIMEOUT_S` is 5 seconds.
4. Everything else the worker fleet owes — the post-call pipeline, the 30-second campaign
   dispatch tick, the nightly retention sweep — competes for the remaining 6 connections
   and starts meeting `QueuePool limit reached` after 5 seconds. The dispatch tick
   overruns its interval and fires `dispatch_tick_overrun`; the symptom points at the
   dispatcher and the cause is one client's slow CRM.

**Proven or reasoned**: reasoned. Bounded and survivable — every leg has a timeout, and
the connection budget in DEPLOYMENT §2a is generous — which is why this is Medium and not
High. It is listed because the repository already treats this exact pattern as a defect
elsewhere and says so: `campaign_dispatch._dispatch_for_campaign`'s docstring
(`:530-545`) calls out "it stops a DB transaction being held open across an engine HTTP
round trip" as a property it was restructured to obtain, and `pipeline._copy_recording_once`
(`:636-646`) deliberately refuses to hold a lock "across a 120-second vendor download".
Two modules reason about it; the delivery worker does not.

**What would fix it**: the shape `_copy_recording_once` uses — read what the attempt needs
in one short transaction, close it, perform the network call outside any session, then open
a second short transaction to write `record_delivery` and the retained-body key. The
sheets-kind duplicate guard (`outbound_webhooks.py:251-262`) is the one read that must stay
paired with the write; a CAS on the delivery row is the standard answer and is already this
repo's doctrine (BACKEND-PATTERNS §5).

---

## R-6 · MEDIUM · `/healthz` and `/healthz/ready` can hang, because the health probe is the one wait in this repo with no bound

**Where**
- `apps/api/core/health.py:80-87` — `_check_db` runs `SELECT 1` through
  `untenanted_session()` with no `asyncio.timeout` and no statement timeout
- `apps/api/db/session.py:120-124` — the engine sets `pool_timeout` and `pool_pre_ping`
  but **no connect timeout and no statement timeout**
- `apps/voice-runtime/webhook_routes.py:136-141` states the underlying fact plainly:
  "psycopg sets no statement timeout, the engine sets no connect timeout, and
  `pool_pre_ping`'s `SELECT 1` hangs on exactly the same socket as the query it is
  checking"

**The failure sequence**

Postgres is *blackholed* rather than refusing — a dropped NAT mapping, a firewall change,
a host that stops answering without sending RST. `_check_db` blocks on the socket
indefinitely: `pool_pre_ping`'s own `SELECT 1` hangs on the same socket, so the pre-ping
does not save it either.

- `/healthz` never answers. `scripts/vps-deploy.sh:758` polls it with `curl --max-time 5`,
  so the deploy is protected — it burns its full 180s health window and then aborts with a
  correct message, which is the right outcome by accident rather than by design.
- `/healthz/ready` never answers. That is the endpoint OPERATIONS §8 makes the go-live
  gate and the line an operator curls during an incident; it hangs rather than returning
  `503 db_down`, which is the one word it exists to produce.
- Each hung probe holds a pooled connection for the life of the request, so repeated
  probing during the outage exhausts the pool and makes the *rest* of the service answer
  503 for the wrong reason.

Voice-runtime's receiver is immune — `_DURABLE_DEADLINE_S` wraps its Postgres work
(`webhook_routes.py:616`) — which is why this is scoped to the health surface.

**Proven or reasoned**: reasoned; the absence of the bound is verified by reading
`get_engine` and `_check_db`, and the repo states the psycopg/pre-ping behaviour itself in
the citation above. Not reproduced (would need a packet-dropping Postgres).

**What would fix it**: the same doctrine every other wait in this repo already follows —
wrap `_check_db` (and `_queue_stats`) in an `asyncio.timeout` sized well under any
caller's patience, and treat the breach as `db_down`/`redis_down` rather than as an
exception. A `connect_timeout` in the DSN's `connect_args` is the complementary half and
would also bound the pool's own pre-ping.

---

## R-7 · LOW · The outbox column that reads as routing routes nothing, and the fleet name is written by only one producer

Recorded as D-162 and argued in `apps/api/reliability/service.py:267-289` — **not a new
finding**, and noted only to say the audit examined it and agrees with the recorded
decision. `outbox_messages.queue` is NOT NULL, selected by `claim_outbox_batch`, and
ignored by `dispatch_outbox` and by `WorkerSettings` alike. The deferral names what closes
it (drop the column, or a second fleet with a filter). No action proposed.

---

## R-8 · LOW · `dispatch_outbox` reports its per-message failures through the caller's session, which a database fault has already poisoned

**Where**: `apps/workers/dispatcher.py:78-119`.

`claim_outbox_batch` commits on its own connection (correctly, and argued at length at
`reliability/service.py:399-429`), but `mark_outbox_published` and `mark_outbox_failed`
write through the *caller's* `untenanted_session`, which stays open across the whole batch
of up to 50 messages and commits once at the end.

The consequence is narrow but real: the broad `except Exception` at
`dispatcher.py:109-118` is written for a **poisoned payload**, and it responds by issuing
another statement on the same session. If the exception that arrived was a database error
rather than a payload error — which it can be, since `mark_outbox_published` at line 85 is
inside the `try` — the session is in a failed-transaction state, `mark_outbox_failed`
raises `InFailedSqlTransaction`, and the whole tick aborts with the batch's status writes
rolled back. The messages keep their bumped `attempt_count` (that commit is durable) and
are re-claimed next tick, so nothing is lost; what is lost is the *distinction* between a
poison message and a database blip, and up to 50 messages get charged an attempt each pass
until the database recovers or `_dead_letter_exhausted_claims` retires them as poison they
never were.

**Proven or reasoned**: reasoned from the code and from psycopg's documented
failed-transaction semantics. Low because the outcome is a mislabelled dead letter under a
database outage — a condition that has louder alarms of its own.

**What would fix it**: narrow the `except` to the exceptions a payload can actually raise
(the enqueue path's serialisation and value errors), and let a `DBAPIError` escape to the
tick's own failure handling, where "the database is gone" is the correct verdict.

---

## R-9 · LOW · `webhook_deliveries` records only the deliveries we claimed, so the forensic trail is missing exactly the events an investigation would want

**Where**: `apps/voice-runtime/webhook_routes.py:726-743` — the `webhook_deliveries`
INSERT sits inside `if claimed:`.

A delivery that is refused at the source check (`:531-547`), that is unkeyable
(`:582-600`), that is over the size cap (`:554-562`), that times out reading its body
(`_read_bounded`), or that the inbox answers `duplicate` for, leaves **no row in the
forensic table**. All of those are alerted and metered, which is the operational half; the
*evidential* half — SEC-COMP §4's "scope via `audit_log`/`webhook_deliveries`" for a
suspected breach (OPERATIONS §7) — sees only the accepted traffic. An attacker probing an
unsigned public endpoint is precisely the population this table would be consulted about,
and it is the population the table does not contain.

**Proven or reasoned**: reasoned from the code path. Low because the alert stream and
`record_webhook_replay_divergence` carry the operational signal, and because writing a row
per refusal on an unauthenticated endpoint is itself an amplification risk the current
design deliberately avoids.

**What would fix it**: probably nothing in the receiver — the right place is a bounded,
aggregated counter rather than a row per hostile POST. What *should* change is the breach
runbook's sentence, which currently sends an investigator to a table that cannot answer
the question.

---

## Examined and found clean

Listed so the next reader knows what was looked at rather than skipped.

**Reliability triad**
- `apps/api/reliability/service.py` in full. The outbox claim's commit-on-its-own-
  connection, the `MATERIALIZED` + `ORDER BY created_at, id` claim (which genuinely does
  fix the LIMIT-rescan overcount), `locked_until` doing double duty as lease and backoff,
  `_dead_letter_exhausted_claims` closing the abandoned-claim loop, the CAS guards on
  `mark_outbox_published`/`mark_outbox_failed`/`defer_outbox_claim`/`replay_dead_letters`,
  and the deliberate asymmetry between re-checking `status` and not re-checking `job` —
  all correct and correctly argued.
- `enqueue_outbox_once`'s `ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL`: the
  partial-index conflict target is spelled correctly, which is the thing that usually goes
  wrong here.
- `read_dead_letter_queue`'s single grouped aggregate: `depth` and `deferred` genuinely
  cannot disagree, because `now()` is the transaction timestamp.
- Idempotency: the lease-based re-claim of a stale `processing` record, the
  same-key-different-body 409, the separate `IDEMPOTENCY_SCOPE_SECRET`. The `scope_key`
  cannot be submitted from the wire (both call sites derive it from the verified
  principal — checked).
- Webhook inbox: keying on the **transition** (`{execution_id}:{raw_status}`) rather than
  the execution, and `payload_hash` over the key rather than the delivery. Both are the
  right call and both are argued from evidence.

**Voice runtime**
- Hard rule 3's five obligations hold today. Source check before any body read; body
  bounded in bytes *and* time; every exit measured through `measured()`/`_refuse`; the
  durable section under `_DURABLE_DEADLINE_S`; the Redis fast-path key written only
  **after** the commit (the ordering that matters most, and it is right).
- `tests/voice_runtime_import_surface_test.py` and
  `tests/voice_runtime_deploy_independence_test.py` exist and pin the import surface and
  the deploy decoupling. `core/health.build_health_router` takes `detail_gate` by
  injection specifically to keep `core.auth` off voice-runtime's boot graph — verified.
- The receiver's only DB work is the inbox claim plus one forensic row; no tenant session
  is opened and no domain row is written. Confirmed by reading, not assumed.
- The ARQ enqueue does sit inside the inbox transaction, which is a network call inside a
  transaction — but it is bounded by the ARQ pool's `conn_timeout=2` *and* by
  `_DURABLE_DEADLINE_S`, and the failure direction (job queued, transaction rolled back)
  costs at most a job whose `inbox_row_id` no longer resolves. Deliberate and safe.

**Kill switch and gates**
- The big red switch reaches both places it must: once per dispatch tick
  (`campaign_dispatch._run_tick`) and once per contact through `check_dispatch`
  (`compliance/service.py:306-311`), so a halt thrown mid-batch stops the contacts behind
  the one in flight. Propagation is bounded by the 5s in-process memo, and
  `set_platform_status` invalidates the Redis cache.
- `_read_durable` raises when Postgres is unreachable, so the tick **fails closed** — no
  dialling. The one fail-open (`platform_state` row absent = fresh database) is explicitly
  argued and is the right call.
- The per-dial DNC read is uncached and per contact, so hard rule 5's "additions propagate
  before the next dispatch tick" is met with margin.
- `_tick_lease` fails open on a Redis error, and the claim CAS is what stands behind it —
  correct, and the reasoning about arq's per-execution-time cron ids is accurate.
- The claim CAS (`MATERIALIZED` + total ordering + `SKIP LOCKED` + the campaign's own
  `status = 'running'` re-read inside the claiming transaction) does prevent double-dial
  under overlapping ticks.

**Workers**
- `WorkerSettings`: `retry_jobs = True`, `job_timeout = 300`, `job_completion_wait = 45`
  strictly under the workers' 60s compose grace (pinned by a test), `on_job_start`/
  `on_job_end` pinning `Settings` per job so one call cannot be priced at two rates.
- `max_tries` is passed explicitly on every cron that needs it — *except*
  `reconcile_executions` and `dispatch_outbox`, and for `dispatch_outbox` the 10-second
  cadence makes that correct. See R-4 for the one that is not.
- Every job that matters alerts on ladder exhaustion (`engine_ingest_abandoned`,
  `post_call_abandoned`, `outbound_webhook_exhausted`, `hot_lead_notification_exhausted`,
  `campaign_escalation_exhausted`, `setup_fees_unissued`, `qa_sample_draw_abandoned`,
  `engine_drift_sweep_abandoned`, `kb_drift_sweep_abandoned`), which is the substitute for
  the arq DLQ that does not exist. `tests/job_registration_test.py` guards registration.
- `arq.Retry` (not a bare raise) is used everywhere the ladder is wanted — checked in
  `pipeline._abandon_ingest`, `outbound_webhooks`, `storage.StorageUnavailableError`.
- Sweeps are bounded: `retention.SWEEP_BATCH_ROWS = 1000` with `TENANT_ROW_BUDGET`, every
  statement `ORDER BY … LIMIT :batch`; `TENANT_ERASURE_BATCH = 500`;
  `dispatcher.STALL_WINDOW_HOURS = 24` bounds the stall alarm's window.
- Per-tenant isolation in the fleet-wide sweeps (`report_stalled_pipeline`,
  `report_overdue_erasures`, `retention.sweep_tenants`, `qa_sampling.draw_for_tenants`)
  with an `unreached` count carried into the alert body — the fail-towards-silence class
  is handled properly in all four.
- `_all_tenants` correctly uses `admin_session` (not `untenanted_session`) for the
  organizations directory, and enters each tenant through a normal `tenant_session`.
- Every outbound HTTP client in `apps/`, `packages/` and `scripts/` carries an explicit
  timeout — checked exhaustively (bolna 10s, cartesia, razorpay, clerk, sheets, whatsapp,
  extraction, storage download, delivery, secret probes, transport).

**Failure behaviour**
- Fail-**closed** where it must: signup rate limits when Redis is gone
  (`tenancy/signup.py`), the spend cap, the compliance gate, the dispatch tick when
  Postgres is unreachable, the webhook receiver's durable deadline (503 + poller, never a
  false ack).
- Fail-**open** where it is argued: the receiver's Redis fast path, the tick lease, the
  backup relay's stamp-file suppression when the state directory is unwritable, the
  missing `platform_state` row. Each has its reason written where the branch is.
- Object-storage failure: raises `StorageUnavailableError` (an `arq.Retry` subclass) on
  the recording copy — correct, since a lost recording is unrecoverable under TRAI's 90-day
  floor — and is best-effort on the delivered-body retain and the engine-payload archive,
  each with a stable alert code. The split is right in both directions.

**Deploy**
- `scripts/vps-deploy.sh` end to end. Preflight refusals (`.env`, the two `AWS_*` names,
  `PLATFORM_KEK`, clean checkout, disk, dev-compose project-name collision, Cloudflare IP
  age); `preflight_plan` running before `--dry-run` exits; migrate-before-swap with
  `transaction_per_migration=True`; the seed in the migrate profile; the rollback
  detection via `scripts/deploy_revision_check`'s exit code 3; the explicit `up -d redis`
  *without* `--no-deps` before the swap loop; the swap order workers → api →
  voice-runtime; `curl --max-time 5` on every health poll; the nginx backup-and-restore
  around `nginx -t`; the explicit envsubst variable list (an unrestricted `envsubst` on an
  nginx template is a classic and it is avoided).
- `.github/workflows/deploy.yml`'s four independent gates, `cancel-in-progress: false`,
  zero third-party actions, and `--expected-sha` closing the CI-validated-a-different-
  commit race.
- `components_for_paths` matches DEPLOYMENT §4c's table exactly, including the
  conservative direction (`apps/api/core/*` → all three).
- I specifically tested the `[[ -f "$STATE_DIR/deployed-sha" ]] && last=$(cat …)` line
  under `set -Eeuo pipefail` with an ERR trap — it does **not** trip errexit. Clean.

**Health**
- Three endpoints per service; `/healthz/live` touches nothing (correct: a Postgres blip
  must not make Docker restart every container mid-incident, and `compose.prod.yml`
  polls exactly that); D-128's public-verdict/private-detail split with the withheld
  detail written to `health_not_ready`; `ARQ_QUEUE_KEY` matching arq's default; deferred
  jobs correctly not counted as stale (their scores are in the future, so the clamp to 0
  is right).
