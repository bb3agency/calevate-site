# Correctness and concurrency audit — `apps/api` and `apps/workers`

**Date**: 17 August 2026 · **Surface**: money, concurrency, transactions, time, error
handling and state machines in `apps/api` and `apps/workers`. · **Mode**: find and
document. Nothing in this pass was fixed; no source file was touched.

**Standard audited against**: `docs/BACKEND-PATTERNS.md` §4 (the reliability triad) and
§5 (CAS doctrine, "never a lock held across a network call"), `docs/DATA-MODEL.md`, and
CLAUDE.md hard rules 4 (append-only), 6 (PII in logs) and 7 (money).

**Prior art checked before writing anything**: `docs/ROADMAP.md` §6 (the whole decision
log), `docs/OPERATIONS.md` §2, `docs/evidence/our-gates-audit.md`, `docs/LEGAL-SURFACE.md`,
`docs/AUTH-MIGRATION.md` §11. Nothing below is a restatement of a recorded decision, and
nothing below argues that a recorded decision is wrong.

**In flight, and therefore excluded**: a sibling change is removing Clerk and touches
`apps/api/core/auth.py`, the Clerk modules and `apps/web`. `apps/api/core/deps.py::db`
is read below only for the property it has always had (commit on clean exit, rollback on
exception); the auth dependency it sits behind was not audited.

**Honest summary**: this is a well-defended codebase. The money core — `billing/service.py`,
`billing/payments.py`, `billing/caps.py`, `billing/rates.py`, `workers/pipeline.py::_meter` —
survived a deliberate hunt for a float, a lost paisa, a double debit and a lock-order
inversion with nothing to report. Two findings are real and worth acting on; the rest are
smaller. The count is deliberately short.

| # | Severity | Title |
|---|---|---|
| 1 | **High** | The `Idempotency-Key` on the two paid client-initiated routes shares a transaction with the payment it is supposed to guard |
| 2 | **High** | `dispatch_call` places the engine call BEFORE the `calls` row, which is the opposite of what it promises — an accepted dial can leave no record and be re-dialled |
| 3 | Medium | `max_overflow=0` rests on a stated invariant ("no path holds two sessions at once") that two live paths break |
| 4 | Medium | Three hot paths hold a database transaction open across a vendor HTTP round trip, one of them while claiming to do the opposite |
| 5 | Low | `_pipeline_settled`'s "was a CRM fan-out owed" predicate is a second, narrower spelling of `enqueue_events`' own |
| 6 | Low | The campaign retry ladder writes `next_attempt_at` from the app clock and reads it against the database clock |
| 7 | Low | `platform_config.refresh()` is documented as "never raises", and half of it is outside the `try` that makes that true |

---

## 1. HIGH — the idempotency claim rolls back with the side effect it exists to protect

**Where**
- `apps/api/crm/routes.py:289-296` and `:368-370` — `POST /v1/calls/{call_id}/assist`
- `apps/api/crm/routes.py:992-999` and `:1046-1052` — `POST /v1/leads/{lead_id}/call`
- Contrast: `apps/api/billing/payment_routes.py:333-356` (`_create_order_once`)
- Mechanism: `apps/api/core/deps.py:27-30` — "Commits on clean exit, rolls back on any
  exception"; `apps/api/db/session.py:127-137` — one transaction per request.

**The failure sequence** (assist route, the more expensive of the two):

1. Client `POST`s with `Idempotency-Key: K`. The route is required to carry one —
   `crm/routes.py:277-288` refuses without it, and the docstring at `:261-271` says why:
   "a repeated assist is a second, silent payment to Google".
2. `claim_idempotency` (`:289`) INSERTs the `processing` record **into the request's own
   transaction**. Nothing is committed.
3. `run_assist` (`:318`) runs the model. **The provider has now been paid.**
4. `meter_assist` (`:336`) writes the `usage_events` rows — still uncommitted.
5. `write_audit` (`:338`) raises. Any raise will do: `AUDIT_CHAIN_SECRET` unset or short
   (BACKEND-PATTERNS §7 makes the API refuse to write an entry), a statement timeout, a
   severed connection, a serialization failure on the audit chain's advisory lock.
