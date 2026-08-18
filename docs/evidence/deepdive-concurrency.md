# Deep dive: concurrency and time, across `apps/api` and `apps/workers` (D-320 – D-322)

A sweep of the two axes CLAUDE.md names beside money — **concurrency and time** — as a
CLASS rather than feature by feature. Money had its own pass
(`docs/evidence/deepdive-money.md`); nothing it already reported is repeated here, and
neither are the surfaces `audit-correctness.md` and `audit-reliability.md` cleared.

Scope: `apps/api/**` and `apps/workers/**`, every transaction boundary and state
transition. Out of scope by assignment and untouched: the engine adapters,
`apps/web/**`, the compliance module.

Every item is marked **PROVEN** (reproduced by running code against this tree and a
database migrated from base to head) or **REASONED** (derived from reading).

**Environment note.** The shared `calevate_replay` database was stamped at a revision
(`b7e4c1a90d38`) that does not exist in this branch's history — a sibling's migration —
so `alembic upgrade` could not run against it and any migration of my own was impossible
there. Everything below was measured against a private `calevate_conc` database created
from base to this branch's head plus the one migration added here. No sibling's database
was altered.

---

## FIXED

### F-1 — `authn`'s three "only the newest credential works" rules were retire-then-issue with nothing serializing them, so two overlapping requests left two live credentials — **PROVEN** (D-320)

`apps/api/authn/otp.py` opens with a section headed ONE LIVE CHALLENGE PER (SUBJECT,
PURPOSE) and rests the whole guess budget on it:

> Issuing a new code invalidates the previous one. Without that rule, "resend the code"
> becomes an attempt-budget reset: an attacker requests twenty codes and gets twenty lots
> of five guesses against a moving target, and the per-row ceiling means nothing.

`service.request_password_reset` makes the same promise about links — "only the newest
link works. Without this, 'click forgot password three times' leaves three live keys in a
mailbox for an hour" — and `service.confirm_password_reset` makes it about a password
change: burn every outstanding reset link, so "an attacker who triggered a reset, then
watched the victim change their password by other means" does not still hold a key.

All three were implemented the same way: an `UPDATE ... WHERE <live> IS NULL` followed by
an `INSERT`. Two statements, one transaction, and nothing making the pair exclusive. Under
READ COMMITTED two of them interleave with no conflict for the database to detect — A's
retire cannot see the row B has not committed, B's cannot see A's, and both then insert.

**Measured**, two `issue_challenge` calls for one admin subject, the second opening while
the first was still uncommitted:

```
live challenges: 2
retired code accepted: True   newest code accepted: True
```

Two valid one-time codes for one person, from a double-tap on "resend" — exactly the
accumulation the docstring says the rule prevents. `verify_challenge`'s per-row ceiling is
unchanged by it, so the budget does not literally double; what doubles is the number of
codes a guess can hit, and what disappears is the invariant that the newest code is the
only live one.

**Fix.** New `apps/api/authn/locks.py`: `lock_subject_credentials` takes
`pg_advisory_xact_lock(hashtextextended('authn:subject:{realm}:{subject}', 0))` — the
house primitive for a read-decide-write whose critical section IS a transaction
(BACKEND-PATTERNS §5, following `billing/service.lock_tenant_credits` and
`kb/service._lock_agent_publishes`). It is called at the top of `otp.issue_challenge` and
`tokens.invalidate_outstanding`, which are the two statements that own the RETIRE half;
every caller that needs "only mine survives" already runs one of them first, in the same
transaction, and the lock is transaction-scoped so it is still held through their INSERT.

The key is the SUBJECT, not (subject, purpose): the reset path spans two tables and a
password change, and a per-purpose key would let a reset request slip a new link in
between `set_password` and the `invalidate_outstanding` meant to kill it.

Migration `f1c8b7d5a903` adds `ux_auth_otp_challenges_live`, a partial unique index on
`(realm, subject_id, purpose) WHERE consumed_at IS NULL`. **It is not the fix** and the
migration says so: it is the invariant written where `pg_catalog` can hold it, against a
future writer that forgets the lock. An index-only fix was rejected for the reason
`_lock_agent_publishes` rejects one — the loser would meet a unique violation, so a person
who pressed "resend" twice would get a 500. `auth_email_tokens` deliberately gets no
equivalent index: "one live token" is true of `password_reset` and false of
`email_verify`, which nothing invalidates, so an index there would refuse a resend that is
allowed.

