"""Each campaign speaks through its own engine agent (D-1003, Phase 2 of the campaign plan)

Revision ID: f5c1a8d3e7b2
Revises: f3b8d1a6c2e9
Create Date: 2026-11-16 21:00:00.000000

Founder, 16 Nov 2026: the campaign is the worker and the agent is its voice. Start used to put
the campaign's script on the agent itself, so a number the agent answers heard the campaign
and two campaigns could not share one voice. A campaign now gets its own engine agent, the
way an inbound line does (D-997):

* `campaigns.engine_agent_ref`: the campaign's own engine agent, while it has one. Set by
  Start and by its test call, cleared when the campaign ends and the engine agent is retired.
* `campaigns.engine_agent_at`: when that engine agent was last published; a test holder of a
  campaign that never started is retired once it has sat unused.
* `campaigns.extraction_fields`: what the campaign's calls note ("What it notes"), in the
  extraction-schema field shape; empty means the agent's own.
* `engine_agent_routes.campaign_id`: which campaign an engine agent speaks for, so intake
  stamps the call. No foreign key, as `agent_id` has none: the table is global.
* `engine_kb_routes.campaign_id`: the campaign's engine agent holds its own copy of each of
  the client's published sources (D-689). UNIQUE `(source_id, agent_id, variant_id,
  test_copy, inbound_line_id, campaign_id) NULLS NOT DISTINCT` replaces the five-column holder
  index, because that is what `ON CONFLICT` on the six columns infers against.
* `calls.engine_agent_ref`: the engine agent a dial rang through, so a borrowed number is held
  per engine agent rather than per voice (two campaigns of one agent are two callers).

No data is moved here. A campaign running at deploy keeps dialling through its agent until its
next dispatch tick publishes its own engine agent (`workers/campaign_engine_agents`), and only
then is that agent put back on its own script.

No new table, so no new policy: `campaigns` and `calls` keep their FORCEd RLS, and the two
route tables keep theirs. `downgrade()` reverses it and refuses while a campaign holds a
knowledge claim, as the line migration does, for the same reason.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5c1a8d3e7b2"
down_revision: str | None = "f3b8d1a6c2e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KB_ROUTES = "engine_kb_routes"
KB_LINE_HOLDER = "ux_engine_kb_routes_holder_line"
KB_CAMPAIGN_HOLDER = "ux_engine_kb_routes_holder_campaign"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("campaigns", sa.Column("engine_agent_ref", sa.Text(), nullable=True))
    op.add_column(
        "campaigns", sa.Column("engine_agent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "extraction_fields",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("engine_agent_routes", sa.Column("campaign_id", sa.UUID(as_uuid=True)))
    op.create_index(
        "ix_engine_agent_routes_campaign",
        "engine_agent_routes",
        ["campaign_id"],
        postgresql_where=sa.text("campaign_id IS NOT NULL"),
    )
    op.add_column("calls", sa.Column("engine_agent_ref", sa.Text(), nullable=True))

    op.add_column(KB_ROUTES, sa.Column("campaign_id", sa.UUID(as_uuid=True), nullable=True))
    op.execute(
        f"CREATE UNIQUE INDEX {KB_CAMPAIGN_HOLDER} ON {KB_ROUTES} "
        "(source_id, agent_id, variant_id, test_copy, inbound_line_id, campaign_id) "
        "NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX {KB_LINE_HOLDER}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {KB_ROUTES} WHERE campaign_id IS NOT NULL) "
        "THEN RAISE EXCEPTION 'campaigns hold knowledge claims in engine_kb_routes; retire "
        "the campaigns'' engine agents before downgrading'; END IF; END $$"
    )
    op.execute(
        f"CREATE UNIQUE INDEX {KB_LINE_HOLDER} ON {KB_ROUTES} "
        "(source_id, agent_id, variant_id, test_copy, inbound_line_id) NULLS NOT DISTINCT"
    )
    op.execute(f"DROP INDEX IF EXISTS {KB_CAMPAIGN_HOLDER}")
    op.drop_column(KB_ROUTES, "campaign_id")
    op.drop_column("calls", "engine_agent_ref")
    op.drop_index("ix_engine_agent_routes_campaign", table_name="engine_agent_routes")
    op.drop_column("engine_agent_routes", "campaign_id")
    op.drop_column("campaigns", "extraction_fields")
    op.drop_column("campaigns", "engine_agent_at")
    op.drop_column("campaigns", "engine_agent_ref")
