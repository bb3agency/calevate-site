"""experiment arms hold the client's knowledge; the developer workspace's Studio check is recorded

Revision ID: 61a3b8e4e312
Revises: e4b7d2a9c160
Create Date: 2026-10-17 20:00:00.000000

D-806 (founder, 17 Oct 2026).

`engine_kb_routes`: an experiment arm is its own vendor agent and now holds its own copy of
each of the client's published sources, so a claim names its holder:

* `variant_id` — nullable; NULL is the agent's own vendor agent, otherwise the arm of its
  script test. No foreign key, as no column of this table has one: a claim must outlive the
  rows it names so the orphan sweep can still find the vendor object.
* UNIQUE `(source_id, agent_id, variant_id) NULLS NOT DISTINCT` replaces UNIQUE
  `(source_id, agent_id)`: still one claim per source on the agent itself (two NULLs
  collide), plus one per arm. It is a unique INDEX because `NULLS NOT DISTINCT`
  (PostgreSQL 15+) is what `ON CONFLICT (source_id, agent_id, variant_id)` infers against.
  The primary key on the vendor handle is unchanged.

`platform_state`: the last answer our developer workspace gave to "are you on our Cartesia
key for the voice?" (`studio_developer_ready`), written by the hourly Studio check and by
Studio ready. A trial agent's Studio publish needs it on (D-727), and the client voice
picker reads it rather than asking the vendor per page. Defaults to not ready: the first
hourly check after deploy records the real answer.

RLS is unchanged: `engine_kb_routes` keeps its policies and `platform_state` has none.

DOWNGRADE refuses while an arm holds a claim, because restoring UNIQUE `(source_id,
agent_id)` over an agent's and its arm's claims would fail half-way, and dropping them would
lose the only record of the vendor documents; the operator ends the experiments first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "61a3b8e4e312"
down_revision: str | None = "e4b7d2a9c160"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTES = "engine_kb_routes"
_HOLDER = "ux_engine_kb_routes_holder"
_OLD_UNIQUE = "uq_engine_kb_routes_source_agent"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(_ROUTES, sa.Column("variant_id", sa.UUID(), nullable=True))
    op.execute(
        f"CREATE UNIQUE INDEX {_HOLDER} ON {_ROUTES} (source_id, agent_id, variant_id) "
        "NULLS NOT DISTINCT"
    )
    op.drop_constraint(_OLD_UNIQUE, _ROUTES, type_="unique")
    op.add_column(
        "platform_state",
        sa.Column(
            "studio_developer_ready", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM engine_kb_routes WHERE variant_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'experiment arms hold knowledge claims in engine_kb_routes; end "
        "the experiments before downgrading'; END IF; END $$"
    )
    op.drop_column("platform_state", "studio_developer_ready")
    op.create_unique_constraint(_OLD_UNIQUE, _ROUTES, ["source_id", "agent_id"])
    op.execute(f"DROP INDEX IF EXISTS {_HOLDER}")
    op.drop_column(_ROUTES, "variant_id")
