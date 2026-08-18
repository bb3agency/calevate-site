# Deep dive: the schema itself, and the migrations that built it (D-192)

18 Aug 2026. Ground: `alembic/versions/**`, `apps/api/*/models.py`, `apps/api/db/**`, and the
relationship between what the ORM believes and what the database actually contains.

**Method.** Everything below is marked PROVEN (executed) or REASONED (read). Two scratch
databases were created for this work and dropped afterwards — `d192_scratch` (round-trip
target) and `d192_fresh` (pristine control) — so nothing here touched the shared
development database except the one `alembic upgrade head` that applies this pass's own
migration. No `make db-reset`, no bare `pytest`, no truncation.

Environment: PostgreSQL 16.15, 72 revision files, head before this pass `c7a1e93d40b8`
(62 tables).

---

## 1. FIXED — a tenant could lift a platform-wide DNC suppression (PROVEN)

**Severity: compliance.** `scope='global'` is described in DATA-MODEL §6 as "an ABSOLUTE
platform-wide suppression (a regulator/TSP instruction naming a number, or our own
permanent refusal), written only by `POST /v1/ops/dnc/global`".

`e4f2a86b13d7` closed the DELETE half of this and, in its own docstring, cleared UPDATE:

> "UPDATE was already safe and was checked rather than assumed: the same statement with
> `SET source = 'hijacked'` returns *new row violates row-level security policy*, because
> the NEW row fails `WITH CHECK`. Only DELETE was open."

The probe was real and the conclusion was wrong. `SET source = 'hijacked'` leaves the row
GLOBAL, which is what fails `WITH CHECK` for a tenant session. The update that **moves**
the row satisfies `WITH CHECK` exactly, because the new row IS a legitimate row for that
tenant.

Executed as `calevate_app` against `d192_scratch`, migrated base → head:

```
SET LOCAL app.tenant_id = '01900000-0000-7000-8000-00000000000a';

SELECT ... WHERE phone_e164 = '+919999000001';          -- 1 row (by design)
DELETE FROM dnc_list WHERE ... AND tenant_id IS NULL;   -- DELETE 0   e4f2a86b13d7 working
UPDATE dnc_list SET tenant_id = <me>, scope = 'tenant'
  WHERE phone_e164 = '+919999000001' AND tenant_id IS NULL;  -- UPDATE 1   <-- the hole
DELETE FROM dnc_list WHERE phone_e164 = '+919999000001';     -- DELETE 1
```

The suppression was gone from the table. Two statements, from an ordinary tenant session,
against a number a regulator named.

**Why nothing caught it.** `tests/rls_sweep_test.py` asks "can tenant A touch tenant B's
rows". A global row belongs to no tenant, so `tenant_id IS NULL` is outside every probe in
that file by construction — and `dnc_list` is the only table in this schema whose `USING`
mentions `tenant_id IS NULL` (confirmed against `pg_policy`). The behavioural pin that does
exist, `dnc_test.py::test_a_global_suppression_is_visible_to_a_tenant_and_not_removable`,
asserts the ROUTE's 422, which is `remove_entry`'s application check — the same layer
`e4f2a86b13d7` already argued was not the enforcement.

**Fix.** Migration `e7b45c19a308` adds `dnc_list_update_scope`, RESTRICTIVE FOR UPDATE,
predicate character-for-character its DELETE sibling's. `WITH CHECK` omitted deliberately:
for a policy that can carry both, PostgreSQL applies `USING` to the rows an UPDATE may
select and, with no `WITH CHECK` defined, uses the `USING` expression for the new row too
([PG16 CREATE POLICY]). Restrictive policies are ANDed with the permissive ones
([PG16 §5.8]), so this subtracts one verb and leaves SELECT — the clause that MUST admit
global rows — untouched.

**Verified after the fix, all PROVEN:**

| probe | before | after |
|---|---|---|
| tenant re-tenants a global row | UPDATE 1 | UPDATE 0 |
| tenant deletes the re-tenanted row | DELETE 1 | DELETE 0 |
| tenant SELECTs a global row (must still work) | 1 row | 1 row |
| tenant INSERT/UPDATE/DELETE on its OWN row | ok | ok |
| ops (untenanted) UPDATE + DELETE on a global row | ok | ok |

