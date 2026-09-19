"""The two voice rungs stop being spelled with their vendors' names.

`credit_lots` carried `sarvam_inr_per_min` and `cartesia_inr_per_min`: the price of a
minute on the VALUE rung and on the PREMIUM rung, each named after whichever vendor
happened to serve that rung when the column was created. One of those vendors no longer
speaks on this product at all — the Sarvam TEXT-TO-SPEECH leg was withdrawn on
18 Sep 2026 and Gnani `timbre-v2.5` serves the value rung now — so the column that prices
that rung was named for a vendor with nothing to do with it, on a money table.

The other half is subtler and is the reason BOTH columns move. `cartesia` named a rung AND
a TTS provider, so the two vocabularies overlapped in exactly one token: `billing/
tts_volume.PLAN_BILLED_VOICE` held the string as a VENDOR and `workers/pipeline.py`
compared a call's TIER against it. That matched — for the wrong reason, and only while the
coincidence held. Renaming the rungs to `clear` and `studio` (what the client has always
been shown, `billing/rates.VOICE_TIER_LABELS`) turned it into a type error, which is how
it was found.

**WHY THIS IS SAFE TO DO AS A RENAME AND WHY IT WILL NOT BE SAFE AGAIN.** A lot's two
rates are FROZEN at purchase by a trigger that refuses any UPDATE, so renaming the columns
that hold them would normally mean restating terms a client had already bought. It does
not here: nothing has ever been sold. The founder verified on the production host on
18 Sep 2026 that `credit_lots`, `organizations` and `usage_events` were all empty, and
this migration does not take that reading on trust — it COUNTS THE ROWS ITSELF and refuses
to run against a non-empty `credit_lots`. From the first sale onward these names are
frozen with the rates they hold.

**WHY A RENAME AND NOT HARD RULE 8's TWO-STEP.** That rule protects live data across a
release boundary: add the new column, backfill, stop writing the old, drop it later. Every
step of it buys something only when there are rows to carry across and a running release
reading the old name. There are neither — the count is zero and this deploy swaps the
application in the same window — so the two-step would leave four rate columns on a money
table for a week and a backfill nobody could verify against anything. `ALTER TABLE ...
RENAME COLUMN` is atomic, loses no value, and is exactly reversible, which the two-step is
not.

Renaming a column carries its CHECK constraints with it — PostgreSQL stores the expression
parsed, against attribute numbers, so `studio_inr_per_min >= clear_inr_per_min` is what the
old expression renders as afterwards without being rewritten. The constraints are renamed
too, because a constraint called `ck_credit_lots_cartesia_not_below_sarvam` on columns with
neither word in them is the next reader's wasted hour.

Revision ID: f1c40d8b6e93
Revises: d8b3f5127ac4
"""

from __future__ import annotations

from alembic import op

revision = "f1c40d8b6e93"
down_revision = "d8b3f5127ac4"
branch_labels = None
depends_on = None

_TABLE = "credit_lots"

#: `(old, new)` per direction, columns first and then the constraints that mention them.
#: Constraint names are the RENDERED ones here, not the bare ones `op.drop_constraint`
#: takes: `ALTER TABLE ... RENAME CONSTRAINT` is raw SQL and never passes through
#: `alembic/env.py`'s naming convention, so it needs the name PostgreSQL actually holds.
_COLUMNS = (("sarvam_inr_per_min", "clear_inr_per_min"), ("cartesia_inr_per_min", "studio_inr_per_min"))
_CONSTRAINTS = (
    ("ck_credit_lots_sarvam_rate_positive", "ck_credit_lots_clear_rate_positive"),
    ("ck_credit_lots_cartesia_not_below_sarvam", "ck_credit_lots_studio_not_below_clear"),
)


def _refuse_if_sold() -> None:
    """Stop rather than rename the columns under rates somebody has bought.

    THE GUARD IS THE POINT OF THIS MIGRATION BEING ACCEPTABLE AT ALL. The argument for a
    straight rename is "no row holds one of these rates"; a migration that asserts that
    argument instead of checking it would apply cleanly on the day it stopped being true
    and silently rename the columns under frozen terms. `count(*)` on an empty table is
    free, and on a non-empty one it is the only chance anybody gets.

    Deliberately NOT `SET ROLE` or RLS-bracketed: migrations run as the owner, and the
    count must see every tenant's rows — a policy-filtered zero here would be the exact
    false reassurance this function exists to refuse.
    """
    sold = op.get_bind().exec_driver_sql(f"SELECT count(*) FROM {_TABLE}").scalar_one()
    if sold:
        raise RuntimeError(
            f"{_TABLE} holds {sold} row(s), each with two per-minute rates FROZEN at "
            "purchase. Renaming the columns they sit in restates terms a client has "
            "already bought, which this migration will not do silently. If the rename is "
            "genuinely wanted with live lots, it needs a decision-log entry and a plan for "
            "the sold terms — not this revision."
        )


def upgrade() -> None:
    _refuse_if_sold()
    for old, new in _COLUMNS:
        op.execute(f"ALTER TABLE {_TABLE} RENAME COLUMN {old} TO {new}")
    for old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_TABLE} RENAME CONSTRAINT {old} TO {new}")


def downgrade() -> None:
    _refuse_if_sold()
    for old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {_TABLE} RENAME CONSTRAINT {new} TO {old}")
    for old, new in _COLUMNS:
        op.execute(f"ALTER TABLE {_TABLE} RENAME COLUMN {new} TO {old}")