**Test.** `tests/authn_credential_race_test.py`, four tests. The overlap is FORCED, not
hoped for: the first writer holds its transaction (and therefore its lock) open behind an
`asyncio.Event`, and the second starts only once the first has taken it. Each fixed test
asserts two things — that one credential survives, and that the second writer WAITED — so
a pass cannot come from the two never having met. Two negative controls stub the lock out
and assert the same harness breaks: the OTP pair now raises `IntegrityError` (the index
catching what the lock prevents) and the token pair ends with two live reset links, which
is the raw defect reproduced.

**Sabotage.** Replacing both `lock_subject_credentials` calls in the source with `pass`
turns `test_two_overlapping_resends_leave_one_live_challenge` and
`test_two_overlapping_reset_requests_leave_one_live_link` red (`assert 2 == 1`); restoring
them turns all four green.

### F-2 — The reliability triad's terminal transitions were blind UPDATEs, so an abandoned holder's late report reopened work somebody else had already finished — **PROVEN** (D-321)

`mark_outbox_failed` carries `AND status = 'pending'` and its docstring explains, at
length, that the guard is "load-bearing rather than decorative":

> without it a late failure report drags a message that has ALREADY been published back to
> pending, and the next dispatcher tick queues its job a second time. For
> `deliver_outbound_webhook` that is a duplicate POST into a client's CRM.

The other four terminal writers in the same module had no such guard:

```
complete_idempotency   UPDATE ... WHERE id = :id
fail_idempotency       UPDATE ... WHERE id = :id
mark_inbox_processed   UPDATE ... WHERE id = :id
mark_inbox_failed      UPDATE ... WHERE id = :id
```

**The race is one this module deliberately creates.** `claim_idempotency` hands a lapsed
`processing` record to a SECOND holder by design — "a crashed attempt must not own the key
until the TTL sweep" — and `claim_inbox_event` does the same, because "an at-most-once
engine event whose key says duplicate is a silently dropped call". From the moment of a
re-claim, two callers legitimately hold one row id, and the first is by definition the one
whose report arrives late. Once you accept the re-claim (the code does, deliberately), the
late report is not hypothetical.

Consequences, which are worse than the outbox's because nothing dedupes behind them:

* an idempotency record reopened by a late `fail_idempotency` answers the client's next
  retry `fresh` instead of replaying the stored response. On `POST /v1/leads/{lead_id}/call`
  that is a **second real phone call to a member of the public**; on
  `POST /v1/calls/{call_id}/assist` a second paid model run. `scope_key`'s own docstring
  names this exact harm when arguing why the fingerprint key must be stable;
* an inbox row reopened by a late `mark_inbox_failed` makes the vendor's next retry
  re-drive the whole post-call pipeline for a call already metered, extracted and
  notified on.

**Measured**, driving the module's own documented recovery — claim, age `updated_at` past
`CLAIM_LEASE`, re-claim, second holder resolves, first holder reports:

```
idempotency: third claim state  = "fresh"      (expected "replay")
inbox:       third claim state  = "claimed"    (expected "duplicate")
```

**Fix.** `complete_idempotency` and `fail_idempotency` CAS on `status = 'processing'`;
`mark_inbox_processed` and `mark_inbox_failed` CAS on `status IN ('processing',
'enqueued')` — `enqueued` because the voice-runtime receiver writes it before handing the
event to a worker, and the worker's terminal report arrives from there. A lost CAS is a
WARNING via `_late_report`, not a raise: the reporting attempt has nothing left to do and
its request is already answered, but an attempt outliving its lease is the signal that
`CLAIM_LEASE` is shorter than something real in production, and an operator who never sees
it cannot learn that.

**Test.** `tests/reliability_late_report_test.py`, three tests covering both tables and
both directions (a late failure after a completion, and a late completion after a
release). The lease is expressed by moving `updated_at` back rather than by sleeping ten
minutes — that column IS the lease's input, so this is the mechanism's own condition, not
a simulation of it.

**Sabotage.** Widening the two guard constants to include the terminal states turns all
three red; restoring them turns them green.

### F-3 — Two deadlines were written by the application's clock and judged by the database's — **PROVEN** (D-322)

`idempotency_records.expires_at` and `invitations.expires_at` were both written as
`datetime.now(UTC) + TTL`, while every reader compares them with the DATABASE's clock:

