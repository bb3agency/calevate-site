"""the carrier's own id for the call, so a deletion request has a handle to quote

Revision ID: c7f1a9d4e620
Revises: b4e17c920fd3
Create Date: 2026-09-18 00:00:00.000000

One nullable TEXT column on `calls`, and nothing writes it yet. That is deliberate and is
stated rather than hidden: the writer is the voice-worker seam, which is another change's
to make, and shipping the column separately is what lets that change be one INSERT field
instead of a migration plus a deploy ordering question.

WHAT IT HOLDS AND WHY IT IS NOT `engine_call_id`
----------------------------------------------------------------------------------
`voice_worker/carrier.py:182` computes a `carrier_call_id` — the CARRIER's id for the
call, taken from the telephony websocket handshake (`start.callId`) — and its own
docstring says it "is NOT `SessionConfig.call_id`, which is ours". `calls.engine_call_id`
holds OURS (or the engine's), and the two identify the same conversation in two different
vendors' systems. Until now the carrier's id existed for the length of one websocket and
was then discarded.

THE CONSEQUENCE THAT MAKES IT A COLUMN
----------------------------------------------------------------------------------
A DPDP §12 erasure reaches every copy WE hold, and the certificate is honest about the
copies we cannot reach: a sub-processor's own records are asked for in writing. A written
request to a telephony vendor has to name the calls it is about, and the only identifier
that vendor's CDR is keyed on is theirs. Without this column the request can name a number
and a date range and nothing else — which is both slower for them and wider than the
request should be, since a number and a date range is a fishing expression where a call id
is a fact.

NULLABLE, AND NOT UNIQUE
----------------------------------------------------------------------------------
Nullable because every call already in this table has no such id and never will, and
because the value only exists on the carrier-attached leg — a backfill would be inventing
identifiers (hard rule 11). Not unique and not indexed: nothing reads it yet, and an index
nobody queries is a write cost and a lock on every dial for a benefit nobody has asked for.
The moment a reader exists — an operator looking a call up by the carrier's id — it takes
one more migration, which is cheaper than guessing now.

IT SURVIVES AN ERASURE, WHICH IS THE POINT
----------------------------------------------------------------------------------
No scrub arm clears this column, and that is not an omission for a later change to fix. It
is a VENDOR-SIDE identifier, not the data principal's data: it names a row in somebody
else's system and says nothing about a person on its own. The erasure needs it to survive
for the same reason `recording_erasure_holds` exists — clearing the only handle on a copy
we are obliged to have destroyed is what makes that copy permanently unreachable.

REVERSIBILITY
----------------------------------------------------------------------------------
`drop_column` restores the previous shape exactly; no data anything reads is lost, because
nothing reads it. Once a writer exists, hard rule 8's two-step applies as usual: stop
writing it, ship, then drop.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7f1a9d4e620"
down_revision = "b4e17c920fd3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("carrier_call_id", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "carrier_call_id")
