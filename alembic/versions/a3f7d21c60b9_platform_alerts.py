"""platform_alerts: every alarm gets a row, and only the loud ones get an email

Revision ID: a3f7d21c60b9
Revises: e4b7a10c92d6
Create Date: 2026-09-11

**WHY (D-591).** `core/alerting.py` mailed every alarm code, so an evening of four
ordinary deploys, one browser extension and one already-diagnosed FX outage buried the one
message that mattered. The founder's instruction was "failures in the admin panel only,
high priority things through mail" — which needs somewhere for the panel to read FROM, and
there was no alert storage of any kind.

**A ROW IS AN EPISODE.** `fx_rate_stale` fires on every cost conversion while a vendor feed
is down; twenty-six deliveries were one condition. `uq_platform_alerts_open_fingerprint` —
a PARTIAL unique index on `fingerprint WHERE cleared_at IS NULL` — is what makes that true
in the schema rather than in a convention: at most one OPEN episode per `stage:code`, so
the writer can `INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING (xmax = 0)` and learn,
in one statement, whether this occurrence OPENED the episode. Only an opening occurrence is
allowed to mail. Without the partial predicate the index would collapse a code's entire
history into one row and the onset/clear transition would have nowhere to live.

**NO RLS AND NO `tenant_id`**, registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with
the reason written out there. An alarm is about this platform's machinery, and a great many
of them fire with no tenant in scope at all.

**HARD RULE 6 IS A PROPERTY OF THE WRITER, NOT OF THE COLUMN**, so the columns say so:
`detail` and `ids` are passed through `core/logging.redact_mapping` before they are bound,
the same function the alert email body uses. The COMMENTs below are for the next person
reading the schema without the model in front of them.

**REVERSIBLE.** The downgrade drops the table. It loses only alert HISTORY — the durable
record of every one of these is the ERROR log line `alert()` writes first and
unconditionally, which is why nothing else in the system reads this table for truth.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3f7d21c60b9"
down_revision = "e4b7a10c92d6"
branch_labels = None
depends_on = None

TABLE = "platform_alerts"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "fingerprint",
            sa.Text(),
            nullable=False,
            comment="stage:code — the same key core/alerting.py deduplicates on.",
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column(
            "severity",
            sa.Text(),
            nullable=False,
            comment=(
                "page | attention | record, as core/alarm_severity.py had it at the time. "
                "Recorded on the row so a later re-classification does not rewrite the "
                "history of what was actually mailed."
            ),
        ),
        sa.Column("service", sa.Text(), nullable=False),
        sa.Column(
            "detail",
            sa.Text(),
            nullable=True,
            comment=(
                "REDACTED through core/logging.redact_mapping before binding, and capped "
                "(hard rule 6). Never a payload, never transcript text."
            ),
        ),
        sa.Column(
            "ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "The **ids the call site passed, through the same redaction. Ids only "
                "(hard rule 6): phone-shaped runs are masked and PII-shaped keys blanked."
            ),
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "occurrences",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
            comment=(
                "Every occurrence in this episode, including the ones the repeat window "
                "withheld from delivery — so it runs far ahead of the email count."
            ),
        ),
        sa.Column("emailed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cleared_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Set by workers/alerts.sweep_alert_clears when the condition has been "
                "quiet for ALERT_CLEAR_AFTER_S. NULL means it is still happening, which "
                "is what the partial unique index below keys on."
            ),
        ),
        sa.CheckConstraint(
            "severity IN ('page', 'attention', 'record')",
            name=op.f(f"ck_{TABLE}_severity"),
        ),
        sa.CheckConstraint("occurrences >= 1", name=op.f(f"ck_{TABLE}_occurrences_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
        comment=(
            "One EPISODE of one alarm (D-591). Platform-scoped: no tenant_id and no RLS, "
            "registered in db/registry.RLS_EXEMPT_TENANT_COLUMNS."
        ),
    )
    # THE UPSERT TARGET. Partial, so a cleared episode does not block the next one.
    op.create_index(
        "uq_platform_alerts_open_fingerprint",
        TABLE,
        ["fingerprint"],
        unique=True,
        postgresql_where=sa.text("cleared_at IS NULL"),
    )
    # The console's default order, and the clear sweep's scan.
    op.create_index(
        "ix_platform_alerts_last_seen",
        TABLE,
        [sa.text("last_seen_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_alerts_last_seen", table_name=TABLE)
    op.drop_index("uq_platform_alerts_open_fingerprint", table_name=TABLE)
    op.drop_table(TABLE)
