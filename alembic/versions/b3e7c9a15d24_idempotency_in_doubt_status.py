"""an idempotency key whose side effect may have happened is never re-run

Revision ID: b3e7c9a15d24
Revises: a6d2f8c41e97
Create Date: 2026-10-26 10:30:00.000000

`idempotency_records.status` gains `in_doubt`: a holder about to start a side effect it
cannot take back (a real phone call) commits it first, and the lease re-claim never takes
such a record. Before this, a dial whose placement was unconfirmed left the key
`processing`, and the same Idempotency-Key retried after the ten-minute lease came back
`fresh` and placed a second call.

The constraint is re-added NOT VALID, as `e3b9d5f1a827` does: every existing value is in
the old set. The downgrade refuses while an `in_doubt` row exists, rather than rewriting it
as something it is not; the rows expire with the 24-hour TTL sweep.
"""

from collections.abc import Sequence

from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline
from sqlalchemy import text

revision: str = "b3e7c9a15d24"
down_revision: str | None = "a6d2f8c41e97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `reliability.models.IDEMPOTENCY_STATUSES`, frozen at this revision.
_BEFORE = ("processing", "completed", "failed")
_AFTER = ("processing", "in_doubt", "completed", "failed")
_CK = "ck_idempotency_records_status_enum"


def _statuses(values: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE idempotency_records DROP CONSTRAINT IF EXISTS {_CK}")
    op.execute(
        f"ALTER TABLE idempotency_records ADD CONSTRAINT {_CK} "
        f"CHECK (status IN ({listed})) NOT VALID"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _statuses(_AFTER)


def _refuse_while_in_doubt() -> None:
    # Offline there is no table to count; the rendered script is reviewed by a human who
    # runs it against a database they can check for in_doubt rows first.
    if probe_skipped_offline("in_doubt idempotency rows are not counted offline; check none exist"):
        return
    held = op.get_bind().execute(
        text("SELECT count(*) FROM idempotency_records WHERE status = 'in_doubt'")
    ).scalar_one()
    if held:
        raise RuntimeError(
            f"{held} idempotency record(s) are in_doubt; downgrading would let their keys "
            "be re-run. Wait for the 24-hour TTL sweep to remove them, then retry."
        )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _refuse_while_in_doubt()
    _statuses(_BEFORE)
