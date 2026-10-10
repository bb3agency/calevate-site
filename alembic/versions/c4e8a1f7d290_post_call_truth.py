"""post-call truth: derived outcomes, two summaries, a headline, translated turns, lead rules

Revision ID: c4e8a1f7d290
Revises: b4e8d2a61c90
Create Date: 2026-10-10

The first live call (docs/evidence/first-call-review-2026-10-10.md, F-4..F-7 and founder
decisions 1, 4-8, 12) read "Resolved" after a booked call back, showed the agent's last
words as its summary, and filed a test call as a campaign lead. This revision gives the
pipeline somewhere to put the truth:

1. `calls.outcome_tag` takes the client vocabulary `call_back_booked`, `needs_you`,
   `answered`, `transferred`, `hung_up_early`, `missed`. Hard rule 8's first step: the
   CHECK admits the old four AND the new six, stored rows are rewritten to the new words
   (a call with a booked call back becomes `call_back_booked` whatever it said before),
   and nothing writes an old word after this. The next release narrows the CHECK.
2. `calls` gains `callback_requested`, `headline`, `next_step` (both stored redacted),
   `summary_local` + `summary_language` (the summary in the call's language beside the
   English `summary`), `summary_source` (`engine` or `extraction`), `summary_state`
   (`pending|ready|failed|empty`) and `translation_state`. A stored summary that is a
   transcript line (the offline runner's, `^agent:`/`^caller:`) reads `empty`; the text is
   kept (no data is destroyed here) and the API stops serving it.
3. `call_extractions` gains `outcome_hint` and `out_of_scope`: the model's own reading,
   kept so a re-drive derives the same outcome without paying for the model again.
4. `transcript_turns.text_en`: the English rendering of a turn, made from `text_redacted`
   and therefore redacted like it.
5. `leads.source` admits `test_call` and `outbound_call`; `leads.status_set_by`
   (`system|person`) + `status_set_at` say who last moved a lead's status, so the
   after-call rules never overwrite a person's choice. Existing leads read `system`.
6. Two partial indexes on `scheduled_callbacks`: by the call it was booked on (the outcome
   reads it per call) and by lead (the lead list reads the next one).

Backfills run with FORCE RLS lifted on `calls` and `leads` for the statement, the house
pattern (`a2f7c4e9d61b`), and restored in `finally`.

DOWNGRADE maps the six words back onto the four (`answered` -> `resolved`,
`call_back_booked`/`needs_you` -> `needs_follow_up`, `hung_up_early`/`missed` -> `dropped`),
moves `test_call`/`outbound_call` leads to `campaign` (the value every outbound lead carried
before), and drops what upgrade added. The English translations, headlines and local
summaries are derived text and are lost on downgrade by design.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1f7d290"
down_revision: str | None = "b4e8d2a61c90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OUTCOMES_BEFORE = "('resolved', 'needs_follow_up', 'transferred', 'dropped')"
_OUTCOMES_BOTH = (
    "('resolved', 'needs_follow_up', 'transferred', 'dropped', "
    "'call_back_booked', 'needs_you', 'answered', 'hung_up_early', 'missed')"
)
_HINTS = "('needs_you', 'answered', 'transferred', 'hung_up_early')"
_SOURCES_BEFORE = "('inbound_call', 'webhook', 'campaign', 'manual')"
_SOURCES_AFTER = "('inbound_call', 'webhook', 'campaign', 'manual', 'test_call', 'outbound_call')"

_BOOKED = (
    "EXISTS (SELECT 1 FROM scheduled_callbacks s WHERE s.source_call_id = calls.id "
    "AND s.tenant_id = calls.tenant_id AND s.status <> 'cancelled')"
)

_BACKFILL_OUTCOMES = f"""
UPDATE calls SET outcome_tag = CASE
    WHEN {_BOOKED} THEN 'call_back_booked'
    WHEN outcome_tag = 'needs_follow_up' THEN 'needs_you'
    WHEN outcome_tag = 'resolved' THEN 'answered'
    WHEN outcome_tag = 'dropped' AND status <> 'completed' THEN 'missed'
    WHEN outcome_tag = 'dropped' THEN 'hung_up_early'
    ELSE outcome_tag END
 WHERE outcome_tag IN ('resolved', 'needs_follow_up', 'dropped')
    OR (outcome_tag = 'transferred' AND {_BOOKED})
"""

_BACKFILL_SUMMARY_STATE = """
UPDATE calls SET summary_state = CASE
    WHEN summary IS NOT NULL AND summary !~* '^\\s*(agent|caller)\\s*:' THEN 'ready'
    WHEN status IN ('queued', 'ringing', 'in_progress') THEN 'pending'
    ELSE 'empty' END,
  summary_source = CASE
    WHEN summary IS NOT NULL AND summary !~* '^\\s*(agent|caller)\\s*:' THEN 'extraction'
    END,
  translation_state = CASE
    WHEN status IN ('queued', 'ringing', 'in_progress') THEN 'pending'
    ELSE 'unavailable' END
"""

_DOWNGRADE_OUTCOMES = """
UPDATE calls SET outcome_tag = CASE outcome_tag
    WHEN 'answered' THEN 'resolved'
    WHEN 'call_back_booked' THEN 'needs_follow_up'
    WHEN 'needs_you' THEN 'needs_follow_up'
    WHEN 'hung_up_early' THEN 'dropped'
    WHEN 'missed' THEN 'dropped'
    ELSE outcome_tag END
 WHERE outcome_tag IN ('answered', 'call_back_booked', 'needs_you', 'hung_up_early', 'missed')
