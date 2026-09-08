"""inbound_stops_when_the_credit_runs_out — agents.inbound_silenced_at

Revision ID: d1a7f39c50be
Revises: b7d4e91a0c58
Create Date: 2026-09-08 00:00:00.000000

The founder's decision of 8 Sep 2026. `compliance.check_dispatch` refuses OUTBOUND at a
balance of zero or below; inbound passes through none of it, so a client whose top-up
lapsed went on having their phone answered and `workers/pipeline.py` went on debiting every
answered minute against a wallet that could only get more negative. At zero or below the
agent now stops doing business and the caller hears one short neutral line instead.

## What this column is, and what it deliberately is NOT

It is a MIRROR OF THE ENGINE, the same shape as `live_tts_voice` (c8b3f14e7a29): the
instant `agents.service.reconcile_inbound_answering` last saw the vendor accept the
credit-stop script for this agent, NULL when the agent is saying its own words.

It is NOT the policy. Whether an agent should be silent is DERIVED, from
`compliance.service.credits_exhausted` — one predicate, already shared by the dial gate,
the campaign launch gate, the admin health board, `legal/readiness.py` and the client's own
wallet summary. A second boolean recording the same fact is a second thing to be wrong: it
would be written by one path, read by another, and the day the two disagreed a paid-up
client's phone would stay silent with every screen green.

Nullable with no server default and no backfill, and that is correct rather than lazy: the
value means "the engine was observed to hold the message", and nothing has been observed
about any existing agent. The reconciler's first pass over a client with no credit stamps
the ones it actually reaches.

## No CHECK constraint

There is nothing to constrain it against. `status`/`archived_at` next door are an
EQUIVALENCE because both spellings are OURS; here the other half of the fact lives at a
third party, and a constraint tying this column to a live wallet balance would make a
routine top-up (a row in `credit_ledger`, a different table, in a different transaction)
able to violate a CHECK on `agents`.

## Locking

One `ALTER TABLE ... ADD COLUMN` of a nullable column with no default — a catalogue-only
change in PostgreSQL 11+, so it takes ACCESS EXCLUSIVE for the length of the catalogue
write and rewrites no rows. No index: the two readers both already have the tenant's agent
rows in hand (`agents.service._ANSWERING_AGENTS_SQL` scans one tenant's live answering
agents under RLS, `crm/attention.py` the same), and an index on a column that is NULL for
almost every row would earn nothing.

## RLS

None to add. `agents` is already a tenant-scoped table with its FORCEd policy (hard rule 1);
a column inherits it.

**Downgrade** drops the column. That loses only our record of what the engine is holding —
no money, no consent, no audit row — and the next reconciliation pass re-derives it from
the wallet, at the price of one vendor round trip per answering agent of an exhausted
client.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7f39c50be"
down_revision: str | None = "b7d4e91a0c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("inbound_silenced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "inbound_silenced_at")