6. `deps.db` rolls the transaction back. **The idempotency record, the usage rows and the
   audit row all disappear. The payment does not.**
7. The client retries with the same `K` — which is what an `Idempotency-Key` is for, and
   what the console's own retry does. `claim_idempotency` finds no row, INSERTs a fresh
   one, returns `fresh`, and step 3 runs again. Second payment, second unrecorded spend,
   and the platform AI brake (`ai_quota._BUMP_PLATFORM_SQL`) never moved for either.

`POST /v1/leads/{lead_id}/call` has the identical shape with a phone call in place of a
model call: claim at `:992`, `dispatch_call` at `:1026`, `write_audit` at `:1035`,
`complete_idempotency` at `:1047`. A rollback between `:1026` and the commit erases the
claim while the customer's phone has already rung; the retry rings them again.

**Why this is a finding rather than a nit**: the repo already knows the answer and wrote
it down, in the same package. `billing/payment_routes.py:333-339` — *"**The claim commits
BEFORE the network call, in its own transaction.** Two clicks racing would otherwise both
be inside `INSERT … ON CONFLICT`, so the loser blocks on the unique index until the
winner's transaction ends — i.e. a database lock held across a call to a payment
provider"* — and it uses three separate `tenant_session` blocks (claim / call / complete)
plus `fail_idempotency` on the failure arm. The two CRM routes use one transaction for
all three phases. That is two ways of doing one thing, and the second one does not work.

**Proven or reasoned**: reasoned, from code that is unambiguous. The transaction boundary
is `deps.db`'s documented contract and the ordering is straight-line. Not executed.

**What would fix it (described, not implemented)**: give the two CRM routes
`_create_order_once`'s shape — claim in its own committed transaction before the paid
call, `fail_idempotency` in its own transaction on the failure arm, `complete_idempotency`
in a third. That is the existing solution in this repo; adopting it also removes the
second way of doing this.

---

## 2. HIGH — `dispatch_call` calls the engine before it writes the call row

**Where**: `apps/api/agents/service.py:636-707`. The engine call is at `:674`; the
`INSERT INTO calls` is at `:684-701`.

**The contradiction**: the function's own docstring (`:638-640`) states

> A `queued` call row is written BEFORE the engine call returns, so a dispatch that
> succeeds at the vendor but fails on our side still shows up rather than becoming an
> invisible charge.

The row cannot be written before the engine call returns: `engine_call_id` is the
row's conflict key and its value **is** the engine's return value (`handle`, `:674`,
used at `:696`). The promise is structurally unachievable in the current shape, and
everything downstream is written as if it holds.

**Failure sequence A — the invisible charge.** `start_outbound_call` returns a handle
(the vendor is now dialling). The INSERT, `assignment.record` (`:706`) or the commit
fails — a pool timeout, a statement timeout, a worker killed mid-transaction, an
`asyncio.CancelledError` from arq's `job_timeout`. The transaction rolls back. There is
no `calls` row, so: no metering (`_meter` is keyed off a call row), no `usage_events`, no
`spend_state` movement, no wallet debit — and the reconciliation poller can only repair it
inside its own window, because `_pipeline_settled`
(`apps/workers/pipeline.py:2103-2112`) looks the execution up by `engine_call_id` in
`calls`, returns `missing_call`, and `reconcile_executions` (`:2178`) lists only the last
30 minutes. Past that window the call is billed by the vendor and unknown to us. That is
exactly the outcome the docstring promises cannot happen.

**Failure sequence B — the second phone call.** On the campaign path
(`apps/workers/campaign_dispatch.py:657-696`), the contact was claimed `pending →
dialing` with `attempts + 1` in a transaction that **already committed** (`:600-627`),
and the dial then runs in its own transaction. If that transaction fails after the
engine accepted, `last_call_id` is never written (`:689-696`). Thirty minutes later
`_reap_stuck_dialing` (`:893-906`) returns the contact to `pending` with
`next_attempt_at = now() + 30 minutes` and **its attempt count unchanged**, so a contact
under a slider of three attempts is dialled a second time although their phone already
rang. `resolve_campaign_contact` cannot rescue it: it matches on
`cc.last_call_id = :cid AND cc.status = 'dialing'` (`:812-822`), and `last_call_id` is
NULL.