Test: `tests/dnc_global_scope_rls_test.py` — 7 tests, 2 red against the pre-fix tree, the
5 controls green (so the red is the subject, not the harness), all green after.

## 2. FIXED — `TenantMixin` claimed a foreign key it never created (PROVEN)

`apps/api/db/base.py`'s `TenantMixin` carried this comment inside its `mapped_column()`
call:

> "FK by name (not Column object) so mixin works across modules. ondelete RESTRICT:
> offboarding is an explicit workflow (FLOWS §9), never a cascade."

The call named no `ForeignKey` at all. 41 of the 43 tenant tables hand-write `tenant_id`
with the FK spelled out and were unaffected; the two that trusted the shared mixin —
`qa_reports`, `qa_call_samples` — had an ORM column with no relationship to
`organizations`.

PROVEN by `compare_metadata` against `d192_fresh` (migrated base → head): two `remove_fk`
ops, both on those tables. Since `alembic/env.py` sets `target_metadata = Base.metadata`,
the next `--autogenerate` proposed `DROP CONSTRAINT fk_qa_reports_tenant_id_organizations`
and its twin — in a diff a human is asked to skim. That drop would make orphaned tenant
rows representable and delete the RESTRICT that keeps offboarding a workflow.

The mirror error rode along: the mixin's `index=True` (plus one on
`lead_saved_views.user_id`) declared three indexes the database has never had, so
autogenerate also proposed CREATEing them — against an index budget DATA-MODEL §10 says is
decided by measurement, with `tests/prefix_index_audit_test.py` pinning four drops and
seven keepers.

**Why nothing caught it.** `scripts/check_metadata_columns.py` deliberately judges
`add_column`/`remove_column` only, and argues that scope well. `add_index` / `remove_fk`
are outside it, and nothing else looked.

**Fix.** `TenantMixin` now carries `ForeignKey("organizations.id", ondelete="RESTRICT")`
and no `index=True`; `lead_saved_views.user_id` loses its `index=True`. After the fix the
`add_index`, `add_fk` and `remove_fk` op classes are all empty.

## 3. FIXED — `organizations.plan_tier` had an enum in the model and none in the table (PROVEN)

`apps/api/tenancy/models.Organization` has declared
`CheckConstraint(f"plan_tier IN {PLAN_TIERS!r}", name="plan_tier_enum")` since D-39.
`f170dbce6f47`, the migration that ADDED the column, added it as a bare `sa.String()` with
a server default and **no constraint**. A `CheckConstraint` on a model is a DDL
instruction — SQLAlchemy never evaluates it client-side — so the rule existed nowhere that
could refuse a row.

PROVEN against `d192_fresh`:

```
INSERT INTO organizations (..., plan_tier, ...) VALUES (..., 'enterprise_platinum', ...);
-- INSERT 0 1
```

**Why it matters.** DATA-MODEL §2 calls `plan_tier` "which MOTION this org belongs to …
it decides whether credits gate dispatch (compliance gate) and whether the self-serve
screens render". `apps/api/admin/holds.py` selects R-11's first-campaign-review population
with `plan_tier = ANY(:tiers)`, so a tenant carrying an unrecognised tier falls silently
OUTSIDE the manual hold rather than visibly wrong — a compliance control failing towards
not applying.

**Why nothing caught it.** `compare_metadata` does not diff CHECK constraints in either
direction, so this class is invisible to every guard in the repo. It is the only instance:
a name-insensitive comparison of every ORM `CheckConstraint` against `pg_constraint` finds
this one and six cosmetic name drifts (`ck_platform_state_tm_status_enum` in the model vs
`ck_platform_state_tm_registration_enum` in the database, three constraints whose model
name already carried the prefix the naming convention adds again).

**No path writes a bad value today** — the admin route passes no tier, and
`tenancy/signup.py` uses a `Literal`. The parameter on `create_organization` is a plain
`str | None`, so the guarantee rested on both callers staying careful. That is the same
argument `e4f2a86b13d7` made about `remove_entry`, one finding earlier.

