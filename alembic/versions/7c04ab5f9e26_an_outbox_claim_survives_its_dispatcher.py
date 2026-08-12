"""an outbox claim survives its dispatcher

Revision ID: 7c04ab5f9e26
Revises: a6f2e84b1d37
Create Date: 2026-08-11 05:40:00.000000

`claim_outbox_batch` promises, in its own docstring, that "`attempt_count` bumps on
claim, so a message that keeps killing its worker still walks to the DLQ instead of
looping". It does not. The bump is written inside the dispatcher's transaction, and the
dispatcher does not commit until after it has published. A SIGKILL — an OOM kill, a
container eviction, a deploy that does not wait — rolls the bump back with everything
else, and the row returns to `pending` with `attempt_count = 0`. A message whose payload
is what kills the worker therefore loops forever: claimed, fatal, rolled back, claimed,
with a retry budget that resets on every pass and a DLQ it can never reach. The failure
is silent by construction, because the evidence dies with the process.

There is no way to fix that without a COMMIT: an uncommitted write is not durable, and
that is the entire content of the bug. But committing the bump ON ITS OWN is not a fix
either — the commit releases the `FOR UPDATE` locks that are the only thing making the
claim exclusive, and the row is `pending` again the instant they drop, so a second
dispatcher takes work the first is still doing. The claim has to commit AND the
exclusivity has to survive the commit, which means exclusivity must move out of the
lock and into a durable fact on the row. That fact is this column.

--------------------------------------------------------------------------------
The choice: `locked_until` (shipped) vs a `claimed` status (rejected)
--------------------------------------------------------------------------------

Both express "someone has this". The lease wins on four counts, and the fourth is the
one that decided it.

1. **It does not add a state anyone has to learn.** `status` keeps its three values, so
   every existing reader stays correct without being touched: the CAS guards in
   `mark_outbox_published` / `mark_outbox_failed` (`AND status = 'pending'`) still mean
   what they meant, `record_outbox_metrics` still counts an in-flight message toward
   outbox lag (it IS lag — it has not been published), the DLQ-depth query is unchanged,
   `replay_dead_letters` is unchanged, and the ops surface does not start rendering a
   fourth status. A `claimed` status changes the CHECK constraint and puts every one of
   those readers in the blast radius of this migration.

2. **Recovery needs no new machinery.** An abandoned `claimed` row is in a state no
   query returns, so something must sweep it back to `pending` — a reaper cron, with
   its own schedule, its own failure mode, and its own bug about how long is too long.
   A lapsed lease needs nobody: the claim query the dispatchers already run every ten
   seconds picks the row up again the moment `locked_until` passes. The recovery path
   IS the normal path, which is the only kind of recovery path that is still working
   the first time it is needed.

3. **It is the lease this module already runs on.** `CLAIM_LEASE` exists, and both the
   idempotency claim and the inbox claim already treat "a PROCESSING record older than
   the lease" as abandoned rather than in flight. `locked_until` is that same doctrine
   with the deadline stated instead of inferred. Stated is better here: those two infer
   it from `updated_at`, which every status transition also bumps, so it answers "when
   was this row last touched" and not "when was this row claimed". The outbox claim
   needs the second question, and a column that only the claim writes answers it.

4. **A mixed-version deploy degrades to the old behaviour instead of to a stall.** An
   old dispatcher still running against the new schema ignores the lease and can claim
   a leased row — a double publish, which `job_id_for(job, message.id)` already dedupes
   at the queue, and which is exactly what the system did before this migration. The
   same overlap with a `claimed` status is worse in kind: rows sitting in a state the
   old code's `WHERE status = 'pending'` never selects and its `mark_outbox_published`
   guard silently no-ops against. Choosing the failure mode you already survive over a
   new one is not conservatism, it is the only honest thing to do to a queue that
   carries a client's CRM notifications.

What the `claimed` status is genuinely better at is legibility: an operator reading the
table sees "in flight" without knowing to compare a timestamp to `now()`. That is real,
and it is bought back cheaply — `locked_until > now()` is the predicate, and it is one
column on one screen.

--------------------------------------------------------------------------------
Shape and cost
--------------------------------------------------------------------------------

Nullable, no default, no backfill: NULL means "never claimed, or the claim was
resolved", and every one of the 858 pending rows already on this database is exactly
that. In Postgres 11+ adding a nullable column with no default is a catalog-only
change — no table rewrite — so the ACCESS EXCLUSIVE lock is held for the length of a
catalog update, which is why this is safe to run against a database other suites are
using. CONCURRENTLY does not apply to ADD COLUMN and would not be an improvement here.

**No new index, deliberately.** The claim becomes

    WHERE status = 'pending' AND (locked_until IS NULL OR locked_until <= now())
    ORDER BY created_at, id

and `ix_outbox_pending (status, created_at)` already serves it perfectly: it walks
pending rows in `created_at` order and stops as soon as the batch is full, filtering the
handful of currently-leased rows as it goes. An index leading with `(status,
locked_until, ...)` would look more targeted and be worse — it cannot deliver the
`created_at` ordering for an OR predicate, so the planner would have to sort the whole
pending set to answer a LIMIT.

**Downgrade** drops the column. The claim reverts to being a bump inside the
dispatcher's transaction, i.e. back to the bug — which is the honest meaning of
reversing this change, and the reason the code in `apps/api/reliability/service.py`
reads the column rather than requiring it to exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c04ab5f9e26"
down_revision: str | None = "a6f2e84b1d37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox_messages",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox_messages", "locked_until")
