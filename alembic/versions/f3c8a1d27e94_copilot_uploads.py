"""copilot uploads — the files a person attaches to a question for Pip (D-781)

Revision ID: f3c8a1d27e94
Revises: c8e5a2f7d914
Create Date: 2026-10-15 00:00:00.000000

One row per file a person attached. The bytes are in the private uploads bucket under
`object_key`; nothing here holds them. A row is `uploading` while its body streams through
the API into the store and `ready` once the whole file is stored; `sent_at` is set when a
question carrying it is sent, which is what frees its place in the next message's limits.

THE LIFETIME IS THE CONVERSATION'S. `run_started_at` is the sign-in run the file was sent
in, exactly as on `copilot_conversation_turns` (`c7e0b2a94f13` argues the shape): a row
from an older run is deleted before the person's next upload or download, the hourly
`copilot_transcript` sweep deletes every row whose owner has no live session, "start
again" deletes them all, account erasure deletes them all, and the bucket's 30-day
lifecycle rule removes any object nothing else did.

THE WORKLIST BRIDGE IS THE TRANSCRIPT'S, UNDER THE TRANSCRIPT'S REASON. The sweep runs
untenanted and this table is FORCE-RLS'd, so it learns which tenants to visit from
`retention_worklist`, which grants an untenanted session tenant ids and nothing else. The
reason is `copilot_transcript` rather than a new one: "this account holds Pip conversation
data" is the fact both tables register, the sweep that reads it is one job, and a second
reason would widen a CHECK for no new decision.

THE ADMIN TWIN is a second table for `admin_copilot_conversation_turns`' reason: an
operator id is an `admin_users.id`, and two id spaces in one column is a cross-realm read
one predicate away. No tenant, no policy; `db/registry.py` holds the justification.

REVERSIBILITY. `downgrade()` drops both tables and the trigger. The worklist rows stay:
they carry the transcript's reason and the transcript table still exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "f3c8a1d27e94"
down_revision: str | None = "c8e5a2f7d914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "copilot_uploads"
ADMIN_TABLE = "admin_copilot_uploads"

_POLICY = (
    f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

_WORKLIST_FN = "register_retention_worklist"
_WORKLIST_REASON = "copilot_transcript"
_TRIGGER = "copilot_uploads_register_retention_worklist"

#: `attachments.MAX_FILE_BYTES`, as a CHECK: the store bound in the schema, not only in
#: the writer.
_MAX_BYTES = 20 * 1024 * 1024


def _columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=False),
        # The name the person chose, cleaned (`attachments.clean_name`). Shown back to them;
        # never in a key or a log line.
        sa.Column("file_name", sa.String(length=120), nullable=False),
        sa.Column("stored_type", sa.String(length=40), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # The PDF this row is the browser-extracted TEXT of (D-781), or NULL for a file of its
        # own. CASCADE: the text never outlives the PDF it came from.
        sa.Column("text_of", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(
            "status IN ('uploading', 'ready')", name=op.f(f"ck_{table}_status_enum")
        ),
        sa.CheckConstraint(
            "stored_type IN ('image/jpeg', 'application/pdf', 'text/plain', 'text/csv')",
            name=op.f(f"ck_{table}_stored_type_enum"),
        ),
        sa.CheckConstraint(
            f"size_bytes IS NULL OR (size_bytes > 0 AND size_bytes <= {_MAX_BYTES})",
            name=op.f(f"ck_{table}_size_bounds"),
        ),
        # A ready file has a size; an uploading one does not yet.
        sa.CheckConstraint(
            "(status = 'ready') = (size_bytes IS NOT NULL)",
            name=op.f(f"ck_{table}_ready_has_size"),
        ),
        sa.CheckConstraint(
            "length(btrim(file_name)) > 0", name=op.f(f"ck_{table}_file_name_not_blank")
        ),
        sa.UniqueConstraint("object_key", name=op.f(f"uq_{table}_object_key")),
        sa.ForeignKeyConstraint(
            ["text_of"], [f"{table}.id"], ondelete="CASCADE", name=op.f(f"fk_{table}_text_of_{table}")
        ),
        # Only a text file can be the text of a PDF.
        sa.CheckConstraint(
            "text_of IS NULL OR stored_type = 'text/plain'",
            name=op.f(f"ck_{table}_text_of_is_text"),
        ),
    ]


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        TABLE,
        *_columns(),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # WHOSE file. RLS answers "which tenant"; every read in `copilot/attachments.py`
        # also names the person.
        sa.Column("user_id", sa.UUID(), nullable=False),
        *_constraints(TABLE),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )
    op.create_index(op.f(f"ix_{TABLE}_tenant_user"), TABLE, ["tenant_id", "user_id", "created_at"])
    op.create_index(op.f(f"ix_{TABLE}_text_of"), TABLE, ["text_of"])
    for statement in (
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_{TABLE}_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID",
        f"ALTER TABLE {TABLE} ADD CONSTRAINT fk_{TABLE}_user_id_users "
        "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE NOT VALID",
    ):
        op.execute(statement)
    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint in (f"fk_{TABLE}_tenant_id_organizations", f"fk_{TABLE}_user_id_users"):
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {constraint}")

    # Hard rule 1, in the same migration as the table it protects.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    op.create_table(
        ADMIN_TABLE,
        *_columns(),
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        # Which account was on screen. Context, not ownership: SET NULL on tenant delete.
        sa.Column("viewing_tenant_id", sa.UUID(), nullable=True),
        *_constraints(ADMIN_TABLE),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{ADMIN_TABLE}")),
    )
    op.create_index(op.f(f"ix_{ADMIN_TABLE}_user"), ADMIN_TABLE, ["admin_user_id", "created_at"])
    op.create_index(op.f(f"ix_{ADMIN_TABLE}_text_of"), ADMIN_TABLE, ["text_of"])
    for statement in (
        f"ALTER TABLE {ADMIN_TABLE} ADD CONSTRAINT fk_{ADMIN_TABLE}_admin_user_id_admin_users "
        "FOREIGN KEY (admin_user_id) REFERENCES admin_users (id) ON DELETE CASCADE NOT VALID",
        f"ALTER TABLE {ADMIN_TABLE} ADD CONSTRAINT "
        f"fk_{ADMIN_TABLE}_viewing_tenant_id_organizations FOREIGN KEY (viewing_tenant_id) "
        "REFERENCES organizations (id) ON DELETE SET NULL NOT VALID",
    ):
        op.execute(statement)
    op.execute("SET LOCAL lock_timeout = '3s'")
    for constraint in (
        f"fk_{ADMIN_TABLE}_admin_user_id_admin_users",
        f"fk_{ADMIN_TABLE}_viewing_tenant_id_organizations",
    ):
        op.execute(f"ALTER TABLE {ADMIN_TABLE} VALIDATE CONSTRAINT {constraint}")

    op.execute(
        f"CREATE TRIGGER {_TRIGGER} AFTER INSERT ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {_WORKLIST_FN}('{_WORKLIST_REASON}')"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {TABLE}")
    op.drop_table(ADMIN_TABLE)
    op.drop_table(TABLE)
