"""A released phone number can be held again: e164 is unique among live numbers only

Revision ID: e3c7a1f9b542
Revises: a964c0d7e2f1
Create Date: 2026-11-03 10:00:00.000000

A released number keeps its `phone_numbers` row (`released_at` set): the rental ledger, the
calling-number filings and the audit trail name it. `uq_phone_numbers_e164` (05bba2f3c19c)
made that row hold the number for ever, so once a number was released nobody could record it
again, the client who released it included. On the engine path the vendor rents the number
FIRST (`campaigns/engine_number_purchase`), so the insert that then fails leaves a number
rented and charged to us, the purchase stuck at `renting`, and every retry refused.

UPGRADE builds `uq_phone_numbers_e164_live` (UNIQUE `e164` WHERE `released_at IS NULL`)
before dropping the constraint, so no instant admits two live holders of one number.

DOWNGRADE refuses while a number has more than one row (a released one and a later holder),
because the table-wide constraint could not be rebuilt over them and deleting either row
would lose its rental history.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3c7a1f9b542"
down_revision: str | None = "a964c0d7e2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "uq_phone_numbers_e164"
_LIVE_INDEX = "uq_phone_numbers_e164_live"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        f"CREATE UNIQUE INDEX {_LIVE_INDEX} ON phone_numbers (e164) WHERE released_at IS NULL"
    )
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT {_CONSTRAINT}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # FORCE-RLS hides every row from the owner on an unset tenant, which would let the
    # refusal below pass over rows it cannot see; the bracket lets it count them all.
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM phone_numbers GROUP BY e164 HAVING count(*) > 1) "
        "THEN RAISE EXCEPTION 'a released phone number was recorded again; the table-wide "
        "unique e164 cannot be restored over both rows'; END IF; END $$"
    )
    op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE phone_numbers ADD CONSTRAINT {_CONSTRAINT} UNIQUE (e164)")
    op.execute(f"DROP INDEX IF EXISTS {_LIVE_INDEX}")