**Proven or reasoned**: the ordering and the docstring contradiction are proven by
reading — no concurrency is required to see them. The two consequences are reasoned.

**What would fix it (described, not implemented)**: either write a `queued` row keyed on
a locally minted correlation id before the engine call and stamp `engine_call_id` onto it
afterwards (which makes the docstring true), or delete the promise from the docstring and
push the guarantee onto the poller explicitly, accepting the 30-minute window as the
bound. The first is what the rest of the system already assumes. Whichever is chosen,
`_dispatch_for_campaign` should record the contact's dial attempt against something that
survives the failure, so `_reap_stuck_dialing` cannot re-ring a phone.

---

## 3. MEDIUM — the no-overflow pool rests on an invariant two paths break

**Where**: `apps/api/db/session.py` (`get_engine`'s docstring, the paragraph beginning
"Overflow is safe to remove only because"):

> no code path here holds two sessions at once: every `async with *_session()` block
> closes before the next opens (checked across apps/api and apps/workers), so a pool at
> its ceiling cannot deadlock against itself.

Two paths hold two connections from the same pool simultaneously:

1. **`apps/workers/dispatcher.py:78-80`** — `dispatch_outbox` opens
   `untenanted_session()` and then calls `claim_outbox_batch(session)`, which by design
   takes a **second** connection off the same engine
   (`apps/api/reliability/service.py:384-393` `_claim_engine`, `:431-449`
   `async with engine.begin()`). The nesting is deliberate and correct for its own reason
   (the claim must commit independently); it is simply not what the pool comment says.
2. **`apps/api/compliance/service.py:306`** — `check_dispatch` calls
   `get_platform_status()`, which on a memo miss with Redis unavailable falls through to
   `apps/api/core/loadshed.py:157-163 _read_durable()` → `untenanted_session()`. Every
   caller of `check_dispatch` already holds a session: the campaign dispatcher's
   per-contact `tenant_session` (`campaign_dispatch.py:630`, `:649`) and the request
   session on `POST /v1/leads/{lead_id}/call` (`crm/routes.py:1008`). The 5-second memo
   (`loadshed._MEMO_TTL_S`) hides this almost always, and stops hiding it precisely when
   Redis is down — which is when the API is busiest with retries.

**The failure sequence**: Redis is unavailable. `_cache_read` raises and is swallowed
(`loadshed.py:110-111`), so every memo expiry (5s) sends the *next* caller to Postgres.
With `db_pool_size = 16` (`packages/shared/src/calevate_shared/config.py:148`) and
`max_overflow = 0`, sixteen concurrent requests that each hold a tenant session and reach
`check_dispatch` on a cold memo occupy all sixteen connections and then each wait for a
seventeenth. Every one of them blocks for `_POOL_TIMEOUT_S = 5.0` and then fails. This is
self-deadlock against a pool at its ceiling — the exact outcome the comment says cannot
happen.

**Proven or reasoned**: the nesting is proven by reading (three call sites, one engine).
The saturation scenario is reasoned; it was not reproduced, and the memo makes it
uncommon.

**What would fix it (described, not implemented)**: either restore the invariant —
resolve the platform status before opening the caller's session and pass it in, and give
the outbox claim its own connection budget rather than the request pool's — or state the
real invariant ("at most two connections per task") and size the pool against it. What
must not stay is a capacity decision justified by a property the code does not have.

---

## 4. MEDIUM — transactions held open across vendor round trips

**Where**
- `apps/workers/outbound_webhooks.py:236-296` — `load_endpoint`, the delivery and
  `record_delivery` are all inside one `tenant_session`. The delivery is an HTTP POST with
  `DELIVERY_TIMEOUT_S = 10.0` (`apps/api/integrations/service.py:102`), or a Google Sheets
  append with no stated bound (`sheets_sync.append_event`).
