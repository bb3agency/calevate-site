"""platform_state + user deactivation + repair of two silently-dropped FKs

Revision ID: 769a9152cb06
Revises: 05bba2f3c19c
Create Date: 2026-08-10

Three things, two of them planned and one a repair:

1. `platform_state` — the single-row global switchboard holding the load-shed mode
   and the big red switch (BACKEND-PATTERNS §6 requires the mode to be DURABLE in
   Postgres; Redis is only its cache). Not tenant-scoped, deliberately not RLS'd:
   it is global by definition and is written only through the audited admin ops
   surface. Seeded with its singleton row here so a fresh database boots `normal`.

2. `users.deactivated_at` — the auth guard re-checks active state against the DB on
   every request (BACKEND-PATTERNS §7) so a cached Clerk session cannot outlive a
   deactivation. That check needs a column to read.

3. **Repair:** `agents.system_prompt_id → prompt_versions` and
   `agents.extraction_schema_id → extraction_schemas` were declared `use_alter=True`
   in the models and written into migration 05bba2f3c19c's `op.create_table(...)`,
   but Alembic does not emit `use_alter` constraints from inside `create_table` — it
   dropped them silently, so production would have carried two unenforced FKs.
   Caught by running `alembic revision --autogenerate` against a migrated database
   and reading the diff (DEV-SETUP §5 exists for exactly this). Added here as the
   separate ALTERs they were always meant to be.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "769a9152cb06"
down_revision: str | None = "05bba2f3c19c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("load_shed_mode", sa.String(), server_default="normal", nullable=False),
        sa.Column("outbound_halted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("halt_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "load_shed_mode IN ('normal', 'reduced', 'emergency', 'maintenance')",
            name=op.f("ck_platform_state_load_shed_enum"),
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_platform_state_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_state")),
    )
    # The singleton. Without it every load-shed read falls back to the in-code
    # default, which works but hides the fact that nobody can flip the switch.
    op.execute(
        "INSERT INTO platform_state (id, load_shed_mode, outbound_halted) "
        "VALUES (1, 'normal', false) ON CONFLICT (id) DO NOTHING"
    )

    op.add_column("users", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))

    # Repair (see docstring). Both are SET NULL: losing a prompt version must not
    # delete the agent, and two-step deprecation (hard rule 8) applies to columns,
    # not to constraint repairs.
    op.create_foreign_key(
        op.f("fk_agents_system_prompt_id_prompt_versions"),
        "agents",
        "prompt_versions",
        ["system_prompt_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_agents_extraction_schema_id_extraction_schemas"),
        "agents",
        "extraction_schemas",
        ["extraction_schema_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # `platform_state` inherits the app-role grants from migration 05bba2f3c19c's
    # ALTER DEFAULT PRIVILEGES (same owner role runs both), so no explicit GRANT.


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_agents_extraction_schema_id_extraction_schemas"), "agents", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_agents_system_prompt_id_prompt_versions"), "agents", type_="foreignkey"
    )
    op.drop_column("users", "deactivated_at")
    op.drop_table("platform_state")
