"""a paying client's test copy holds the client's knowledge (D-964)

Revision ID: a964c0d7e2f1
Revises: e962a4c1d7b3
Create Date: 2026-11-02 18:00:00.000000

A test copy (`agent_test_copies`, D-859) is the developer-workspace vendor agent a paying
client's test call rings through before the client has a number. It is its own vendor agent,
so like an experiment arm (D-806) it holds its own copy of each of the client's published
sources, and a claim names that holder:

* `test_copy` — NOT NULL, default false; true is the agent's test copy (one per agent, so
  `agent_id` names which), false is the agent's own vendor agent or the arm `variant_id`
  names. A constant default, so adding it rewrites no row.
* UNIQUE `(source_id, agent_id, variant_id, test_copy) NULLS NOT DISTINCT` replaces UNIQUE
  `(source_id, agent_id, variant_id) NULLS NOT DISTINCT`, which is what
  `ON CONFLICT (source_id, agent_id, variant_id, test_copy)` infers against. The primary key
  on the vendor handle is unchanged.

RLS is unchanged: `engine_kb_routes` keeps its policies. No row is written: a copy kept by a
move before this revision holds documents no claim names, and its next refresh replaces it
(`agents/service.publish_agent`).

DOWNGRADE refuses while a test copy holds a claim, because the narrower index would collide
with the agent's own claim on the same source, and dropping the claims would lose the only
record of the vendor documents; retire the copies first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a964c0d7e2f1"
down_revision: str | None = "e962a4c1d7b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROUTES = "engine_kb_routes"
_HOLDER = "ux_engine_kb_routes_holder"
_NEW_HOLDER = "ux_engine_kb_routes_holder_kind"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        _ROUTES,
        sa.Column("test_copy", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_NEW_HOLDER} ON {_ROUTES} "
        "(source_id, agent_id, variant_id, test_copy) NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX {_HOLDER}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM engine_kb_routes WHERE test_copy) "
        "THEN RAISE EXCEPTION 'test copies hold knowledge claims in engine_kb_routes; retire "
        "the copies before downgrading'; END IF; END $$"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {_HOLDER} ON {_ROUTES} (source_id, agent_id, variant_id) "
        "NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX IF EXISTS {_NEW_HOLDER}")
    op.drop_column(_ROUTES, "test_copy")