| column | written | read |
| --- | --- | --- |
| `idempotency_records.expires_at` | `datetime.now(UTC) + IDEMPOTENCY_TTL` | `sweep_idempotency`: `expires_at < now()` |
| `invitations.expires_at` | `datetime.now(UTC) + INVITE_TTL` | `admin.service`: `expires_at > now()` in the pending probe **and** in `accept_invitation`'s burn |

That is wrong twice over. By the app/DB host skew, which is unbounded and invisible. And,
on every deployment regardless of skew, by the **age of the transaction**: Postgres `now()`
is transaction START time, while the Python expression is evaluated when the statement is
built, so a row minted after other work in the same transaction quietly outlives its stated
TTL by however long that work took. `create_invitation` really does run after other work —
`assert_account_open`, the membership probe and the pending probe all precede its INSERT.

**Measured**, with one 500ms statement ahead of the write:

```
idempotency_records:  expires_at - created_at = 1 day, 0:00:00.501853   (TTL is 1 day)
invitations:          expires_at - created_at = 3 days, 0:00:00.506436  (TTL is 3 days)
```

**Fix.** Both are now `now() + make_interval(secs => :ttl_s)` — the same clock, the same
instant, as the column beside them and as every reader. The repo had already made this
correction once, for the outbox's retry rung (`_BACKOFF_INTERVAL_SQL`); these are the two
places it had not reached.

**Test.** `tests/reliability_late_report_test.py::test_the_idempotency_ttl_is_measured_by_one_clock`
and `tests/admin_security_test.py::test_the_invitation_deadline_is_measured_by_one_clock`
age the transaction with a `pg_sleep(0.5)` and assert `expires_at - created_at` is EXACTLY
the TTL. Reverting either write makes the corresponding test fail by the sleep.

---

## LOOKED AT AND CLEAN

Named so a later pass knows what has been walked and does not re-walk it.

### Read-then-write — **REASONED**, one defect (F-1), rest clean

Every read-decide-write I could find already takes its lock or its CAS BEFORE the read:

* `billing/service.lock_tenant_credits`, `billing/caps.lock_tenant_spend_state` — taken
  before the balance/cap reads (the money pass covered these);
* `tenancy/members.lock_owner_ids` — `SELECT ... FOR UPDATE` over the whole owner set with
  `ORDER BY user_id`, and the docstring correctly argues the EvalPlanQual recheck and why
  locking the SET rather than the row is what makes the last-owner rule hold;
* `kb/service` version numbering and `ops/secret_service` version numbering — `MAX(version)
  + 1` under a per-key advisory lock;
* `ops/config_service` — per-key advisory lock before the validate-and-write;
* `compliance/deletion._lock_subject`, `compliance/tenant_erasure` — lock before the "is one
  already open?" probe;
* `flags/service.set_flag` — insert arm is `ON CONFLICT DO NOTHING` with `rowcount == 0`
  meaning lost, update arm carries the value it read in the WHERE clause;
* `quality/sampling.draw_week_sample` — `UNIQUE (tenant_id, call_id)` plus
  `ON CONFLICT DO NOTHING`, so a re-run converges rather than re-drawing;
