"""A campaign's WhatsApp follow-up, set up from its card (D-1041)

Revision ID: e7c3a9f15b42
Revises: e4b9d2a7f160
Create Date: 2026-11-24 18:00:00.000000

The campaign page's "Follow up on WhatsApp" card makes one Follow-up for its campaign, with
the message Pip writes from the campaign's main task and knowledge.

`follow_ups.campaign_id` names the campaign a Follow-up was made for, under the new starter
`campaign_whatsapp`; `uq_follow_ups_campaign_whatsapp` keeps it to one per campaign, so a
double press or a retried job reuses the row instead of making a second. Which calls start it
is still the trigger's (`trigger.campaign_ids`), frozen on each version as every trigger is;
the column is only the card's way back to its Follow-up. `ON DELETE SET NULL`: a deleted
campaign leaves its Follow-up as an ordinary one.

`campaigns.whatsapp_follow_up_state/_at/_inputs` are the agent-pass columns
(`agents/agent_pass`) of Pip's writing, and `whatsapp_follow_up_error` the short code of why
the last pass made nothing (the card's sentence), never the model's words.

NO NEW TABLE, SO NO NEW POLICY: both tables keep their FORCEd `tenant_isolation`.
Reversible: `downgrade()` drops what this adds and puts the starter CHECK back; a
`campaign_whatsapp` Follow-up made meanwhile keeps running as an ordinary one (its starter
is cleared first, so the narrower CHECK holds).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7c3a9f15b42"
down_revision: str | None = "e4b9d2a7f160"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `agents.models.FIELD_SUGGESTION_STATES` (the agent-pass ladder), frozen at this revision.
_STATES = ("queued", "running", "done", "failed", "skipped")
_OLD_STARTERS = (
    "call_new_leads",
    "qualify_new_leads",
    "missed_call_callback",
    "appointment_reminder",
    "payment_reminder",
    "win_back",
)
_NEW_STARTERS = (*_OLD_STARTERS, "campaign_whatsapp")
_STARTER_CHECK = "ck_follow_ups_starter_enum"


def _starter_check(starters: tuple[str, ...]) -> None:
    op.drop_constraint(op.f(_STARTER_CHECK), "follow_ups", type_="check")
    op.create_check_constraint(
        op.f(_STARTER_CHECK), "follow_ups", f"starter IS NULL OR starter IN {starters!r}"
    )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "follow_ups", sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_follow_ups_campaign_id_campaigns"),
        "follow_ups",
        "campaigns",
        ["campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _starter_check(_NEW_STARTERS)
    op.create_index(
        "uq_follow_ups_campaign_whatsapp",
        "follow_ups",
        ["campaign_id"],
        unique=True,
        postgresql_where=sa.text("starter = 'campaign_whatsapp' AND campaign_id IS NOT NULL"),
    )
    op.add_column("campaigns", sa.Column("whatsapp_follow_up_state", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("whatsapp_follow_up_inputs", sa.Text(), nullable=True))
    op.add_column(
        "campaigns",
        sa.Column("whatsapp_follow_up_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("campaigns", sa.Column("whatsapp_follow_up_error", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_campaigns_whatsapp_follow_up_state_enum"),
        "campaigns",
        f"whatsapp_follow_up_state IS NULL OR whatsapp_follow_up_state IN {_STATES!r}",
    )
    op.create_check_constraint(
        op.f("ck_campaigns_whatsapp_follow_up_error_shape"),
        "campaigns",
        "whatsapp_follow_up_error IS NULL OR whatsapp_follow_up_error ~ '^[a-z_]{1,48}$'",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(
        op.f("ck_campaigns_whatsapp_follow_up_error_shape"), "campaigns", type_="check"
    )
    op.drop_constraint(
        op.f("ck_campaigns_whatsapp_follow_up_state_enum"), "campaigns", type_="check"
    )
    op.drop_column("campaigns", "whatsapp_follow_up_error")
    op.drop_column("campaigns", "whatsapp_follow_up_at")
    op.drop_column("campaigns", "whatsapp_follow_up_inputs")
    op.drop_column("campaigns", "whatsapp_follow_up_state")
    op.drop_index("uq_follow_ups_campaign_whatsapp", table_name="follow_ups")
    op.execute("UPDATE follow_ups SET starter = NULL WHERE starter = 'campaign_whatsapp'")
    _starter_check(_OLD_STARTERS)
    op.drop_constraint(
        op.f("fk_follow_ups_campaign_id_campaigns"), "follow_ups", type_="foreignkey"
    )
    op.drop_column("follow_ups", "campaign_id")
