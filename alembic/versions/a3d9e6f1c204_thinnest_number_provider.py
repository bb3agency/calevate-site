"""`phone_numbers.provider` may name `thinnest`: a number rented and attached in ThinnestAI

Revision ID: a3d9e6f1c204
Revises: e8a4c2f17b39
Create Date: 2026-10-07 20:00:00.000000

On `ENGINE=thinnest` the calling numbers are ThinnestAI's own, rented and attached in their
console (founder decision, D-678 §1; renting is console-only, `thinnest-findings/mirror/
pages/api-reference/voices-and-models.md:85-87`). The dial gate needs a bound,
DLT-registered `phone_numbers` row to present, and `ck_phone_numbers_provider_carrier`
(c8f5d1b74a30) admitted only the two carriers Pipecat dials on, so such a number could be
recorded only under a provider that was not true. The CHECK is widened by one value;
`vobiz` and `plivo` keep their meaning. RLS is unchanged.

DOWNGRADE refuses while any row holds `thinnest` rather than rewriting it: there is no true
carrier to rewrite it to, and NULL would silently take the number off the dial gate.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "a3d9e6f1c204"
down_revision: str | None = "e8a4c2f17b39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_phone_numbers_provider_carrier"
_WIDENED = "provider IS NULL OR provider IN ('vobiz', 'plivo', 'thinnest')"
_ORIGINAL = "provider IS NULL OR provider IN ('vobiz', 'plivo')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(f"ALTER TABLE phone_numbers ADD CONSTRAINT {_CHECK} CHECK ({_WIDENED})")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    if not probe_skipped_offline(
        "offline `--sql`: the pre-flight that refuses to narrow ck_phone_numbers_provider_carrier\n"
        "while a ThinnestAI number is recorded was NOT run. The narrower CHECK re-validates\n"
        "the rows, so a stranded `thinnest` provider still aborts the script. Check first with:\n"
        "SELECT count(*) FROM phone_numbers WHERE provider = 'thinnest';"
    ):
        # FORCEd RLS is fail-closed for the owner on an unset tenant, so an unbracketed
        # count reads zero (c8f5d1b74a30's bracket, for its reason).
        op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
        held = (
            op.get_bind()
            .execute(sa.text("SELECT count(*) FROM phone_numbers WHERE provider = 'thinnest'"))
            .scalar_one()
        )
        op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")
        if held:
            raise RuntimeError(
                f"{held} phone number(s) are recorded as ThinnestAI numbers. Remove or re-record "
                "them first; there is no carrier to rewrite them to."
            )
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.execute(f"ALTER TABLE phone_numbers ADD CONSTRAINT {_CHECK} CHECK ({_ORIGINAL})")