- `apps/workers/campaign_dispatch.py:630-696` — the per-contact `tenant_session` wraps
  `campaign_dialable_now`, `check_dispatch` **and** `dispatch_call`, i.e. the engine POST
  plus up to `THROTTLE_MAX_ATTEMPTS` retries with `asyncio.sleep` backoff
  (`apps/api/engine/bolna.py:630-650`, `REQUEST_TIMEOUT_S = 10.0`).
- `apps/api/crm/routes.py:1008-1044` and `:307-357` — the request transaction wraps the
  engine dial and the model call respectively (see finding 1).

The campaign case carries a false claim: `_dispatch_for_campaign`'s docstring
(`campaign_dispatch.py:543`) says the claim/dial split *"stops a DB transaction being held
open across an engine HTTP round trip."* It stops the **claim's** transaction being held
open. The dial's own transaction is opened at `:630` and the engine call happens at `:658`,
inside it.

**Why it matters**: BACKEND-PATTERNS §5 names this outright, and the concrete cost is
finding 3's: each in-flight vendor call is a pooled connection sitting idle-in-transaction
for up to ten seconds (longer with the throttle ladder). `apps/workers/settings.py` sets
no `max_jobs`, so worker concurrency is arq's default against a sixteen-connection pool
with no overflow, and a slow receiver converts a delivery incident into a
database-capacity incident for every other worker job.

**Proven or reasoned**: reasoned. The transaction boundaries and the timeouts are read
directly; no measurement was taken.

**What would fix it (described, not implemented)**: close the session before the vendor
call and reopen it to record the outcome — the shape `_create_order_once` already uses,
and the shape the campaign claim/dial split already uses one level up. Where the row must
be written atomically with the result, write the *intent* first and the *outcome* second.

---

## 5. LOW — two spellings of "which endpoints get this event"

**Where**: `apps/workers/pipeline.py:2097-2098` versus
`apps/api/integrations/service.py:251-259`.

`enqueue_events` writes one outbox row per endpoint matching
`active = true AND kind = ANY(DELIVERABLE_KINDS) AND :event = ANY(events)`.
`_pipeline_settled`'s `crm_fanout_owed` asks
`active = true AND 'call.completed' = ANY(w.events)` — **the `kind` predicate is missing**.

**The failure sequence, if the two ever diverge**: a tenant holds an active endpoint
subscribed to `call.completed` whose `kind` is not in `DELIVERABLE_KINDS`.
`enqueue_events` writes zero rows, so `_mark_crm_notified` is never called
(`pipeline.py:944-946`) and `crm_notified_at` stays NULL. `_expected_artifacts` therefore
expects `crm_fanout` (`:2006-2007`), `present["crm_fanout"]` is False, and past
`PIPELINE_STALL_AFTER` every completed call for that tenant reads `unfinished_pipeline`.
The poller re-drives the whole pipeline once an hour per execution while the execution is
inside its 30-minute listing window — including `extract_call`, which is a billed model
round trip with no idempotency of its own.

