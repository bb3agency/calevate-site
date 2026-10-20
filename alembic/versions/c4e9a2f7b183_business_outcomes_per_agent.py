"""each agent's own call outcomes, and the one each call came to

Revision ID: c4e9a2f7b183
Revises: c4f8a2d6e913
Create Date: 2026-10-20 21:00:00.000000

D-836 (founder, 20 Oct 2026). Beside the system-fact outcome (`calls.outcome_tag`), each agent
carries up to eight outcomes of its own, and each call records the one the extraction model
chose:

* `agents.business_outcomes` — JSONB array of `{key, label, meaning, lead_status}`, NULL until
  drafted or written by the owner;
* `agents.business_outcomes_draft` — the one AI draft's state, NULL = never queued;
* `calls.business_outcome` / `calls.business_outcome_label` — the chosen key and its label as
  it read then (both NULL or both set);
* `call_extractions.business_outcome` — the model's choice, so a re-drive reuses it.

Additive only: nothing stops writing a column, so there is no deprecation step. RLS is
unchanged: all three tables already carry their FORCEd policies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4e9a2f7b183"
down_revision: str | None = "c4f8a2d6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `calevate_shared.business_outcomes.MAX_BUSINESS_OUTCOMES`, frozen at this revision.
_MAX_OUTCOMES = 8
#: `agents.models.BUSINESS_OUTCOMES_DRAFT_STATES`, frozen at this revision.
_DRAFT_STATES = ("queued", "running", "done", "failed", "skipped")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents",
        sa.Column("business_outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("agents", sa.Column("business_outcomes_draft", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_agents_business_outcomes_shape"),
        "agents",
        "business_outcomes IS NULL OR (jsonb_typeof(business_outcomes) = 'array' "
        f"AND jsonb_array_length(business_outcomes) <= {_MAX_OUTCOMES})",
    )
    op.create_check_constraint(
        op.f("ck_agents_business_outcomes_draft_enum"),
        "agents",
        f"business_outcomes_draft IS NULL OR business_outcomes_draft IN {_DRAFT_STATES!r}",
    )
    op.add_column("calls", sa.Column("business_outcome", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("business_outcome_label", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_calls_business_outcome_labelled"),
        "calls",
        "(business_outcome IS NULL) = (business_outcome_label IS NULL)",
    )
    op.add_column("call_extractions", sa.Column("business_outcome", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("call_extractions", "business_outcome")
    op.drop_constraint(op.f("ck_calls_business_outcome_labelled"), "calls", type_="check")
    op.drop_column("calls", "business_outcome_label")
    op.drop_column("calls", "business_outcome")
    op.drop_constraint(op.f("ck_agents_business_outcomes_draft_enum"), "agents", type_="check")
    op.drop_constraint(op.f("ck_agents_business_outcomes_shape"), "agents", type_="check")
    op.drop_column("agents", "business_outcomes_draft")
    op.drop_column("agents", "business_outcomes")
