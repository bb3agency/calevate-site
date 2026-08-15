"""platform_settings + the config-version sentinel that makes a change propagate

Revision ID: a4d17c02fb98
Revises: e6b2d94f31a7
Create Date: 2026-08-14 09:40:00.000000

PLATFORM-CONFIG §5 (data model) and §6 (propagation), phase 2 of §13's build order.

Two tables and one trigger. The trigger is the part worth reading.

**Neither table is tenant-scoped, and neither carries a `tenant_id`.** They are PLATFORM
state — one engine selection, one calling window, for every client at the same instant —
and they are reachable only from the admin realm behind `platform:config`. They are
registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with "platform-scoped, admin realm
only" as the written reason, exactly as `audit_log` and `engine_agent_routes` are.
Giving them a decorative `tenant_id` to satisfy the RLS checker was rejected: a column
nothing writes and nothing reads, existing only to make a guardrail agree, would make
this pair LOOK tenant-scoped to every sweep that discovers tables by their columns.

**`platform_config_version` is a singleton by construction**, not by convention:
`id boolean PRIMARY KEY DEFAULT true CHECK (id)` admits exactly one row, so a second one
is a constraint violation rather than a race that silently forks the sentinel. It is
seeded here, because a sentinel that does not exist until the first write means every
process polls a missing row for the life of a fresh deployment.

**THE TRIGGER IS WHY THE VERSION CAN BE TRUSTED.** The obvious design is for the
application to bump the version after it writes a setting, and it is wrong for a reason
this spec states as its own acceptance test: "a value changed in psql reaches all four
processes in <10s". An operator editing a row at 3am is a writer, and they will not run
our bump. So will a data-fix migration, and so will the next code path somebody adds.
A statement-level `AFTER INSERT OR UPDATE OR DELETE` trigger cannot be forgotten and
cannot be bypassed, which turns the version into a statement ABOUT the data rather than
a claim sitting beside it.

Statement-level rather than row-level on purpose: a five-row update is ONE config change
and should move the sentinel once. Peers rebuild the whole snapshot either way, so
bumping five times would buy nothing and cost four extra writes to a row every process
is reading.

**Concurrency.** The bump is `UPDATE ... SET version = version + 1`, which reads and
writes the row under Postgres's own row lock — two concurrent config writes serialize
on it and both bumps land. Deliberately NOT a sequence: a sequence is
transaction-independent, so a rolled-back write would still have consumed a number and
peers would rebuild a snapshot identical to the one they had. The version has to move
if and only if the data did, which is what a plain increment inside the writer's own
transaction gives.

**`updated_by` is NOT NULL and references `admin_users`.** Every value in this table was
put there by a person, and the audit row naming them is written in the same transaction
(§9). A nullable actor would make "who changed the calling window on the day the margin
moved" answerable with a shrug.

**Locking.** Two `CREATE TABLE`s and one seed INSERT — no existing table is touched, so
nothing queues behind this. `lock_timeout` is set anyway, per the house pattern.

**Downgrade** drops both tables and the trigger. Every console-managed value reverts to
its environment value or its code default at the next process restart, which is the
same state the platform is in today; no tenant data is involved.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a4d17c02fb98"
down_revision: str | None = "e6b2d94f31a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "platform_config_version",
        # `DEFAULT true CHECK (id)` — the only value the key admits is true.
        sa.Column("id", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "bumped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_config_version")),
        sa.CheckConstraint("id", name=op.f("ck_platform_config_version_singleton")),
    )
    # Seeded, so a fresh deployment polls a row that exists rather than a hole.
    op.execute("INSERT INTO platform_config_version (id, version) VALUES (true, 1)")

    op.create_table(
        "platform_settings",
        # The `Settings` FIELD NAME, exactly — not a label and not an env spelling. The
        # resolution layer applies these straight onto the model, so a key that is not a
        # field cannot resolve, and the write path refuses one at the boundary.
        sa.Column("key", sa.Text(), nullable=False),
        # The value in its JSON form. `Decimal` lands as a STRING here, never a JSON
        # double — `88.50` as a float is not 88.50, and this table holds money-adjacent
        # values (hard rule 7).
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        # WHY, for the next reader. The API requires it; nullable here because a row
        # written by a seed or a data-fix migration has no operator to state one.
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_settings_updated_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_platform_settings")),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION platform_config_bump_version() RETURNS trigger AS $$
        BEGIN
            UPDATE platform_config_version
               SET version = version + 1, bumped_at = now()
             WHERE id;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_settings_bump_config_version
        AFTER INSERT OR UPDATE OR DELETE ON platform_settings
        FOR EACH STATEMENT EXECUTE FUNCTION platform_config_bump_version();
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP TRIGGER IF EXISTS platform_settings_bump_config_version ON platform_settings")
    op.execute("DROP FUNCTION IF EXISTS platform_config_bump_version()")
    op.drop_table("platform_settings")
    op.drop_table("platform_config_version")
