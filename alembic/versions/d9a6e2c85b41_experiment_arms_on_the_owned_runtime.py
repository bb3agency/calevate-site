"""An experiment arm is its own engine record under its real agent (G3)

Revision ID: d9a6e2c85b41
Revises: c8f5d1b74a30
Create Date: 2026-10-02 00:00:00.000000

A script test publishes one engine agent per arm (`agents.service.publish_variant`). On the
owned runtime that is a `pipecat_agents` row, and the row could not be written for an arm:
`pipecat_agents.agent_id` is a foreign key to `agents` and was UNIQUE, while the arm's
config carries the VARIANT's id in `agent_id`. The insert failed on the foreign key, so no
experiment could start on this engine.

Now an arm's row keeps the real `agent_id` and names its arm in `variant_id`:

* `variant_id` — nullable, a foreign key to `prompt_experiment_variants` (RESTRICT, this
  repo's rule). NULL is the agent's own record.
* UNIQUE `(agent_id, variant_id) NULLS NOT DISTINCT` replaces UNIQUE `(agent_id)`: still one
  record for the agent itself (two NULLs collide), plus one per arm. `engine_agent_ref` stays
  UNIQUE on its own, so every ref still names exactly one row.

The constraint is a unique INDEX, because `NULLS NOT DISTINCT` (PostgreSQL 15+) is what the
control plane's `ON CONFLICT (agent_id, variant_id)` infers against, and the ORM does not
declare it (`tests/orm_schema_fidelity_test.py` judges the model-ahead direction only).

RLS is unchanged: `pipecat_agents` already carries its FORCEd tenant policy.

DOWNGRADE refuses while an arm row exists, because restoring UNIQUE `(agent_id)` over two
rows for one agent would fail half-way; the operator ends the experiment first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9a6e2c85b41"
down_revision: str | None = "c8f5d1b74a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "pipecat_agents"
_FK = "fk_pipecat_agents_variant_id_prompt_experiment_variants"
_UNIQUE = "ux_pipecat_agents_agent_variant"
_OLD_UNIQUE = "uq_pipecat_agents_agent_id"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_TABLE, sa.Column("variant_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        _FK,
        _TABLE,
        "prompt_experiment_variants",
        ["variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_UNIQUE} ON {_TABLE} (agent_id, variant_id) NULLS NOT DISTINCT"
    )
    op.drop_constraint(_OLD_UNIQUE, _TABLE, type_="unique")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pipecat_agents WHERE variant_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'experiment arm rows exist in pipecat_agents; end the "
        "experiments before downgrading'; END IF; END $$"
    )
    op.create_unique_constraint(_OLD_UNIQUE, _TABLE, ["agent_id"])
    op.execute(f"DROP INDEX IF EXISTS {_UNIQUE}")
    op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "variant_id")
