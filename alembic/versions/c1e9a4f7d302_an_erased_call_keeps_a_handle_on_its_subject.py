"""An erased call keeps a handle on its subject, so a later erasure can still reach it

Revision ID: c1e9a4f7d302
Revises: b7e4c1a90d38
Create Date: 2026-08-18 10:05:00.000000

D-310.

THE DEFECT. `execute_deletion_request` finds a subject's calls with
`from_e164 = :phone OR to_e164 = :phone` and then CLEARS both columns. After it has run,
that call is unreachable to every future erasure of the same person: the only keys that
ever joined the call to the subject are gone. That is invisible while nothing else ever
writes to an erased call — and something does. A call still IN FLIGHT when the erasure
executes has no transcript, no extraction and no lead yet; the ordinary post-call
pipeline writes all three afterwards, plus the summary, the recording pointer and the
archived vendor document. The certificate is false within the pipeline's two-minute SLO,
and the re-filed erasure that D-310 adds could locate the person's LEAD and not the call
their transcript hangs off.

WHAT THIS COLUMN IS. The same instrument, for the same reason, as
`deletion_requests.subject_ref` (migration f4a8e1c07b62): when the number is cleared, a
one-way handle is what remains so the record stays answerable to anyone who already
holds the number and to nobody who does not — `compliance/export.subject_ref`, the one
construction the proof, the export and the DNC tombstone all share. It is written only
by the per-subject erasure, only on the calls that erasure covered, and it is read only
by a later erasure of the same subject.

NOT A SECOND COPY OF THE NUMBER, and the direction matters: it cannot be dialled, it
cannot be exported into a CRM, and it is already what `deletion_requests` keeps on a far
more sensitive row (the register of who exercised a right). What it adds is the ability
to finish a job we had already started.

The index is PARTIAL because the population is: only erased calls carry a value, and the
lookup runs inside one tenant's RLS session on a table that is otherwise the largest we
have.

Reversible: the column and its index drop cleanly. Nothing reads it except the erasure's
own lookup, which falls back to the two phone columns exactly as it did before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1e9a4f7d302"
down_revision = "b7e4c1a90d38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("erased_subject_ref", sa.Text(), nullable=True))
    op.create_index(
        "ix_calls_erased_subject_ref",
        "calls",
        ["tenant_id", "erased_subject_ref"],
        postgresql_where=sa.text("erased_subject_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_calls_erased_subject_ref", table_name="calls")
    op.drop_column("calls", "erased_subject_ref")
