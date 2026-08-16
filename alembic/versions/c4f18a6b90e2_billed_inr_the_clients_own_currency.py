"""billed_inr — the client's spend, in the client's own currency

Revision ID: c4f18a6b90e2
Revises: a7c31e05b8d4
Create Date: 2026-08-16 15:40:00.000000

One column on `spend_state`, and it exists because that table was holding two different
facts in one place and calling them both "spend".

THE DEFECT (P1.3). `spend_state.spend_used` accumulates `cost.total_inr` — what the
ENGINE charges US, converted from USD cents by `engine/bolna.py`. Three things read it:

  * `billing/caps.py::over_cap_sql`, which is the ceiling the compliance gate enforces
    before every outbound dial;
  * `billing/cap_routes.py`, where a CLIENT sets `client_cap_spend` and is shown the
    figure it is compared against;
  * `billing/service.py::usage_summary`, which publishes it to that client as
    `spend_used_inr`.

So a client who caps themselves at ₹5,000 is stopped at ₹5,000 of **Calevate's** cost —
roughly ₹20,000 of their own bill at a 3x markup — and the number on their screen is our
supplier pricing. `billing/service.py` states the rule it was breaking in as many words:
*"The client panel never shows `unit_cost_paid`. Our supplier pricing is commercially
ours"* — while the panel three functions below published its monthly aggregate.

WHY A SECOND COLUMN RATHER THAN CONVERTING THE FIRST. Both numbers are wanted, by
different readers. `spend_used` is what the admin margin panel is FOR: margin is
`billed - paid`, and a deployment that overwrote the paid side would be unable to answer
"are we making money on this client" ever again, including retrospectively. So the two
stop being one number, which is the whole finding.

DEFAULT 0 AND NOT NULL, so every existing row is valid the moment this applies and no
reader needs a COALESCE. What that means in practice is that a tenant mid-month reads
`billed_inr = 0` until their next call meters — their cap is briefly looser than it will
be, never tighter, and it self-corrects on the next completed call. The alternative was
back-filling from `usage_events` at a markup we would have had to invent per historical
plan row; a migration that guesses a price is a migration that writes a commitment
nobody made (the argument `b1d5c8e73f04` makes about `overage_rate_value`). No
deployment has ever run, so the set of affected rows is empty in fact as well as in
principle.

PRECISION MATCHES `spend_used` EXACTLY — NUMERIC(12,4). Not a wider type "because it is
a larger number": the two are compared against caps by the same expression and summed
onto the same screens, and a pair of money columns with different scales is how a
rounding difference becomes a support ticket (hard rule 7).

NO RLS CHANGE. `spend_state` already has its FORCEd policy from `05bba2f3c19c`; adding a
column to a table under RLS inherits it, so there is nothing to add and nothing to test
that `tests/rls_test.py` does not already cover for this table.

REVERSIBLE, and the downgrade is a real drop rather than a no-op: this column has no
dependents outside the code that ships with it, and hard rule 8's two-step deprecation
governs REMOVING a column the code still writes — not un-applying a release whole.
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f18a6b90e2"
down_revision = "a7c31e05b8d4"
branch_labels = None
depends_on = None

CK_BILLED_NONNEGATIVE = "ck_spend_state_billed_inr_nonnegative"


def upgrade() -> None:
    op.add_column(
        "spend_state",
        sa.Column(
            "billed_inr",
            sa.Numeric(precision=12, scale=4),
            server_default="0",
            nullable=False,
        ),
    )
    # The same non-negativity `spend_used` has no constraint for and should: a negative
    # accrual is not a refund (refunds are `credit_ledger` entries, and that table is
    # append-only for exactly this reason) — it is arithmetic that went wrong upstream,
    # and a cap compared against a negative number is a cap that never closes. Named
    # here rather than left to the writer because the writer is one UPSERT in a worker
    # and the reader is the gate that decides whether a client may dial.
    # RAW SQL, and the name is spelled in full, because `op.create_check_constraint`
    # applies this project's naming convention to whatever it is handed — so passing the
    # already-conventional name produced `ck_spend_state_ck_spend_state_billed_inr_
    # nonnegative` on a real database. Measured, not guessed. `b1d5c8e73f04` spells its
    # own constraint out for the same reason and this follows it rather than inventing a
    # second way to name one.
    op.execute(
        f"ALTER TABLE spend_state ADD CONSTRAINT {CK_BILLED_NONNEGATIVE} CHECK (billed_inr >= 0)"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE spend_state DROP CONSTRAINT IF EXISTS {CK_BILLED_NONNEGATIVE}")
    op.drop_column("spend_state", "billed_inr")
