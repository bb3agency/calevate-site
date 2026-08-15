"""one metering row per (tenant, call, unit_type)

Revision ID: b8d3f47c2a19
Revises: 9c1d3e7a05f4
Create Date: 2026-08-15 10:14:00.000000

The last line of defence for the money ledger, and the one `usage_events` did not have
while both of its sibling ledgers did (`ux_credit_ledger_tenant_reason_ref`,
`ux_one_time_charges_tenant_kind_ref`).

    CREATE UNIQUE INDEX CONCURRENTLY ux_usage_events_tenant_call_unit
        ON usage_events (tenant_id, call_id, unit_type)
     WHERE call_id IS NOT NULL
       AND unit_type IN ('telephony_s','platform_min','stt_s','tts_chars','llm_tok_out')
       AND created_at >= '2026-08-15 10:14:00+00:00'::timestamptz;

--------------------------------------------------------------------------------
WHY AN INDEX WHEN D-110 ALREADY TOOK A LOCK
--------------------------------------------------------------------------------

`pipeline._meter` reads "have we metered this call" and then writes, inside
`lock_call_writes` (a `pg_advisory_xact_lock` on the call id). That closes the window and
it is the right first line. It is not the last one, because **an advisory lock is a
convention and a unique index is a fact**: the lock protects the call sites that remember
to take it, and nothing in the database refuses a writer that forgets. D-110's own
negative control measures exactly what forgetting costs — two overlapping `_meter` runs
produced **10 usage rows for a five-row call and 1.5833 minutes counted into
`spend_state` as 3.1666** — and `usage_events` is append-only (hard rule 4), so neither
number can be taken back. The remedy for a double charge is a compensating entry somebody
writes by hand, if anybody notices.

--------------------------------------------------------------------------------
WHAT THIS CHANGES ABOUT A RETRY, which is the question an append-only table forces
--------------------------------------------------------------------------------

On a table where the fix for a bad row is another row, turning a duplicate into an ERROR
has to be shown to leave the system better, not merely stricter. It does, and the walk is
short:

* **The guarded path is unaffected.** Under `lock_call_writes` the second run reads the
  first run's rows and returns 0 before inserting anything. The index is never reached.
* **The unguarded path aborts instead of double-charging.** Postgres blocks the second
  inserter on the conflicting key until the first transaction resolves, then raises
  `unique_violation`. `_meter` writes all five rows, `charge_for_call` and the
  `spend_state` upsert inside ONE transaction, so the abort rolls back the entire second
  metering — no partial row set, no half-moved counter.
* **And the retry then succeeds by doing nothing.** The abort propagates to ARQ, which
  re-runs the job; the re-run's "have we metered this call" read now sees the first run's
  rows and returns 0. So the failure mode changes from *a permanent double charge nobody
  can undo* to *one failed job attempt and a self-healing retry*. That is the whole
  trade, and it is the right way round on a ledger.
* **`ON CONFLICT` is deliberately NOT used at the insert site.** `DO UPDATE` is
  unavailable here on principle and in fact — it would fire `calevate_forbid_mutation`,
  the append-only trigger — and `DO NOTHING` would convert the conflict into silence,
  which is worse than an abort: it would let a run that believed it was metering a call
  report success having written a partial, interleaved row set. A future writer that does
  want `DO NOTHING` must repeat this index's WHERE clause verbatim as an `index_predicate`
  or Postgres will not infer a partial index at all
  (postgresql.org/docs/16/sql-insert.html, "unique index inference" — READ AT SOURCE).

--------------------------------------------------------------------------------
THE KEY, clause by clause
--------------------------------------------------------------------------------

- `(tenant_id, call_id, unit_type)` — tenant first for the reason
  `ux_credit_ledger_tenant_reason_ref` gives: it keeps a unique violation reachable only
  against a row of your own, and a unique violation is one of the few channels through
  which a row RLS hides can announce that it exists.

- `call_id IS NOT NULL` — most of this column is not null, but the rows that are matter.
  `number_rental` and the restore drill's probe rows carry no call, and NULLs do not
  collide in a btree anyway; naming it makes the index smaller and the intent legible.

- **`unit_type IN (the five the metering path writes)` — the clause four readings of
  this key would have missed.** `billing.service.record_tier_correction` is the
  hard-rule-4 compensating entry for a call metered on the wrong TTS rung, and it appends
  `unit_type = 'other'` against the SAME `(tenant_id, call_id)`. Two ops references
  correcting one call legitimately produce two such rows, so a key without this clause
  would convert the one mechanism the ledger has for FIXING a mistake into an
  IntegrityError on the correction route. Enumerated positively rather than as
  `unit_type <> 'other'` for the same reason `credit_ledger` enumerates its reasons: a
  unit type added tomorrow should have to be thought about rather than silently
  constrained. `tests/usage_events_unique_index_test.py::
  test_the_index_covers_exactly_the_unit_types_the_metering_path_writes` reads the five
  back out of `pipeline._meter`'s own source and fails if the two ever disagree.

- **`created_at >= '2026-08-15 10:14:00+00:00'` — the grandfather line.** Hard rule 4
  forbids deleting the pre-fix residue, so any duplicate already on a database is
  PERMANENT and a partial index is the only shape that can ever build there. Production
  holds none (this key has never been violated under `lock_call_writes`), but a shared
  dev database does: `tests/postcall_concurrency_test.py`'s negative control stubs the
  lock to a no-op and double-meters a call ON PURPOSE, and every run of it before this
  revision left a violating pair behind that nothing can remove. An index that cannot be
  created is not a constraint.

  **`created_at`, not `occurred_at`, and that is a deliberate departure from
  `ux_credit_ledger_tenant_reason_ref`'s `occurred_at` cutoff.** The line means "written
  after this migration", and only `created_at` means that: `_meter` stamps
  `occurred_at` from `snapshot.ended_at`, so the reconciliation poller repairing a call
  that ended yesterday writes a row whose `occurred_at` predates the cutoff and whose
  `created_at` does not. Under an `occurred_at` line every poller repair would land
  OUTSIDE the index — precisely the path with the weakest lock discipline. `created_at`
  is also monotone on this table (`now()` at insert, never backdated, never updated),
  which an `occurred_at` line cannot claim.

  The instant is the authoring instant truncated DOWN to the minute, for
  `ux_credit_ledger_tenant_reason_ref`'s reasons: rounding forward would open a window in
  which a duplicate is legal and invisible, rounding back can only widen coverage, and
  the offset is in the literal because a naive one is read in the server's TimeZone and
  moves by five and a half hours on a machine set to IST.

  What the cutoff costs: rows written between authoring and deploy must themselves be
  unique or the build fails. Those are written by `_meter` under `lock_call_writes`,
  so they are unique by construction — and a failure there would be a REAL finding worth
  stopping a deploy for, not residue.

Measured on a scratch database built from `base` and then run against the affected
suites: 0 violating groups at any cutoff before the negative control ran, 1 after it,
and 0 at or after this cutoff once the control was rewritten to expect the constraint.

--------------------------------------------------------------------------------
LOCKING: CONCURRENTLY, outside the migration's transaction
--------------------------------------------------------------------------------

`usage_events` is written by the post-call pipeline on every completed call. A plain
`CREATE UNIQUE INDEX` takes a SHARE lock for the length of the build and blocks every
metering write; on the money path that trade goes the same way `f9c2b41a8e57` decided it
for `credit_ledger`. Alembic runs a migration inside a transaction and CONCURRENTLY
cannot, hence `autocommit_block()`. Two consequences a reviewer should have in front of
them, both identical to that revision's and repeated because the recovery is the thing
somebody needs at 3am:

1. **A failed CONCURRENTLY build leaves an INVALID index behind**, and an invalid UNIQUE
   index is not inert — it can still reject insertions while being useless for queries.
   It is not rolled back, and `alembic_version` is not advanced, so a plain re-run fails
   with "relation already exists". Recovery is the statement `downgrade()` issues:

       DROP INDEX IF EXISTS ux_usage_events_tenant_call_unit;

   then re-run `alembic upgrade head`. That is why the downgrade drops UNCONDITIONALLY
   and with `IF EXISTS`.
2. **`lock_timeout` applies** (hard rule 8), set with plain `SET` rather than `SET LOCAL`
   because there is no transaction for LOCAL to scope to. 30s, not 3s: CONCURRENTLY waits
   on concurrent transactions as well as on the table lock, and a 3s ceiling would abort
   healthy builds and leave exactly the invalid index above.

**RLS.** No new table, so no new policy: `usage_events` already carries the FORCEd
`tenant_isolation` policy and the index inherits the table's protection. Index builds are
not RLS-filtered — RLS constrains queries, not storage — so this revision issues no DML
and needs no `NO FORCE` bracket. `tests/usage_events_unique_index_test.py` carries the
cross-tenant zero-rows check that hard rule 1 requires of any change touching a
tenant-scoped table, and the specific thing it proves is that the new index does not
become a side channel: two tenants may hold the same `(call_id, unit_type)` without
colliding, because `tenant_id` leads the key.

**Downgrade** drops the index. The pre-migration code runs correctly against the
post-downgrade schema — `lock_call_writes` is unchanged and remains the first line — which
is the sense hard rule 8 means by reversible. The append-only TRIGGER is not touched by
either direction, so there is no function for the downgrade to orphan.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d3f47c2a19"
down_revision: str | None = "9c1d3e7a05f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ux_usage_events_tenant_call_unit"

# The five unit types `pipeline._meter` writes, one per call. Frozen here as
# literals — a migration is a historical fact and must not change meaning because a
# constant elsewhere was edited later — and held equal to the metering path's own source
# by `tests/usage_events_unique_index_test.py`.
METERED_UNIT_TYPES = ("telephony_s", "platform_min", "stt_s", "tts_chars", "llm_tok_out")

# The grandfather line: the authoring instant, truncated down to the minute, in UTC with
# the offset spelled in the literal. See WHY `created_at` above.
CUTOFF = "2026-08-15 10:14:00+00:00"

_UNIT_LIST = ", ".join(f"'{unit}'" for unit in METERED_UNIT_TYPES)

CREATE = (
    f"CREATE UNIQUE INDEX CONCURRENTLY {INDEX} "
    "ON usage_events (tenant_id, call_id, unit_type) "
    "WHERE call_id IS NOT NULL "
    f"AND unit_type IN ({_UNIT_LIST}) "
    f"AND created_at >= '{CUTOFF}'::timestamptz"
)

DROP = f"DROP INDEX IF EXISTS {INDEX}"


def upgrade() -> None:
    # Outside the migration's transaction: CONCURRENTLY cannot run inside one, and the
    # alternative — a SHARE lock held for the whole build — blocks every metering write.
    with op.get_context().autocommit_block():
        # Plain SET, not SET LOCAL: there is no transaction here for LOCAL to scope to.
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE)


def downgrade() -> None:
    # UNCONDITIONAL and IF EXISTS, so this also cleans up an INVALID index left by a
    # CONCURRENTLY build that failed on a database whose alembic_version never advanced.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(DROP)
