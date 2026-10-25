"""an idempotency claim carries the nonce of the holding that took it

Revision ID: a6d2f8c41e97
Revises: e3b9d5f1a827
Create Date: 2026-10-26 10:00:00.000000

`claim_idempotency` hands a `processing` record whose lease has lapsed to a second holder
under the same id, and `complete_idempotency` / `fail_idempotency` matched only on id and
status, so the abandoned holder's late report landed on its successor's claim: a late
fail reopened the key while the successor was still running and a third request with the
same key ran concurrently. `claim_nonce` is minted on every take and both terminal writers
now require it.

Nullable with no default: a row claimed by a container still on the previous release
leaves it NULL and that container completes it by id and status as before; the new code
only ever completes rows it claimed, and those carry a nonce. No RLS change —
`idempotency_records` is scoped by its lookup key, not a policy (`db/registry`).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6d2f8c41e97"
down_revision: str | None = "e3b9d5f1a827"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "idempotency_records",
        sa.Column("claim_nonce", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("idempotency_records", "claim_nonce")