* `campaign_dispatch`'s auto-complete `SELECT count(*) ... WHERE status IN ('pending',
  'dialing')` looks like a read-then-write and is not: every transition that produces
  `pending` acts on a `dialing` row, so under READ COMMITTED the count sees the pre-image
  and cannot observe zero while a contact is on its way back to the ladder.

### State transitions — **REASONED**, one defect (F-2), rest clean

`apps/api/db/transition.py` is the single primitive and it is genuinely single: campaign
pause/resume, lead status, KB approve/reject and organization lifecycle all route through
it, and its ordering argument (CAS first and unconditionally; the discriminating SELECT
only ever on the losing path) is correct. `auth_sessions` rotate/supersede/revoke are all
CAS with the guard read in the same statement. `outbox_messages`' claim, publish and
failure arms are CAS. The four terminal writers that were NOT are F-2.

### Transactions held across a vendor round trip — **REASONED**, no new defect

Three worker paths were checked and all three already split the transaction around the
network call, each with the pool-starvation argument written down:
`outbound_webhooks.deliver_outbound_webhook` (read-and-close, POST, reopen),
`pipeline._copy_recording_once`, `campaign_dispatch._dispatch_for_campaign`.

Two API paths DO hold a lock across vendor calls and both are deliberate and documented:
`agents/service.publish_agent` holds `SELECT ... FOR UPDATE` on the agent row across
`create_agent`/`update_agent` and the `verify_publish` read-back, and
`kb/service.publish_source` holds `pg_advisory_xact_lock(kb:publish:{agent})` across the
detach/attach sequence. `_lock_agent_publishes` states the cost in its own words —
"publishes for one agent queue, each for the length of its engine round trips … This is an
admin-console path, not the audio path, and it is per agent". Each holds ONE pooled
connection, on a path a human clicks; `MAX_NESTED_CONNECTIONS` is not threatened by them.
Reported rather than changed: removing the lock reopens the divergence D-41 exists to
prevent, and the cost is bounded and argued.

### Time — **REASONED**, two defects (F-3), rest clean

* No naive datetime anywhere in `apps/`, `packages/` or `scripts/` — `datetime.now()`,
  `utcnow()` and `today()` have zero occurrences.
* IST has one spelling per question: `billing/plans.ist_billing_month` for months (the
  money pass made that true), `crm/performance.IST_DAY_SQL` for days,
  `quality/sampling._IST_WEEK_SQL` for weeks — and the last imports `IST_ZONE` from the
  first rather than retyping `Asia/Kolkata`.
* Deadlines other than F-3's two are self-consistent: the whole of `authn` writes and
  compares with the app clock (`now=` is injectable, which is why), and
  `compliance/consent` and `compliance/preference_scrub` do the same.
* Retry rungs and leases are computed in SQL (`_BACKOFF_INTERVAL_SQL`, `locked_until =
  now() + ...`, `updated_at < now() - :lease`), so no ladder compares two clocks.

### Deadlocks — **REASONED**, none found

Eleven advisory-lock sites, plus the row locks. An AST scan over `apps/` for a function
that writes an audit entry BEFORE calling anything that takes a lock returns nothing, and
reading the call sites confirms the ordering is uniform: the domain lock
(`credits:{tenant}`, `spend:{tenant}`, `config:{key}`, `secret:{key}`, `kb:publish:{agent}`,
the campaign row) is always taken first and `audit:chain` — the one GLOBAL lock — is always
taken last, inside `write_audit`, at the end of the mutation. `authn._audit` deliberately
opens its own transaction rather than holding a credential transaction across the chain
lock, so the new `authn:subject:*` lock never meets it either. No path takes two domain
locks, so there is no pair to invert: `secret_service.rewrap_all` takes only
`platform:kek` and `set_secret` takes only `secret:{key}`, and the rewrap's UPDATE is
guarded on `dek_wrapped = :old` so it does not need the second one.

### Retry safety — **REASONED**, one defect (F-2), one thing worth knowing

The outbox claim commits its `attempt_count` bump on its own connection and carries a
durable lease; the inbox and idempotency claims re-claim by CAS; `deliver_outbound_webhook`
takes its attempt number from `ctx["job_try"]` rather than reading and incrementing.

`workers/notifications._record_attempt` and its WhatsApp twin are update-then-insert on
`lead_events` with **no unique key**, so two genuinely concurrent attempts would both find
`rowcount == 0` and both insert a timeline row. I could not reproduce it and I do not
believe it is reachable: `enqueue_outbox_once` single-flights the enqueue on
`hot-lead:{lead_id}:{call_id}`, and arq runs one attempt of one job id at a time. Recorded
rather than changed, and the reason is stated plainly: the available fix is a partial
unique index on jsonb expressions, which would convert an unreproducible duplicate row
into a hard worker failure, and there is no evidence to justify that trade.

### Swallowed failures on write paths — **REASONED**, clean

All 49 `except Exception` handlers in `apps/api` and `apps/workers` were read. None is a
bare `pass`. The per-tenant sweeps (`retention`, `qa_sampling`, `billing`) log-and-continue,
and each tenant's work is its own transaction, so a caught failure cannot leave a
half-applied transaction reported as success. `throttle.check` fails CLOSED and says why;
`throttle.record_failure` and `throttle.clear` fail open and say why; `_retain_body` never
raises and alerts on a stable code instead.

---

## STILL OPEN

Nothing here waits on engineering. One thing waits on something outside this repo:

* **Nothing.** No finding in this pass is blocked on a vendor, a registration or a
  commercial term.
