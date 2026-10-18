"""a test Pip prepared from a call waits for the person to check it and save it

Revision ID: b9e4c2d7a316
Revises: d5b1e8c4a7f2
Create Date: 2026-10-19 12:00:00.000000

D-822 (founder, 18 Oct 2026). "Make this call a test" is asked of Pip. Pip does not save the
test: it leaves what it was told the agent should do (and an optional title) for that call
and that person, and the call page opens its "Make this call a test" form filled with it.
The caller's lines are not copied here; the form reads them, redacted, from the call as it
always did. Saving the form or discarding it removes the row.

One row per call per person (`uq_call_test_case_drafts_call_id_requested_by`),
tenant-scoped with FORCEd RLS (hard rule 1); the cross-tenant proof is
`tests/call_test_prepare_test.py`.

**Downgrade** drops the table and with it every test Pip prepared that nobody has saved yet;
saved tests are in `agent_test_cases` and are not touched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e4c2d7a316"
down_revision: str | None = "d5b1e8c4a7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "call_test_case_drafts"
_GUC = "NULLIF(current_setting('app.tenant_id', true), '')"
_OWN_TENANT = f"(tenant_id = ({_GUC})::uuid)"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "expected IS NULL OR char_length(expected) BETWEEN 1 AND 600",
            name=op.f("ck_call_test_case_drafts_expected_length"),
        ),
        sa.CheckConstraint(
            "title IS NULL OR char_length(title) BETWEEN 1 AND 120",
            name=op.f("ck_call_test_case_drafts_title_length"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_call_test_case_drafts_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_call_test_case_drafts_call_id_calls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_test_case_drafts")),
        sa.UniqueConstraint(
            "call_id", "requested_by", name=op.f("uq_call_test_case_drafts_call_id_requested_by")
        ),
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_TABLE} FOR ALL "
        f"USING {_OWN_TENANT} WITH CHECK {_OWN_TENANT}"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
    op.drop_table(_TABLE)
