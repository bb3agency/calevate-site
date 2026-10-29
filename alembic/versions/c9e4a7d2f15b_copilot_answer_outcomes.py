"""copilot_answer_outcomes (+ admin twin): how each Pip answer went, and the person's thumbs

Revision ID: c9e4a7d2f15b
Revises: f3a8c2d61b07
Create Date: 2026-10-29 12:00:00.000000

D-937. One row per Pip answer (or per question refused at the gate), keyed by the ANSWER
turn's id, holding what the live success scores need and nothing a person said:

* which tools the answer called, which of them failed or were refused (names only);
* the immediate actions it executed (`copilot_actions` ids, so "kept" vs "undone" is read
  from the action log rather than copied), the confirm card it proposed, whether it opened a
  screen or started a background job;
* the leg that answered and whether it was a fallback; time to first token and total time;
* a gate refusal (fair use, consent, the platform brake) instead of an answer;
* the asker's thumbs up/down, a reason from a closed list and, for `other`, one short line
  redacted on write.

ONE ROW PER ANSWER, AND THE VOTE IS ON IT. A Pip conversation belongs to one person
(`copilot_conversation_turns.user_id`), so the only person who can see an answer, and so
vote on it, is the person who asked; "one vote per person per turn" is therefore one vote
per row, changeable, and a second vote table would hold exactly one row per outcome row.

NO FOREIGN KEY TO THE TURN. A conversation turn is deleted when its sign-in run ends
(hours, `copilot/session_run.py`); the scores look back 30 days. `turn_id` is a reference
for review, unique, and outlives the words it pointed at, which is the point: the scores
never hold the conversation text.

The client table is tenant data with FORCEd RLS. The admin twin has no tenant and no
policy, for `admin_copilot_actions`' reason (an operator is an `admin_users` row).

`copilot_quality_scan(since)` reads every client's rows for the admin scores page the way
`call_reply_scan` (d3f8b2c6a417) reads calls: a SECURITY INVOKER loop that enters each
tenant under its own `app.tenant_id`, called from an `admin_session()`. It also returns the
interactive and job action-log rows of the window, tagged by `kind`, so one statement serves
the page. Reversible: `downgrade()` drops the function and both tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9e4a7d2f15b"
down_revision: str | None = "f3a8c2d61b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OUTCOMES = "copilot_answer_outcomes"
ADMIN_OUTCOMES = "admin_copilot_answer_outcomes"
SCAN = "copilot_quality_scan"

_MAX_NOTE = 120


def _columns() -> list[sa.Column[object]]:
    names = postgresql.ARRAY(sa.String(length=80))
    return [
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("tools", names, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("failed_tools", names, server_default=sa.text("'{}'"), nullable=False),
        sa.Column("refused_tools", names, server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "action_ids", postgresql.ARRAY(sa.UUID()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("proposed_tool", sa.String(length=80), nullable=True),
        sa.Column("navigated", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("job_started", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("fell_back", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("first_token_ms", sa.Integer(), nullable=True),
        sa.Column("total_ms", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("refusal", sa.String(length=16), nullable=True),
        sa.Column("vote", sa.String(length=4), nullable=True),
        sa.Column("vote_reason", sa.String(length=16), nullable=True),
        sa.Column("vote_note", sa.String(length=_MAX_NOTE), nullable=True),
        sa.Column("voted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def _checks(table: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(
            "refusal IS NULL OR refusal IN ('fair_use', 'consent', 'paused')",
            name=op.f(f"ck_{table}_refusal_enum"),
        ),
        sa.CheckConstraint("vote IS NULL OR vote IN ('up', 'down')", name=op.f(f"ck_{table}_vote_enum")),
        sa.CheckConstraint(
            "vote_reason IS NULL OR vote_reason IN "
            "('wrong', 'not_done', 'too_slow', 'misunderstood', 'other')",
            name=op.f(f"ck_{table}_vote_reason_enum"),
        ),
        # A reason explains a thumbs DOWN; the free line explains `other`.
        sa.CheckConstraint(
            "vote_reason IS NULL OR vote = 'down'", name=op.f(f"ck_{table}_reason_needs_down")
        ),
        sa.CheckConstraint(
            "vote_note IS NULL OR vote_reason = 'other'", name=op.f(f"ck_{table}_note_needs_other")
        ),
        sa.CheckConstraint(
            "(vote IS NULL) = (voted_at IS NULL)", name=op.f(f"ck_{table}_vote_pair")
        ),
        # A refused question was never answered, so it has nothing to vote on.
        sa.CheckConstraint(
            "refusal IS NULL OR vote IS NULL", name=op.f(f"ck_{table}_refusal_not_voted")
        ),
        sa.CheckConstraint(
            "(first_token_ms IS NULL OR first_token_ms >= 0) AND (total_ms IS NULL OR total_ms >= 0)",
            name=op.f(f"ck_{table}_timings_non_negative"),
        ),
        sa.UniqueConstraint("turn_id", name=op.f(f"uq_{table}_turn_id")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def _add_fks(table: str, fks: Sequence[tuple[str, str, str]]) -> None:
    for column, referred, on_delete in fks:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column}_{referred} "
            f"FOREIGN KEY ({column}) REFERENCES {referred} (id) ON DELETE {on_delete}"
        )


_SCAN_SQL = f"""
CREATE OR REPLACE FUNCTION {SCAN}(since timestamptz)
RETURNS TABLE (
    scanned_tenant_id uuid,
    kind text,
    turn_id uuid,
    created_at timestamptz,
    tools text[],
    failed_tools text[],
    refused_tools text[],
    acted boolean,
    kept boolean,
    undone boolean,
    proposed_tool text,
    navigated boolean,
    provider text,
    fell_back boolean,
    first_token_ms integer,
    total_ms integer,
    completed boolean,
    refusal text,
    vote text,
    vote_reason text,
    action_tool text,
    action_tier text,
    action_status text,
    action_source text,
    vote_note text,
    voted_at timestamptz
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
BEGIN
    FOR t IN SELECT o.id FROM organizations o WHERE o.deleted_at IS NULL ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        RETURN QUERY
            SELECT t, 'answer'::text, a.turn_id, a.created_at,
                   a.tools::text[], a.failed_tools::text[], a.refused_tools::text[],
                   cardinality(a.action_ids) > 0,
                   EXISTS (SELECT 1 FROM copilot_actions x
                            WHERE x.id = ANY (a.action_ids) AND x.status = 'done'),
                   EXISTS (SELECT 1 FROM copilot_actions x
                            WHERE x.id = ANY (a.action_ids) AND x.status = 'undone'),
                   a.proposed_tool::text, a.navigated, a.provider::text, a.fell_back,
                   a.first_token_ms, a.total_ms, a.completed, a.refusal::text,
                   a.vote::text, a.vote_reason::text,
                   NULL::text, NULL::text, NULL::text, NULL::text,
                   a.vote_note::text, a.voted_at
              FROM {OUTCOMES} a
             WHERE a.created_at >= since;
        RETURN QUERY
            SELECT t, 'action'::text, NULL::uuid, x.created_at,
                   NULL::text[], NULL::text[], NULL::text[],
                   NULL::boolean, NULL::boolean, NULL::boolean, NULL::text, NULL::boolean,
                   NULL::text, NULL::boolean, NULL::integer, NULL::integer, NULL::boolean,
                   NULL::text, NULL::text, NULL::text,
                   x.tool::text, x.tier::text, x.status::text, x.source::text,
                   NULL::text, NULL::timestamptz
              FROM copilot_actions x
             WHERE x.created_at >= since;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # --- the client realm -----------------------------------------------------------------
    op.create_table(
        OUTCOMES,
        *_columns(),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        *_checks(OUTCOMES),
    )
    # The scores read a window of recent rows; the retention sweep reads the oldest.
    op.create_index(op.f(f"ix_{OUTCOMES}_tenant_created"), OUTCOMES, ["tenant_id", "created_at"])
    _add_fks(
        OUTCOMES,
        (
            ("tenant_id", "organizations", "RESTRICT"),
            # SET NULL: the score survives the colleague who asked; nobody can vote it again.
            ("user_id", "users", "SET NULL"),
        ),
    )
    op.execute(f"ALTER TABLE {OUTCOMES} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {OUTCOMES} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {OUTCOMES} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # --- the admin realm: no tenant_id, no policy (`db/registry.py` says why) -------------
    op.create_table(
        ADMIN_OUTCOMES,
        *_columns(),
        sa.Column("admin_user_id", sa.UUID(), nullable=True),
        sa.Column("viewing_tenant_id", sa.UUID(), nullable=True),
        *_checks(ADMIN_OUTCOMES),
    )
    op.create_index(op.f(f"ix_{ADMIN_OUTCOMES}_created"), ADMIN_OUTCOMES, ["created_at"])
    _add_fks(
        ADMIN_OUTCOMES,
        (
            ("admin_user_id", "admin_users", "SET NULL"),
            ("viewing_tenant_id", "organizations", "SET NULL"),
        ),
    )

    op.execute(_SCAN_SQL)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {SCAN}(timestamptz)")
    op.drop_table(ADMIN_OUTCOMES)
    op.drop_table(OUTCOMES)
