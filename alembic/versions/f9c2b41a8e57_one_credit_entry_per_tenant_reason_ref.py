"""one credit entry per (tenant, reason, ref)

Revision ID: f9c2b41a8e57
Revises: c1f3a7d92b46
Create Date: 2026-08-11 08:07:00.000000

The fifth attempt at a unique index on `credit_ledger`, and the one that lands. The
statement and its clause-by-clause defence are settled in
`scripts/reconcile_credit_ledger.py` (section THE INDEX); this file executes the three
preconditions that section names and freezes the result.

    CREATE UNIQUE INDEX CONCURRENTLY ux_credit_ledger_tenant_reason_ref
        ON credit_ledger (tenant_id, reason, ref)
     WHERE ref IS NOT NULL
       AND reason IN ('topup', 'usage', 'adjustment')
       AND occurred_at >= '2026-08-11 08:07:00+00:00'::timestamptz;

--------------------------------------------------------------------------------
WHY `reason` IS IN THE KEY — the finding four refusals missed
--------------------------------------------------------------------------------

Revisions a6f2e84b1d37 and its three successors all proposed `UNIQUE (tenant_id, ref)`
and all argued about the PREDICATE. The key was the wrong shape. `credit_ledger.ref` is
two namespaces sharing one column: a `usage` row carries a call id, a `topup` row carries
whatever the bank printed, and `TopUpIn.payment_ref` accepts any string of 3 to 120
characters — a 36-character UUID among them. The system does not prevent that collision,
it TOLERATES it, in three places deliberately: `find_topup` scopes its lookup to
`reason = 'topup'`, `charge_for_call` scopes its dedupe to `reason = 'usage'`, and the
reconciler's detector groups by `(ref, reason)`. `UNIQUE (tenant_id, ref)` would convert
that tolerated collision into an IntegrityError on the top-up route — a 500 on a valid
payment, which is strictly worse than the duplicates it would catch.
`tests/credit_ledger_uniqueness_test.py::test_a_call_id_and_a_payment_reference_may_
collide` pins the tolerance so the key cannot quietly regress to `(tenant_id, ref)`.

--------------------------------------------------------------------------------
WHY THIS CUTOFF, AND WHY THIS EXACT INSTANT
--------------------------------------------------------------------------------

`occurred_at >= '2026-08-11 08:07:00+00:00'` is a grandfather line, not a tuning knob.
Hard rule 4 forbids deleting the pre-fix residue and the reconciler does not delete it
either — it appends one compensating entry per duplicated group and the duplicate rows
REMAIN. The residue is therefore permanent, and a partial index is the only shape that
can ever build. Verified: the same index without the cutoff fails on
`(…, topup, UTR-RACE-0)`.

The instant is **the moment this migration was authored, truncated down to the minute**,
and both halves of that sentence are load-bearing:

- **Authoring instant, not a placeholder.** A cutoff is only honest if it sits after
  every duplicate on the target database and at or before deploy. Production has never
  run a test and holds no duplicate under this key at any cutoff, so the binding
  constraint is the second one: pick the latest instant that is still certainly in the
  past when this ships. That is now.
- **Truncated DOWN, never up.** Rounding forward would open a window in which a
  duplicate is legal and invisible — the index would say "impossible" about minutes it
  does not cover. Rounding back can only widen coverage, and the only rows in the extra
  seconds are rows this migration has already been measured against.
- **UTC, with an offset in the literal.** A naive literal is read in the server's
  TimeZone, which is how a cutoff silently moves by five and a half hours on a machine
  set to IST. `tests/credit_ledger_uniqueness_test.py::test_the_cutoff_and_the_residue_
  cannot_cross` asserts the tzinfo for the same reason.

The same instant is written into `scripts.reconcile_credit_ledger.LEDGER_UNIQUE_INDEX_
CUTOFF`. It is duplicated rather than imported: a migration is a frozen historical fact
and must not change meaning because a constant three directories away was edited later.
`tests/credit_ledger_unique_index_test.py::test_the_migration_and_the_reconciler_name_
the_same_cutoff` is what keeps the two copies honest.

Measured against the shared dev database immediately before authoring (owner role,
bypassing RLS), under this exact key and predicate:

    total violating groups, no cutoff clause ......... 637  (571 topup, 61 usage,
                                                             5 adjustment)
    violating groups at or after this cutoff .........   2

Both survivors are the pair `(topup, UTR-DRIFT-1)` and one `(usage, <call uuid>)`,
stamped **2027-08-27** by an earlier form of `test_the_residue_seed_cannot_drift_past_
the_cutoff` that wrote its future-dated fixture for real; the test has since been
rewritten to assert against INSERT parameters instead. Hard rule 4 makes those rows
permanent, so **this index does not build on that database, and that is the correct
outcome.** A cutoff moved into 2028 to dodge dev residue is a cutoff that protects
nothing. Verification for this revision was done on a scratch database (upgrade,
downgrade, upgrade), and CI builds from `base` on a fresh one every run.

--------------------------------------------------------------------------------
THE PREDICATE, clause by clause
--------------------------------------------------------------------------------

- `ref IS NOT NULL` — a null ref is "no idempotency key", not a key that collides. It
  also keeps the index small: most of this table carries no ref.
- `reason IN ('topup', 'usage', 'adjustment')` — the three reasons that have an
  idempotency contract TODAY. `topup` dedupes on the payment reference, `usage` on the
  call id, `adjustment` on the reconciler's content-addressed `dedupe:…` ref. `refund`
  is excluded on purpose: it has no writer in `apps/` at all, every refund row carries a
  NULL ref, and the obvious future shape — several partial refunds against one payment
  reference — is legitimate and would fire the index. Excluding it costs nothing today
  (`ref IS NOT NULL` already excludes every one of them) and avoids designing a
  constraint against a feature nobody has written yet.

--------------------------------------------------------------------------------
LOCKING: CONCURRENTLY, outside the migration's transaction
--------------------------------------------------------------------------------

`credit_ledger` is written continuously by the post-call pipeline. A plain
`CREATE UNIQUE INDEX` takes a SHARE lock on the table and blocks EVERY credit write for
the length of the build — every top-up, every per-call charge — so on this table the
trade a6f2e84b1d37 made for a plan-shape index (a millisecond SHARE lock on 5957 rows)
flips: a constraint on the money path is worth building the slow way.

Alembic runs each migration inside a transaction and `CREATE INDEX CONCURRENTLY` cannot
run in one, hence `op.get_context().autocommit_block()`. Two consequences a reviewer
should have in front of them:

1. **A failed CONCURRENTLY build leaves an INVALID index behind**, and an invalid UNIQUE
   index is not inert — depending on which phase failed it can still reject new
   insertions while being useless for queries. It is not rolled back by the transaction
   this statement is deliberately outside of, and `alembic_version` is NOT advanced, so
   a plain re-run would then fail with "relation already exists". Recovery is one
   statement, the same one `downgrade()` issues:

       DROP INDEX IF EXISTS ux_credit_ledger_tenant_reason_ref;

   then re-run `alembic upgrade head`. That is why the downgrade drops UNCONDITIONALLY
   and with `IF EXISTS` — it has to be able to clean up an index this revision never
   finished creating, on a database that does not believe this revision ran.
2. **`lock_timeout` still applies** (hard rule 8) and is set inside the autocommit block
   with plain `SET`, not `SET LOCAL`: there is no transaction for `LOCAL` to be local to,
   so `SET LOCAL` would be a no-op and the statement would wait forever. 30s, not the 3s
   e2c47b90d5a1 uses, because CONCURRENTLY waits on concurrent transactions as well as on
   the table lock; a 3s ceiling would abort healthy builds on a busy database and leave
   exactly the invalid index described above. What it buys is a bounded failure instead
   of a migration parked behind someone else's DDL.

**RLS.** No new table, so no new policy: `credit_ledger` already carries the FORCEd
`tenant_isolation` policy from 05bba2f3c19c and the index inherits the table's
protection. Index builds are not RLS-filtered — RLS constrains queries, not the storage
layer — so this revision issues no DML and needs no `NO FORCE` bracket. Note what the
key ordering buys under RLS: leading with `tenant_id` keeps a unique violation reachable
only against a row of your own, and a unique violation is one of the few channels
through which a row your policy hides can announce that it exists.

**Downgrade** drops the index. Nothing depends on it for correctness: every writer that
could produce a duplicate key is already serialized by `lock_tenant_credits`, and
`tests/credit_ledger_uniqueness_test.py` pins that. This index is a backstop against a
future writer that forgets the lock — worth having, and not worth breaking a money route
for. The pre-migration code therefore runs correctly against the post-downgrade schema,
which is the sense hard rule 8 means by reversible.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f9c2b41a8e57"
down_revision: str | None = "c1f3a7d92b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ux_credit_ledger_tenant_reason_ref"

# The grandfather line. Frozen here as a literal (see WHY THIS CUTOFF above) and
# duplicated in `scripts.reconcile_credit_ledger.LEDGER_UNIQUE_INDEX_CUTOFF`, which
# `tests/credit_ledger_unique_index_test.py` holds equal to it.
CUTOFF = "2026-08-11 08:07:00+00:00"

CREATE = (
    f"CREATE UNIQUE INDEX CONCURRENTLY {INDEX} ON credit_ledger (tenant_id, reason, ref) "
    "WHERE ref IS NOT NULL "
    "AND reason IN ('topup', 'usage', 'adjustment') "
    f"AND occurred_at >= '{CUTOFF}'::timestamptz"
)

DROP = f"DROP INDEX IF EXISTS {INDEX}"


def upgrade() -> None:
    # Outside the migration's transaction: CONCURRENTLY cannot run inside one, and the
    # alternative — a SHARE lock held for the whole build — blocks every credit write.
    with op.get_context().autocommit_block():
        # Plain SET, not SET LOCAL: there is no transaction here for LOCAL to scope to.
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE)


def downgrade() -> None:
    # UNCONDITIONAL and IF EXISTS. This has to succeed both when the index built
    # cleanly and when a CONCURRENTLY build failed and left an INVALID index behind —
    # including on a database whose alembic_version never advanced past this revision.
    # A plain DROP takes ACCESS EXCLUSIVE for the catalog update only, so it is bounded
    # by the lock_timeout rather than by a build.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(DROP)
