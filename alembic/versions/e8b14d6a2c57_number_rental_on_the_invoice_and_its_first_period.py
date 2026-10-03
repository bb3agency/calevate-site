"""A number's rental reaches an invoiced account's statement, and a number recorded before
D-665 starts at its next renewal (D-665, founder decisions of 3 Oct 2026)

Revision ID: e8b14d6a2c57
Revises: d9a6e2c85b41
Create Date: 2026-10-03 00:00:00.000000

Two changes, both for `billing/number_rental.collect_number_rental`:

* `one_time_charges.kind` admits `number_rental`. An invoiced (managed) account has no
  wallet, so its rental period is a row here, keyed by the same `rental_ref` the wallet
  debit uses, and `ux_one_time_charges_tenant_kind_ref` makes it once per (number, period).
* `phone_numbers.rental_charged_from` (DATE, nullable): the first rental period the client
  is charged for. NULL means from the purchase, which is every number bought from here on.
  Every client-priced number that exists when this runs is stamped with its FIRST RENEWAL
  DATE AFTER TODAY (IST), so the period under way at the deploy is never charged and the
  next one is. Recorded in data rather than a date in code: the cutover is the instant this
  migration ran, and a column says so per number where a constant would have to be kept in
  step with a deploy nobody can see from the code. "Has a purchase debit" was the other
  candidate and was rejected: a managed number and a number bought in a trial have none
  either, so it could not tell an old number from a new one.

The renewal date is the number's own month anchored on the IST date of `created_at`,
computed from the anchor and clamped at month ends, as `number_rental.rental_period_start`
does; PostgreSQL's `date + interval 'n months'` clamps to the month's last day the same way.

DOWNGRADE re-imposes `kind IN ('setup_fee')`, which PostgreSQL validates against every row
whatever the policies say, so it refuses while an invoiced rental exists. Those rows are
money on a client's statement and are not deleted by a downgrade (hard rule 4).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b14d6a2c57"
down_revision: str | None = "d9a6e2c85b41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND_CONSTRAINT = "ck_one_time_charges_kind_enum"

# k = whole calendar months from the anchor to today; the period under way started at
# anchor + k months if that is not after today, else at anchor + (k - 1). The next renewal
# is one period on from that.
_STAMP_FIRST_RENEWAL = """
WITH anchored AS (
    SELECT id,
           (created_at AT TIME ZONE 'Asia/Kolkata')::date AS anchor,
           (now() AT TIME ZONE 'Asia/Kolkata')::date AS today
      FROM phone_numbers
     WHERE client_inr_per_month IS NOT NULL AND rental_charged_from IS NULL
), counted AS (
    SELECT id, anchor, today,
           ((date_part('year', today) - date_part('year', anchor)) * 12
            + (date_part('month', today) - date_part('month', anchor)))::int AS k
      FROM anchored
)
UPDATE phone_numbers p
   SET rental_charged_from = CASE
           WHEN (c.anchor + make_interval(months => c.k))::date <= c.today
               THEN (c.anchor + make_interval(months => c.k + 1))::date
           ELSE (c.anchor + make_interval(months => c.k))::date
       END
  FROM counted c
 WHERE p.id = c.id
"""


def upgrade() -> None:
    op.execute(f"ALTER TABLE one_time_charges DROP CONSTRAINT {_KIND_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE one_time_charges ADD CONSTRAINT {_KIND_CONSTRAINT} "
        "CHECK (kind IN ('setup_fee', 'number_rental'))"
    )
    op.add_column("phone_numbers", sa.Column("rental_charged_from", sa.Date(), nullable=True))
    # Bracketed in NO FORCE for c9d41f7b2e08's reason: the owner is subject to the tenant
    # policy, a migration has no tenant, and without it the UPDATE matches zero rows and
    # reports success.
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute(_STAMP_FIRST_RENEWAL)
    op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("phone_numbers", "rental_charged_from")
    op.execute(f"ALTER TABLE one_time_charges DROP CONSTRAINT {_KIND_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE one_time_charges ADD CONSTRAINT {_KIND_CONSTRAINT} "
        "CHECK (kind IN ('setup_fee'))"
    )