**Safe to apply, verified not assumed:** `SELECT plan_tier, count(*) FROM organizations
GROUP BY 1` on the development database returns only `managed` (27392), `self_serve`
(3988) and `trial` (27), so the constraint validates against real rows rather than being
declared `NOT VALID`.

**Fix.** Migration `e7b45c19a308` part 2. Guarded by
`tests/orm_schema_fidelity_test.py::test_every_orm_check_constraint_exists_in_the_database`,
red before the migration.

## 4. FIXED IN THE SAME MIGRATION — DDL with no `lock_timeout` is an outage waiting for one idle transaction (PROVEN, the expensive way)

This one was found by causing it. The first version of migration `e7b45c19a308` ran a bare
`ALTER TABLE organizations ADD CONSTRAINT …` against the shared development database. Two
sibling sessions were sitting `idle in transaction` holding `AccessShare` on
`organizations` from an ordinary `SELECT`. The `ALTER` queued for the `AccessExclusive` it
needs — and **every statement behind it queued too**, because PostgreSQL's lock queue is
FIFO and a waiting exclusive request blocks later shared ones. Observed live in
`pg_stat_activity`: eleven statements in `wait_event_type = 'Lock'`, including
`SELECT plan_tier FROM organizations WHERE id = $1` (the compliance gate's own read) and
an `INSERT INTO organizations`. The table was effectively down until the DDL was cancelled.

Lock levels then measured directly, from `pg_locks` inside an explicit transaction on
PostgreSQL 16.15:

| statement | lock |
|---|---|
| `ALTER TABLE … ADD CONSTRAINT … CHECK (…)` | `AccessExclusiveLock` |
| `ALTER TABLE … ADD CONSTRAINT … CHECK (…) NOT VALID` | `AccessExclusiveLock` |
| `ALTER TABLE … VALIDATE CONSTRAINT …` | `ShareUpdateExclusiveLock` |
| `CREATE POLICY` | `AccessExclusiveLock` |

**The hazard is acquisition, not the scan.** `organizations` is small; the scan is
microseconds. What hurt was waiting for the lock while holding the queue.

**Fix:** `SET LOCAL lock_timeout = '5s'` at the top of both `upgrade()` and `downgrade()`.
`transaction_per_migration=True` in `alembic/env.py` makes that boundary exactly this
revision.

**Proven to work, in the conditions it exists for.** The retry against the still-contended
shared database returned
`psycopg.errors.LockNotAvailable: canceling statement due to lock timeout` after 5s, left
`alembic_version` at `c7a1e93d40b8`, and blocked nobody. A failed migration an operator
retries, instead of an outage.

**Rejected: the `NOT VALID` / `VALIDATE` split.** It is the right answer on a large table
and buys nothing here — the window it shrinks is the scan, and inside one transaction the
lock taken by `NOT VALID` is held to COMMIT anyway, so the split only pays off across an
`autocommit_block()`. That would trade atomicity (a half-applied revision alembic never
stamps, whose retry then fails on "constraint already exists") for a scan this table does
not notice. Recorded in the migration so the next reader inherits the measurement rather
than re-deriving it.

**This is a repo-wide observation, not just this migration's:** no other migration in
`alembic/versions/` sets `lock_timeout`, and several take `AccessExclusive` on `calls`,
`leads` and `organizations`. Not fixed here — retrofitting 72 applied revisions changes
nothing about databases already migrated, and the value is in the NEXT one. The pattern
now exists in the tree with its measurement attached.

---

## CLEARED — things that were checked by execution and are correct

| claim | how | verdict |
|---|---|---|
| Every migration's `downgrade` actually runs | `alembic downgrade base` over the whole chain on `d192_scratch` | PROVEN clean, exit 0 |
| Downgrade leaves no residue | `pg_tables` / `pg_proc` / `pg_type` after `downgrade base` | PROVEN: only `alembic_version` survives; 0 functions, 0 enum types |
| Round-trip fidelity (base→head→base→head vs a pristine chain) | `pg_dump -s` of `d192_scratch` vs `d192_fresh`, **including ACLs and grants** | PROVEN byte-identical apart from pg_dump's own `\restrict` nonces |
| Empty → head, in order | fresh database, `alembic upgrade head` | PROVEN, exit 0, 62 tables |
| Column types and nullability agree ORM↔DB | `compare_metadata` with `compare_type=True`, `compare_server_default=True` | PROVEN: zero `modify_type`, zero `modify_nullable` |
| Append-only ledgers are triggered, and `ENABLE ALWAYS` | `pg_trigger.tgenabled` for all 8 `APPEND_ONLY_TABLES` | PROVEN: 8/8 carry both an `_append_only` and a `_forbid_truncate` trigger, every one `tgenabled = 'A'` (ALWAYS), so they survive a replica |
| RLS is ENABLEd **and** FORCEd on every tenant table | `pg_class.relrowsecurity` / `relforcerowsecurity` | PROVEN: t/t on all 43 |
| `tenant_id` FK to `organizations` exists in the DB on every tenant table | `pg_constraint` | PROVEN: 43/43, all `ON DELETE RESTRICT`; `engine_agent_routes` is the sole `tenant_id`-carrying table without one and is a declared exemption |
| `dnc_list_delete_scope` is RESTRICTIVE (else it would AND nothing) | `pg_policy.polpermissive` | PROVEN `f` — correct |
| No naive timestamps | `information_schema` for `timestamp without time zone` | PROVEN: 0 columns; `Base.type_annotation_map` maps `datetime` → `DateTime(timezone=True)` and no model bypasses it |
| IDs are uuid_v7 | every `id` column's Python default in `Base.metadata` | PROVEN: every UUID PK defaults to `db.base.uuid7`; the only `uuid4` in non-test code is a correlation-id hex and a script nonce, neither a row id |
| `make guardrails` | full run | PROVEN exit 0 |

## FOUND, NOT FIXED — with the reason

**33 foreign-key child columns have no index leading with that column** (PROVEN via
`pg_index.indkey[0]`). The ones that would matter are children of `calls`:
`usage_events.call_id` (RESTRICT), `consent_ledger.call_id` (RESTRICT),
`qa_call_samples.call_id` (CASCADE), `recording_erasure_holds.call_id`,
`kb_retrieval_logs.call_id`, `campaign_contacts.last_call_id`. A `RESTRICT` check with no
usable index is a sequential scan of the child per parent row deleted, and `usage_events`
is one of the tables named as unboundedly large.

**Not fixed because the parent is never hard-deleted.** PROVEN by grep across `apps/`: the
only `DELETE FROM` statements in the tree target `transcript_turns`, `kb_sources`,
`outbox_messages`, `webhook_inbox_events`, `platform_settings`, `memberships`,
`invitations`, `lead_saved_views`, `dnc_list`, `idempotency_records` and
`tenant_feature_flags`. `apps/workers/retention.py` says so explicitly at line 662 —
"Never a DELETE: leads carry FKs from `lead_events` and are referenced by `calls`". So the
scan is unreachable today, and adding six indexes would be six write costs bought against
a plan nothing executes — which is the opposite of the measured-decision rule DATA-MODEL
§10 sets for this schema. **What re-opens it:** the first code path that hard-deletes a
`calls` row. That path must ship the indexes with it, and this paragraph is the reason to
look.

## CLEARED BY READING ONLY (REASONED, stated as such)

- Every `tenant_isolation` policy's USING (and, where the table has one, WITH CHECK) reads
  the `app.tenant_id` GUC through the shared `NULLIF(...)` form. Dumped from `pg_policy`
  and read; the four asymmetric ones (`dnc_list`, `engine_agent_routes`,
  `inbound_webhooks`, `invitations`, `memberships`, `organizations`) each widen USING for a
  documented reason and each keep a narrower WITH CHECK. Only `dnc_list`'s widening was
  exploitable, and that is finding 1.
- The four `auth_*` tables' deny-by-default `app.auth` policy is FORCEd with identical
  USING and WITH CHECK — read from the catalog, not exercised.
- `RLS_EXEMPT_TENANT_COLUMNS`: every entry names a table this database has (the guard
  checks this and passes). No exemption's stated reason has expired that I could establish
  from the text.

[PG16 CREATE POLICY]: https://www.postgresql.org/docs/16/sql-createpolicy.html
[PG16 §5.8]: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
