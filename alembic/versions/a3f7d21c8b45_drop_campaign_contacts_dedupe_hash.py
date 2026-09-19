"""`campaign_contacts.dedupe_hash` is dropped — step 2 of hard rule 8's two-step.

WHAT THE COLUMN HELD AND WHY IT IS A LIABILITY RATHER THAN A DEAD COLUMN. It was
`sha256(phone_e164)[:16]` — UNSALTED, and truncated over the Indian mobile E.164 space,
which is on the order of 10^9 numbers. A rainbow table for the whole of that space is a
few minutes of one machine, so the column is the phone number in a form that reverses:
it is personal data under DPDP wearing a hash's clothes, sitting on a table a client's
own CSV upload fills. That is why retention's erasure statements NULL it rather than
leaving it (`c6b1f0d47e83` records the same reasoning for `caller_chunks`), and it is why
dropping it is a privacy improvement and not merely tidying.

WHY NOTHING NEEDS IT. It was a dedupe key within one upload and nothing ever read it:
`campaigns/service.add_contacts` dedupes within a batch on the normalized number and
across batches on `uq_campaign_contacts_campaign_id_phone_e164`, which is the real
constraint and is untouched here. D-233 stopped the write — step 1 — and shipped; the
only statements left naming the column were the two erasure UPDATEs that blank it, and
they go in the same change as this migration.

WHY THE TWO-STEP IS SATISFIED RATHER THAN SKIPPED. Hard rule 8 forbids dropping in the
same RELEASE that stops the write, so that a running old application never meets a
missing column. The write stopped in an earlier release that is deployed; this one only
removes what that release left unread. The ORM field and the two erasure arms are removed
in this same commit, so no deployed code refers to the column after the migration runs.

REVERSIBLE, AND HONEST ABOUT WHAT THAT MEANS. `downgrade` re-adds the column with the
shape it had — `Text`, nullable, no index, no constraint, which is exactly what
`e16c96e68bc5` created. It does not restore VALUES, and there is nothing to restore them
from: nothing has written one since D-233 and the erasure sweeps have been NULLing the
older ones since. A downgrade lands on the column as the previous release would have left
it after a retention pass, which is the state the old code is written against.

NO ROW GUARD, DELIBERATELY, and this is the difference from `f1c40d8b6e93` beside it.
That migration refused against a non-empty table because it renamed columns holding rates
a client had bought and frozen. This one destroys no value a reader can want: the column
is unwritten, unread and reversible in shape. A guard that refused to run against rows
would only mean the most privacy-sensitive deployment — the one with real uploads — kept
the reversible hash longest.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3f7d21c8b45"
down_revision = "f1c40d8b6e93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("campaign_contacts", "dedupe_hash")


def downgrade() -> None:
    op.add_column("campaign_contacts", sa.Column("dedupe_hash", sa.Text(), nullable=True))
