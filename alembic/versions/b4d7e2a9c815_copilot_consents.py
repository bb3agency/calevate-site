"""copilot consents — an account owner turning Pip on for the account (D-788)

Revision ID: b4d7e2a9c815
Revises: f3c8a1d27e94
Create Date: 2026-10-15 00:00:00.000000

One row per acceptance of one version of the disclosure Pip shows before it is turned on.
Pip is off for a client account until a row exists whose version is still current under
`copilot/consent.DISCLOSURE` (a material revision re-asks the owner).

APPEND-ONLY, for `outbound_pledge_acceptances`' reason: re-accepting is a new row, and the
one it supersedes survives, because "was Pip on, and under which words, when this was
sent" is asked after the fact. `text_sha256` is the hash of the exact text shown, so the
answer does not depend on the source never having been edited.

NOT PERSONAL DATA OF A CALLER: ids, a version, a hash, the owner's address and two
instants. No erasure arm is owed for a data principal; tenant erasure retains it like the
other acceptance ledgers.

REVERSIBILITY. `downgrade()` drops the table with its policy and triggers.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7e2a9c815"
down_revision: str | None = "f3c8a1d27e94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "copilot_consents"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("disclosure_version", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "btrim(disclosure_version) <> ''", name=op.f(f"ck_{TABLE}_version_present")
        ),
        sa.CheckConstraint(
            "text_sha256 ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{TABLE}_text_sha256_hex")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            name=op.f(f"fk_{TABLE}_accepted_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    # The one read every ask runs: the latest row for one tenant.
    op.execute(
        f"CREATE INDEX ix_{TABLE}_latest ON {TABLE} "
        "(tenant_id, accepted_at DESC, created_at DESC) INCLUDE (disclosure_version)"
    )

    # Hard rule 1, in the same migration as the table it protects.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # Hard rule 4: both triggers, ALWAYS (a restore runs as `session_replication_role =
    # replica`, which skips ORIGIN triggers).
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_forbid_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_append_only")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ALWAYS TRIGGER {TABLE}_forbid_truncate")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(TABLE)
