"""the prefix index the composite replaced

Revision ID: e7c3d10a9f52
Revises: c2f7a91b4e63
Create Date: 2026-08-12 07:10:00.000000

Step two of the two-step deprecation `a6f2e84b1d37` opened (hard rule 8). That
migration created `ix_credit_ledger_tenant_recent (tenant_id, occurred_at DESC,
id DESC)` and deliberately KEPT `ix_credit_ledger_tenant_id`, because "the new index
has to be observed carrying production plans before the old one is removed". This is
the release that has the observation, so this is the release that removes it.

WHY IT IS REDUNDANT
-------------------
`ix_credit_ledger_tenant_id` is a STRICT PREFIX of the composite. A btree on
`(tenant_id, occurred_at DESC, id DESC)` answers every predicate a btree on
`(tenant_id)` answers, by the leading-column rule — which is also why the two plans
kept costing 0.01 apart and why the balance-read assertion in
`tests/schema_hardening_test.py` flapped for a week before `c0ce977` established that
the test, not the index, was the defect.

THE OBSERVATION, on a loaded database (`calevate_bal_big`, 18,437 entries, ANALYZEd),
every query in the repo that touches `credit_ledger`, EXPLAIN ANALYZEd before and
after the drop:

| query                          | before               | after                    |
|--------------------------------|----------------------|--------------------------|
| `_newest_balance`              | Index Scan, COMPOSITE| Index Scan, composite    |
| credits panel                  | Bitmap, prefix       | Bitmap, composite        |
| `_find_topup`                  | Bitmap, prefix       | Bitmap, composite        |
| `charge_for_call` dedupe       | Bitmap, prefix       | Bitmap, composite        |
| reconciler duplicate groups    | Bitmap, prefix       | Bitmap, composite        |
| reconciler compensation lookup | Bitmap, prefix       | Bitmap, composite        |
| reconciler `_ref_exists`       | Bitmap, prefix       | Bitmap, composite        |
| FK enforcement check           | Bitmap + LockRows,   | Bitmap + LockRows,       |
|   (RI query, row_security off) |   prefix             |   composite              |

No node type changed and nothing fell back to a sequential scan; every plan simply
names the composite where it named the prefix. The hot path — the balance read on the
pre-dispatch route — was already on the composite and is untouched.

WHAT IT COSTS, stated rather than glossed: the composite's leaf pages are wider, so
the bitmap-index scans read 2 more shared buffers per execution (4 -> 6 on the tenant
measured) and their startup cost estimate rises from 4.54 to 20.65. That is the price
of one index instead of two on a read that was already touching the heap.

WHAT IT BUYS: `credit_ledger` is APPEND-ONLY (hard rule 4), so every row ever written
pays the insert cost of every index on the table, forever, and none of them ever pays
it back on an UPDATE that never happens. 200k appends measured ~7% faster without this
index. It is also 1.5 MB of pages and one more thing for `VACUUM` to walk.

BOTH HALVES ARE HERE ON PURPOSE. Dropping the index without removing `index=True`
from `CreditLedgerEntry.tenant_id` would leave the model asking for it, and the next
`alembic revision --autogenerate` would helpfully create it again — a deprecation that
un-deprecates itself at the next migration. The column stays indexed in fact, by the
composite declared in `__table_args__`; it stops being indexed TWICE.

LOCKING. Plain `DROP INDEX`, not CONCURRENTLY, and the reasoning is the mirror of the
one `a6f2e84b1d37` gave for its `CREATE`. A drop takes ACCESS EXCLUSIVE on the table
for the duration, which for an index drop is a catalog update and a file unlink — it
does not read the index, so the lock is held for milliseconds regardless of how many
rows the table has (unlike the build, whose cost scales). The exposure is therefore
the WAIT for the lock, not the work under it: a long-running transaction touching
`credit_ledger` will queue this migration behind it, and everything else behind that.
At M1 volumes there is no such transaction. DROP INDEX CONCURRENTLY would avoid even
that queue, but it cannot run inside a transaction block, so it would cost the
migration its atomicity — and a half-applied revision to dodge a millisecond lock on a
plan shape is the wrong trade. If this ever has to run against a ledger under
continuous load, add a `lock_timeout` and retry rather than reaching for CONCURRENTLY.

DOWNGRADE recreates it. Nothing depends on it for correctness — it is a plan shape,
not a constraint — so a downgraded database is slower on writes and identical on
reads, which is exactly where `a6f2e84b1d37` left things.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7c3d10a9f52"
down_revision: str | None = "c2f7a91b4e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_credit_ledger_tenant_id"


def upgrade() -> None:
    op.drop_index(INDEX, table_name="credit_ledger")


def downgrade() -> None:
    op.create_index(INDEX, "credit_ledger", ["tenant_id"])