"""


def _check(table: str, name: str, predicate: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({predicate}) NOT VALID")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.execute("ALTER TABLE calls DROP CONSTRAINT ck_calls_outcome_enum")
    _check(
        "calls",
        "ck_calls_outcome_enum",
        f"outcome_tag IS NULL OR outcome_tag IN {_OUTCOMES_BOTH}",
    )
    op.add_column("calls", sa.Column("callback_requested", sa.Boolean(), nullable=True))
    op.add_column("calls", sa.Column("headline", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("next_step", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("summary_local", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("summary_language", sa.Text(), nullable=True))
    op.add_column("calls", sa.Column("summary_source", sa.Text(), nullable=True))
    op.add_column(
        "calls",
        sa.Column("summary_state", sa.Text(), server_default="pending", nullable=False),
    )
    op.add_column(
        "calls",
        sa.Column("translation_state", sa.Text(), server_default="pending", nullable=False),
    )
    _check(
        "calls",
        "ck_calls_summary_source_enum",
        "summary_source IS NULL OR summary_source IN ('engine', 'extraction')",
    )
    _check(
        "calls",
        "ck_calls_summary_state_enum",
        "summary_state IN ('pending', 'ready', 'failed', 'empty')",
    )
    _check(
        "calls",
        "ck_calls_translation_state_enum",
        "translation_state IN ('pending', 'ready', 'failed', 'not_needed', 'unavailable')",
    )
    _check("calls", "ck_calls_headline_length", "headline IS NULL OR char_length(headline) <= 90")

    op.add_column("call_extractions", sa.Column("outcome_hint", sa.Text(), nullable=True))
    op.add_column("call_extractions", sa.Column("out_of_scope", sa.Boolean(), nullable=True))
    _check(
        "call_extractions",
        "ck_call_extractions_outcome_hint_enum",
        f"outcome_hint IS NULL OR outcome_hint IN {_HINTS}",
    )

    op.add_column("transcript_turns", sa.Column("text_en", sa.Text(), nullable=True))

    op.execute("ALTER TABLE leads DROP CONSTRAINT ck_leads_source_enum")
    _check("leads", "ck_leads_source_enum", f"source IN {_SOURCES_AFTER}")
    op.add_column(
        "leads",
        sa.Column("status_set_by", sa.Text(), server_default="system", nullable=False),
    )
    op.add_column(
        "leads", sa.Column("status_set_at", sa.DateTime(timezone=True), nullable=True)
    )
    _check("leads", "ck_leads_status_set_by_enum", "status_set_by IN ('system', 'person')")

    op.create_index(
        "ix_scheduled_callbacks_source_call",
        "scheduled_callbacks",
        ["tenant_id", "source_call_id"],
        postgresql_where=sa.text("source_call_id IS NOT NULL"),
    )
    op.create_index(
        "ix_scheduled_callbacks_lead_live",
        "scheduled_callbacks",
        ["tenant_id", "lead_id", "requested_at"],
        postgresql_where=sa.text("lead_id IS NOT NULL AND status IN ('scheduled', 'dialing')"),
    )

    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scheduled_callbacks NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_BACKFILL_OUTCOMES)
        op.execute(_BACKFILL_SUMMARY_STATE)
    finally:
        op.execute("ALTER TABLE scheduled_callbacks FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leads NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(_DOWNGRADE_OUTCOMES)
        op.execute("UPDATE leads SET source = 'campaign' WHERE source IN ('test_call', 'outbound_call')")
    finally:
        op.execute("ALTER TABLE leads FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")

    op.drop_index("ix_scheduled_callbacks_lead_live", table_name="scheduled_callbacks")
    op.drop_index("ix_scheduled_callbacks_source_call", table_name="scheduled_callbacks")

    op.execute("ALTER TABLE leads DROP CONSTRAINT IF EXISTS ck_leads_status_set_by_enum")
    op.drop_column("leads", "status_set_at")
    op.drop_column("leads", "status_set_by")
    op.execute("ALTER TABLE leads DROP CONSTRAINT ck_leads_source_enum")
    _check("leads", "ck_leads_source_enum", f"source IN {_SOURCES_BEFORE}")

    op.drop_column("transcript_turns", "text_en")

    op.execute(
        "ALTER TABLE call_extractions DROP CONSTRAINT IF EXISTS "
        "ck_call_extractions_outcome_hint_enum"
    )
    op.drop_column("call_extractions", "out_of_scope")
    op.drop_column("call_extractions", "outcome_hint")

    for name in (
        "ck_calls_headline_length",
        "ck_calls_translation_state_enum",
        "ck_calls_summary_state_enum",
        "ck_calls_summary_source_enum",
    ):
        op.execute(f"ALTER TABLE calls DROP CONSTRAINT IF EXISTS {name}")
    for column in (
        "translation_state",
        "summary_state",
        "summary_source",
        "summary_language",
        "summary_local",
        "next_step",
        "headline",
        "callback_requested",
    ):
        op.drop_column("calls", column)
    op.execute("ALTER TABLE calls DROP CONSTRAINT ck_calls_outcome_enum")
    _check("calls", "ck_calls_outcome_enum", f"outcome_tag IS NULL OR outcome_tag IN {_OUTCOMES_BEFORE}")
