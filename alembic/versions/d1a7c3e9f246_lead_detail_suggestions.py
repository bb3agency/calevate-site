"""choice lists that follow the business: unlisted answers and lead-detail suggestions

Revision ID: d1a7c3e9f246
Revises: c8e4a1f7b2d5
Create Date: 2026-10-25 23:30:00.000000

D-889 (founder, 25 Oct 2026). A choice field's list is the business's, so it has to follow what
the business sells and what its callers ask for:

* `call_extractions.unlisted` — `{field_key: the caller's words}` for a choice field none of
  whose choices fitted. The field stays null rather than taking the nearest wrong choice.
* `agents.field_suggestions` and its state, inputs hash, dismissed fingerprints and time — the
  changes an AI pass over the agent's script, facts and unlisted answers suggests, waiting for
  the owner.

Additive only: nothing stops writing a column, so there is no deprecation step. RLS is
unchanged: both tables already carry their FORCEd policies.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a7c3e9f246"
down_revision: str | None = "c8e4a1f7b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES`, frozen at this revision.
_STATES = ("queued", "running", "done", "failed", "skipped")
#: `agents.models.MAX_FIELD_SUGGESTIONS` and `MAX_DISMISSED_SUGGESTIONS`, frozen.
_MAX_SUGGESTIONS = 6
_MAX_DISMISSED = 200


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "call_extractions",
        sa.Column("unlisted", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_call_extractions_unlisted_shape"),
        "call_extractions",
        "unlisted IS NULL OR jsonb_typeof(unlisted) = 'object'",
    )
    op.add_column(
        "agents",
        sa.Column("field_suggestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("agents", sa.Column("field_suggestions_state", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("field_suggestions_inputs", sa.Text(), nullable=True))
    op.add_column(
        "agents",
        sa.Column(
            "field_suggestions_dismissed",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "agents",
        sa.Column("field_suggestions_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_agents_field_suggestions_shape"),
        "agents",
        "field_suggestions IS NULL OR (jsonb_typeof(field_suggestions) = 'array' "
        f"AND jsonb_array_length(field_suggestions) <= {_MAX_SUGGESTIONS})",
    )
    op.create_check_constraint(
        op.f("ck_agents_field_suggestions_dismissed_shape"),
        "agents",
        "jsonb_typeof(field_suggestions_dismissed) = 'array' "
        f"AND jsonb_array_length(field_suggestions_dismissed) <= {_MAX_DISMISSED}",
    )
    op.create_check_constraint(
        op.f("ck_agents_field_suggestions_state_enum"),
        "agents",
        f"field_suggestions_state IS NULL OR field_suggestions_state IN {_STATES!r}",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f("ck_agents_field_suggestions_state_enum"), "agents", type_="check")
    op.drop_constraint(
        op.f("ck_agents_field_suggestions_dismissed_shape"), "agents", type_="check"
    )
    op.drop_constraint(op.f("ck_agents_field_suggestions_shape"), "agents", type_="check")
    op.drop_column("agents", "field_suggestions_at")
    op.drop_column("agents", "field_suggestions_dismissed")
    op.drop_column("agents", "field_suggestions_inputs")
    op.drop_column("agents", "field_suggestions_state")
    op.drop_column("agents", "field_suggestions")
    op.drop_constraint(
        op.f("ck_call_extractions_unlisted_shape"), "call_extractions", type_="check"
    )
    op.drop_column("call_extractions", "unlisted")
