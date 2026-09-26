"""the autodialer notice names the numbers the calls will come from

Revision ID: f39583a282fb
Revises: f2a9c31d7b64
Create Date: 2026-09-26 10:00:00.000000

The TCCCPR Third Amendment (18 Sep 2026), as an access provider summarised it, requires an
entity making A2P calls to declare that use and the CLIs it will use to its access provider
in advance, and treats an undeclared A2P call as unsolicited commercial communication
(`docs/evidence/trai-tcccpr-third-amendment-2026-09-18.md`, REPORTED). `autodialer_notices`
already records the Regulation 4 notice of autodialler use and its objective; this adds the
numbers, so the same record answers the new question and the dial gate can refuse a call
from a number the sender never declared.

A constant empty-array default, so the ADD is a catalogue change and rewrites no rows.
Existing notices read as declaring no numbers, which is true of them. The number-of-numbers
limit is enforced in `compliance/autodialer.py` rather than by a CHECK, for the reason that
module gives its other limits: it is ours, not the regulator's, and should be correctable
without a migration.
"""

from alembic import op

revision: str = "f39583a282fb"
down_revision: str | None = "f2a9c31d7b64"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE autodialer_notices "
        "ADD COLUMN declared_clis text[] NOT NULL DEFAULT '{}'::text[]"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE autodialer_notices DROP COLUMN IF EXISTS declared_clis")
