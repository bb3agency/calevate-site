"""the balance read walks its index

Revision ID: a6f2e84b1d37
Revises: d3b71c9a5e08
Create Date: 2026-08-11 05:25:00.000000

Two things were asked of this migration. It ships one of them and refuses the other,
and the refusal is the more important half — so it is written down here rather than
left as an absence somebody re-derives in six months.

--------------------------------------------------------------------------------
SHIPPED: ix_credit_ledger_tenant_recent (tenant_id, occurred_at DESC, id DESC)
--------------------------------------------------------------------------------

The wallet balance is not an aggregate — that is the whole reason `balance_after` is
denormalized (see the model docstring). Every read of it is:

    SELECT balance_after FROM credit_ledger
     WHERE tenant_id = :tid ORDER BY occurred_at DESC, id DESC LIMIT 1

and it runs on the pre-dispatch path: `get_balance` -> `record_entry` -> every top-up,
every per-call charge, and the credits panel. Until now the only index was a
single-column `ix_credit_ledger_tenant_id`, which finds the tenant's rows and then
SORTS all of them to answer LIMIT 1. That is a full sort of one tenant's entire ledger
history to read one number, and it gets slower every month a client stays with us —
the classic index that looks present and is not.

The new index carries the ORDER BY, so the plan becomes a backwards walk that stops at
the first row. The `id DESC` tail matters as much as the timestamp: `record_entry`
stamps `occurred_at` with `clock_timestamp()` under a per-tenant advisory lock, so ties
are rare but not impossible, and "newest" has to be a total order or `get_balance` and
`_find_topup` can disagree about which row is the newest.

`apps/api/billing/credit_routes.py` already names this index in a comment ("the
predicate is what makes it an index scan on ix_credit_ledger_tenant_recent"). It did
not exist. The name here is chosen to match, so that the comment stops being fiction.

`ix_credit_ledger_tenant_id` is now a prefix of this index and therefore redundant.
It is deliberately NOT dropped in the same release that stops needing it (hard rule 8,
two-step deprecation): the new index has to be observed carrying production plans
before the old one is removed, and an index is exactly the kind of thing whose absence
is discovered under load.

--------------------------------------------------------------------------------
REFUSED: a partial unique index on (tenant_id, ref) WHERE reason IN ('topup','usage')
--------------------------------------------------------------------------------

The intent is right. Both credit dedupes are check-then-write under
`pg_advisory_xact_lock(hashtextextended('credit:<tenant_id>'))`:

- `record_topup` looks up the payment reference (`reason = 'topup'`), and
- `charge_for_call` looks up the call id (`reason = 'usage'`).

A lock makes double-crediting unlikely. A unique index would make it impossible — and
the difference matters here because the thing being protected is money: an advisory
lock is only as good as every future writer remembering to take it, and the reasons are
already right for the predicate. `adjustment` and `refund` are correctly excluded: two
partial refunds against one call legitimately share a `ref`. `ref IS NULL` belongs in
the predicate too — 4221 of 5957 rows on this database carry no ref (a NULL never
conflicts in a unique index anyway; stating it keeps the index small and the intent
legible).

**It cannot be created. This database already violates it.** 21 (tenant_id, ref) pairs
carry two entries each within one reason — 19 `topup` and 2 `usage`:

    SELECT tenant_id, ref, reason, count(*)
      FROM credit_ledger
     WHERE reason IN ('topup','usage') AND ref IS NOT NULL
     GROUP BY 1,2,3 HAVING count(*) > 1;

Those rows are the bug's own fossil record: one payment reference credited twice, one
call charged twice. `CREATE UNIQUE INDEX` would abort the migration on them.

And they cannot be cleaned the way `call_extractions` duplicates were cleaned two
revisions ago. `credit_ledger` is an APPEND-ONLY ledger (hard rule 4): it is in
`APPEND_ONLY_TABLES`, and the `credit_ledger_append_only` trigger refuses every UPDATE
and DELETE at the database. A migration that dropped the trigger to delete money rows
would be doing precisely what the rule exists to forbid, and it would be destroying the
evidence of a real double-credit rather than correcting it. The correction for a wrong
entry is a compensating `adjustment` entry — a business decision, made by a person
looking at a bank statement, not by a schema migration at deploy time.

Forcing it anyway was considered and rejected in every form:

- a migration that skips the index when it finds violations would leave the constraint
  present in some environments and absent in others, so nobody could ever again reason
  about whether double-crediting is possible — worse than not having it;
- a predicate grandfathering the existing rows (`AND occurred_at > '<cutoff>'`) makes
  the constraint's meaning depend on a date literal frozen in a migration file, and
  hides the 21 unreconciled pairs behind a clean-looking index.

So the index is not in this migration, and the path to it is not schema work:

1. ops reconciles the 21 pairs with compensating entries (hard rule 4), which is also
   the only step that returns the affected wallets to a defensible balance;
2. the detection query above returns zero rows;
3. a follow-up migration adds
   `CREATE UNIQUE INDEX ... ON credit_ledger (tenant_id, ref)
    WHERE reason IN ('topup','usage') AND ref IS NOT NULL`
   and the advisory lock demotes from load-bearing to belt-and-braces.

--------------------------------------------------------------------------------

**Locking.** Plain `CREATE INDEX`, not CONCURRENTLY. `credit_ledger` holds 5957 rows
here and none in production; the build is milliseconds and the SHARE lock it takes
blocks writers for that long only. CONCURRENTLY would buy nothing and cost the
migration its transaction — a failed concurrent build leaves an INVALID index behind
and a revision that is half applied. If this ever has to run against a ledger with
millions of rows, that trade flips, and the note is here so the reviewer of that day
sees the reasoning rather than the conclusion.

**Downgrade** drops the index. Nothing depends on it for correctness — it is a plan
shape, not a constraint — so the ledger keeps working, more slowly, exactly as it did
before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6f2e84b1d37"
down_revision: str | None = "d3b71c9a5e08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_credit_ledger_tenant_recent"


def upgrade() -> None:
    op.create_index(
        INDEX,
        "credit_ledger",
        ["tenant_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="credit_ledger")
