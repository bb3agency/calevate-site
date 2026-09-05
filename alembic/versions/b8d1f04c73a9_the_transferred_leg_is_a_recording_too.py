"""the transferred leg is a recording too, and the same erasure has to reach it

Revision ID: b8d1f04c73a9
Revises: e6c1a49d2f70
Create Date: 2026-09-05 00:00:00.000000

D-533, second half. A call that was handed to a person produces TWO recordings: the part
the AI handled, and the transferred leg, which the voice platform records as an object of
its own and serves from its own route. Until now we copied the first and knew only that the
second existed — so a caller's voice sat on a third party's disk that no erasure of ours
could reach, and a deletion certificate said "the recording was destroyed" while it did not.
The founder's decision (5 Sep 2026) is that the transferred leg is treated exactly like our
own recordings: fetched, on the same retention clock, reachable by the same erasure.

**ONE COLUMN, NOT A SECOND MACHINE, AND THAT IS THE WHOLE POINT OF THE SHAPE.**
`calls.transfer_recording_url` is the exact twin of `calls.recording_url` — OUR object key
and never a vendor URL, written by the pipeline's copy stage, cleared by the retention sweep
and by every erasure path. Nothing new is built around it: `retention._sweep_objects`,
`_erase_recordings`, `recording_erasure_holds` and the two erasure pointer-clears all learn
that a call may have TWO keys, which is a widening of statements that already exist rather
than a parallel set of them. The holds table needed no change at all — it was already unique
on `(tenant_id, object_key)`, so two objects for one call are two holds and always were.

WHY NOT A KEYS ARRAY, OR A ROW PER RECORDING. Both were considered and both are bigger than
the problem. A call has exactly two possible recordings and the second exists only when a
handover happened; an array would put the ordering of two things nobody iterates into a
JSONB, and a `call_recordings` table would fork every one of the statements above into a
join for a cardinality of two. The column is the smaller change AND the one that keeps the
erasure statements readable, which is where being wrong is most expensive.

NULLABLE, with no default and no backfill. A call that never handed over has no second
recording and NULL is the honest value; a call that DID hand over before this migration has
one at the vendor that nothing here ever fetched, and inventing a key for it would make the
retention sweep try to delete an object that does not exist. Those calls are named by
`handoff_attempts.leg_recording_present` and are a data question for a human, not something
a migration can fix.

Not a tenant table of its own — `calls` already carries `tenant_id` and the FORCEd policy,
so this column inherits it. No RLS change, no new policy, no new test table.

REVERSIBLE, and the downgrade DESTROYS NOTHING: it drops the column, which orphans whatever
objects it named in the bucket. That is stated rather than hidden — the `recordings/` prefix
lifecycle rule is the only thing that would ever reach them afterwards, on its own clock,
which is exactly the failure D-148 and the retention sweep's own comment describe. A
downgrade here is therefore an operator decision with a consequence, and the runbook for it
is: sweep the transfer objects first, then downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d1f04c73a9"
down_revision: str | Sequence[str] | None = "e6c1a49d2f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("transfer_recording_url", sa.Text(), nullable=True))
    # THE SWEEP'S PREDICATE, and the reason it is partial. Both recording sweeps ask "which
    # calls still hold audio", and the second column is NULL on every call that was never
    # handed over — which is almost all of them. A full index would be mostly nulls and the
    # planner would ignore it; the partial one is small enough to stay in cache and matches
    # the `IS NOT NULL` the erasure and the retention arm both write.
    op.create_index(
        "ix_calls_transfer_recording",
        "calls",
        ["tenant_id"],
        postgresql_where=sa.text("transfer_recording_url IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_calls_transfer_recording", table_name="calls")
    op.drop_column("calls", "transfer_recording_url")