This is **not reachable today**: `ck_outbound_webhooks_kind_enum`
(`alembic/versions/05bba2f3c19c_db_core_with_rls.py:238`) allows exactly
`('webhook', 'google_sheets')`, which is exactly `DELIVERABLE_KINDS`
(`integrations/service.py:78`). It is reachable the moment a third kind is added to the
CHECK ahead of its worker, which is the ordinary way a third kind arrives. The probe's
own docstring (`pipeline.py:1985-1991`) states that it "mirrors `integrations.
enqueue_events`' own endpoint predicate" — it mirrors two thirds of it.

**Proven or reasoned**: the divergence is proven by reading both predicates; the
consequence is reasoned and currently unreachable.

**What would fix it (described, not implemented)**: export the predicate from
`integrations/service.py` as SQL the way `billing.caps.over_cap_sql` and
`pipeline.EXTRACTION_OWED_SQL` are exported, and have the probe interpolate it rather than
restate it.

---

## 6. LOW — the campaign retry ladder mixes the app clock and the database clock

**Where**: `apps/workers/campaign_dispatch.py:964-970`.

`_record_failure` schedules the next attempt with a value computed in Python:

```
{"next": datetime.now(UTC) + timedelta(minutes=minutes), "id": contact_id}
```

The claim that reads it back compares against the database's clock —
`AND (next_attempt_at IS NULL OR next_attempt_at <= now())` (`:606`). Every other write to
the same column uses the database clock: `_refuse_contact` (`:886`) and
`_reap_stuck_dialing` (`:900`) both write `now() + interval '30 minutes'`.

**The failure sequence**: the worker host's clock runs *n* seconds ahead of the database
host's. A contact whose dial failed is scheduled at app-now + 30 min, which the database
reads as db-now + 30 min + *n*, so the ladder is late by the skew; a worker clock behind
the database's makes it early, and an early rung on a retry ladder is a second call to a
person sooner than the policy says. The magnitude is the skew, so this is small on a
well-run fleet and is not small on one where NTP has drifted — and nothing anywhere would
report it.

**Proven or reasoned**: reasoned. The mixed sources are proven by reading; no skew was
introduced to measure it.

**What would fix it (described, not implemented)**: compute the interval in SQL, as the
other two writers on this column already do (`now() + make_interval(mins => :minutes)`),
so the column has one clock.

---

## 7. LOW — `refresh()` promises never to raise, and half of it is outside the `try`

**Where**: `apps/api/core/platform_config.py:791-798` (the promise), `:820-858` (the
`try`), `:860-898` (the work that is not inside it), `:901-908` (`_poll_forever`, which
has no guard of its own and whose comment says *"`refresh` never raises, so this loop
cannot die"*).

The `try` covers `_sentinel()`, `_read_rows()` and `_read_secrets()`. Outside it:
`_resolve(rows, effective_env())`, `overrides.update(secrets.values)`,
`apply_platform_overrides(overrides)` and the `ConfigSnapshot` construction. Today none of
those raises — `_resolve` (`:759-788`) logs and skips every bad row deliberately, and
`apply_platform_overrides` (`core/settings.py:266-296`) filters rather than refuses — so
the promise holds by the current contents of those two functions rather than by structure.

**The failure sequence, if it ever stops holding**: one exception out of `_resolve` or
`apply_platform_overrides` propagates through `refresh()`, out of `_poll_forever`, and the
task ends. `start_config_refresher` (`:911-929`) is only called at startup, so the process
serves the last snapshot for ever, silently: the two alerts that exist for this
(`platform_config_never_loaded`, `platform_config_stale`) are inside the `except` that no
longer covers the raising code, and the task's own exception is swallowed by asyncio into
a never-retrieved result. An operator changing a console value would see it applied on
some processes and not others with nothing red anywhere.

Also here, and smaller: `:929` uses `asyncio.get_event_loop()`, which is deprecated in
Python 3.12 when there is no running loop. It is called from a lifespan today, so a loop
is running; `asyncio.get_running_loop()` says that rather than relying on it.

**Proven or reasoned**: reasoned, and honestly latent — no input reaching this code today
raises.

**What would fix it (described, not implemented)**: move the `try` to cover the whole
body of `refresh`, or wrap the `await refresh()` inside `_poll_forever` so the loop cannot
be ended by any exception. Either makes the docstring's promise structural.

---

## Examined and found clean

This list is the evidence that the two High findings are the two High findings, rather
than the two that happened to be looked at.

**Money (hard rule 7)** — no float reaches any currency path. Checked by reading and by
grep across `apps/api/billing`, `apps/workers/billing.py` and `apps/workers/pipeline.py`:
the only occurrences of `float` in the billing package are the four validators whose job
is to *refuse* one (`credit_routes.py:236`, `payment_routes.py:132`,
`ai_quota_routes.py:88`, `cap_routes.py:93`).

- `billing/service.py::to_paise` / `allocate_paise` / `rate_to_display` — one rounding
  quantum, one explicit mode imported from `rates.ROUNDING`, never inherited from the
  ambient `decimal` context. `allocate_paise` is largest-remainder and raises when the
  parts do not add to the total rather than silently returning parts that do not.
- `billing/service.py::split_overage` / `overage_rungs` / `_tier_totals` — the panel's
  total is the sum of the invoice's printed lines by construction; the minutes are
  quantized exactly once, at `_tier_totals`, and nothing below it rounds a minute again.
- `billing/payments.py::inr_to_paise` / `paise_to_inr` — exact, with `bool` checked
  before `int` and a fractional paisa refused rather than rounded.
- `billing/service.py::record_entry` / `charge_for_call` / `find_entry_by_ref` — the
  advisory lock is taken before the dedupe read, not only before the write, so the
  check-then-write hole is closed on every writer. `clock_timestamp()` rather than `now()`
  on the ledger insert is correct and the reason given for it is correct.
- `billing/service.py::correct_tts_tier` (`:1280-1400`) — both ledgers keyed on
  `(tenant, call, ref)`; the wallet refund and the cost correction are the same set.
- `billing/payments.py::credit_captured_payment` — lock, then lookup, then write, then
  audit, all in one transaction; a same-reference different-amount replay is a 409 rather
  than an absorbed difference.
- `billing/ai_quota.py::purchase_ai_overage` / `record_ai_assist_usage` — the block is
  idempotent under the credit lock; the assist metering is idempotent on a
  server-minted `ref` enforced by a unique index rather than by a reader's `if`, and the
  platform brake is bumped only for rows that actually landed and only for the month the
  row landed in.
- `billing/caps.py` — `LEAST(admin, client)` in one exported CTE consumed by both
  writers, so the meter and `apply_client_caps` cannot disagree about the ceiling.
  `over_cap_sql`'s NULL handling (`COALESCE(x >= NULL, false)`) is right: an absent
  ceiling is an absent constraint, not a ceiling of zero.
- `workers/pipeline.py::_meter` — the pre-check is under `lock_call_writes`, the unique
  index is behind it, `unit_cost_paid` is a price per unit of `qty` and the quantum and
  mode are imported. The zero-duration-call residual is measured, documented and correct.
- `workers/pipeline.py::_billed_for_this_call` — the managed increment is
  `over(before + this) - over(before)`, order-independent, read under
  `lock_tenant_spend_state`, and a closed-month row correctly counts as zero minutes.

**Lock ordering** — every `pg_advisory_xact_lock` call site in the tree was enumerated
(`billing/service.py:198`, `billing/caps.py:186`, `workers/pipeline.py:1007`,
`compliance/audit.py:265`, `compliance/deletion.py:568`, `compliance/tenant_erasure.py:445`,
`kb/service.py:258,520`, `kb/reconciliation.py:205`, `ops/secret_service.py:222,386`,
`ops/config_service.py:299`). The only path that takes two of them is `_meter`, and it
takes them in one order (`call:` → `credit:` → `spend_state:`); nothing takes
`spend_state:` before `credit:`, which is what `caps.lock_tenant_spend_state:180-183`
claims. No inversion found.

**The reliability triad** — `reliability/service.py` read end to end. The outbox claim
commits its attempt bump on its own connection with a lease, `_dead_letter_exhausted_claims`
is what makes "walks to the DLQ" true for a message that kills its dispatcher,
`mark_outbox_failed`'s retry branch replaces the lease rather than clearing it, and every
terminal transition carries `AND status = 'pending'` as a CAS guard. The
`MATERIALIZED` + `ORDER BY created_at, id` argument for both claim statements is correct
and matters (rows enqueued in one transaction share `created_at` to the microsecond).
`claim_inbox_event`'s lease-based re-claim of an abandoned `processing` row is correct.

**Campaign dispatch** — the tick lease, the `pending → dialing` CAS with
`FOR UPDATE SKIP LOCKED`, the tenant budget spent once across a tenant's campaigns, the
re-read of the campaign's live status inside the claiming transaction, the per-contact
re-check of pause/window/DNC after the claim commits, and the attempt refund in
`_refuse_contact` for non-person-level refusals were each traced against a concurrent
interleaving and hold. `complete_or_rearm` + `emit_campaign_completed` in one transaction
is a correct transactional outbox.

**Scheduling** — `Recurrence.next_after` walks IST wall-clock days rather than adding a
fixed interval, and India has no DST, so the fixed `IST` offset is exact; the
strictly-after comparison is what stops a recurrence stalling on its own occurrence.
`_claim_occurrence`'s identity is the occurrence, not the clock, which is what makes two
racing ticks fire it once. `_fire_due_schedules` reads the clock once per tenant.
`RECURRENCE_CATCHUP` being shorter than the shortest expressible interval is load-bearing
and correct.

**Time** — a tree-wide grep for `datetime.utcnow()`, `datetime.now()` without a tz and
`utcnow()` across `apps/api`, `apps/workers` and `packages` returns **nothing**. Every
instant in the audited surface is timezone-aware. The IST billing month is computed in one
place per layer (`plans.ist_billing_month`, `billing._IST_MONTH`, `pipeline._ist_month`)
and `usage_summary` reads "which month is now" once and passes it around, which is right.

**Error handling** — no bare `except:` anywhere in `apps/api` or `apps/workers`. The 47
`except Exception` handlers were reviewed; none swallows a failure into a success path.
The two that come closest are deliberate and argued: `_tick_lease` fails open on a Redis
error (with the claim CAS still standing behind it) and `loadshed._cache_read` falls
through to Postgres. `arq.Retry` is used correctly in every worker that means "try again"
— `outbound_webhooks`, `pipeline._abandon_ingest`, `_abandon_post_call` — and the
docstrings correctly record that arq 0.28 finishes a job after one attempt for anything
else.

**State machines** — `_upsert_call_row`'s conflict clause moves status forward only, with
`completed` allowed to overwrite a terminal non-completed status; `launch_campaign`'s CAS
deliberately does not use `transition_status` (launching is not idempotent) and stamps
`dnc_scrubbed_at` in the same statement as the transition; `set_campaign_status` uses the
shared three-answer helper. `resolve_campaign_contact`'s `connected` write carries
`AND status = 'dialing'`.

**PII in logs (hard rule 6)** — spot-checked across every log line in the audited files:
ids, rule names, status codes, counts and provider names only. `hide_parameters=True` on
the engine is the right control for the one path that would otherwise leak transcript text
through a DBAPI error string.

**Deliberately not re-reported**: `_meter`'s month-rollover residual for an outbound-only
tenant (named in `pipeline.py:1441-1448` with the fix already in
`compliance.spend_capped`); the outbox `queue` column that routes nothing (D-162); the KB
publish lock held across engine calls (`kb/service.py:468-517` argues it, states its cost,
and names the rejected alternatives); `unit_cost_paid`'s zero-`qty` gap (measured, cited
and pinned by a test).

---

## What could not be determined

- **Nothing was executed.** Four sibling agents are auditing concurrently against a shared
  database, and the instruction for this work forbids the full suite; a targeted run of a
  single test file would have exercised the code these findings are *about* rather than
  the interleavings they turn on, so nothing here is claimed as proven-by-execution.
  Findings 1, 2 and 5 are proven by reading in the strict sense — the ordering and the
  predicate mismatch are visible in straight-line code and need no concurrency — and
  findings 3, 4, 6 and 7 are reasoned. Treat the severity of 3 accordingly: the nesting is
  a fact, the saturation is an argument.
- **The real concurrency of the worker fleet is unknown to this audit.** `arq`'s
  `max_jobs` is not set in `apps/workers/settings.py`, so the effective value is the
  library default. Findings 3 and 4 lean on it; the number that matters is the one a
  deployed worker actually runs with, and `infra/` has never been applied
  (`infra/README.md` §5), so there is no deployment to read it off.
- **Clock skew between the API/worker hosts and Postgres was not measured** (finding 6);
  in the compose development environment they are the same host, so the skew is zero and
  the defect is invisible there by construction.
- **The Clerk-removal surface was not audited** — `apps/api/core/auth.py` and the Clerk
  modules are being changed by a sibling agent in this same session, and a finding against
  a file mid-rewrite is a finding about a file that will not exist.
