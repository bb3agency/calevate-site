"""A scrubbed extraction is not an empty one — D-433

Revision ID: f2a6d81b39c4
Revises: e4b90d27c1f6

WHAT WAS MISSING, AS A MEASURED SENTENCE. Three sweeps in `workers/retention.py` set
`call_extractions.data = '{}'::jsonb` — the lead-clock TTL sweep (`_EXTRACTION_SQL`), the
DPDP subject erasure and the tenant erasure. After any of them the row is BYTE-IDENTICAL
to one where the agent ran and captured nothing, and those two facts are opposites: the
first means "we destroyed what it held", the second means "there was nothing to hold".

The weekly knowledge digest (`apps/api/kb/insights.py`) reads exactly that column to
answer "which required fields is the agent failing to capture", so on a tenant whose lead
retention is shorter than the digest's seven-day window it published

    Details the agent was asked to capture and often did not:
      - Preferred slot — missing on 5 of 25 calls

about an agent that captured it on all twenty-five. A false accusation against a working
agent, addressed to the business owner, manufactured by our own retention policy.

WHY A COLUMN AND NOT AN INFERENCE. Every derivation available without one is a heuristic:
`updated_at` moved later than `ended_at` (true of any edit), `errors IS NULL` (true of a
clean extraction), `moments IS NULL` (true of a call nobody looked at). A privacy- and
correctness-critical control that is "usually right" is the thing `kb/patterns.py`
explicitly refuses to build — a classifier is wrong in both directions and its limits
cannot be written down. So the fact is RECORDED by the code that creates it, in the same
UPDATE that empties the row, and read back rather than guessed.

NULLABLE, AND DELIBERATELY NOT BACKFILLED. A row already emptied before this migration is
one we genuinely cannot classify — that is the whole defect, and a backfill would be the
same guess wearing a migration's authority. NULL therefore means "not scrubbed as far as
this system knows", which reproduces today's behaviour exactly for historical rows and is
the honest reading. The exposure that leaves is bounded by the digest window: seven days
after deploy every row a digest can see was written by a scrubber that stamps this column.

NO NEW POLICY, AND THAT IS NOT AN OMISSION OF HARD RULE 1. `call_extractions` is already
`FORCE ROW LEVEL SECURITY` with `tenant_isolation` (`tenant_id = current_setting(
'app.tenant_id')`), verified in `pg_catalog` before and after this migration. A column
added to a policied table is covered by that policy — the policy is row-scoped, not
column-scoped — so there is no new tenant surface to police here. This migration creates
no table, so the "policy in the same migration" clause has nothing to attach to.

NO INDEX. Nothing filters on this column alone: the digest reads it as a per-row flag on a
window already bounded by `calls.agent_id` and `ended_at`, and the scrubbers write it on
rows they select by `updated_at`. An index would be read by nothing (DATA-MODEL §10's
measured-index rule).

NO `NO FORCE ROW LEVEL SECURITY` BRACKET, unlike e4b90d27c1f6 — that migration needed one
because its DOWNGRADE has to UPDATE rows before it can narrow a CHECK, and FORCE RLS
applies to the table owner. This downgrade drops a column and updates nothing, so there
are no rows for a policy to hide from it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2a6d81b39c4"
down_revision = "e4b90d27c1f6"
branch_labels = None
depends_on = None

TABLE = "call_extractions"
COLUMN = "scrubbed_at"


def upgrade() -> None:
    # `lock_timeout` for e4b90d27c1f6's reason: ADD COLUMN of a NULLABLE column with no
    # default is catalog-only in PG11+ and does not rewrite the table, but it still takes
    # ACCESS EXCLUSIVE briefly, and a request that queues behind a long read parks every
    # other session behind it. Three seconds, then fail and let a human pick the moment.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column(TABLE, COLUMN)
