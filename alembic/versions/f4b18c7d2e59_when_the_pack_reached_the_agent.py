"""when the pack reached the agent: agents.knowledge_pack_recorded_at

Revision ID: f4b18c7d2e59
Revises: d7c2f4a91b83
Create Date: 2026-09-15 09:00:00.000000

WHAT THIS IS FOR
----------------
`agents.knowledge_pack_sha256` (b5d3a91e7c64) says WHICH pack the call path loads. It
cannot say WHEN it started doing so, and that is the one fact a client needs in order to
read the screen: "I published an hour ago, why doesn't my agent know that?" is answered by
the pointer only when the answer is "it does". When the answer is "not yet", the client
needs to know whether "not yet" started two minutes ago (the gloss sweep runs at :12 and
:42 and will heal it) or yesterday (nothing is going to heal it and support should be
called). `kb/delivery.py` is the reader; this is the column.

WHY THIS IS NOT THE MARKER COLUMN `agents_with_stale_packs` REJECTS
-------------------------------------------------------------------
That function's docstring rejects "a marker column, or comparing `kb_documents.updated_at`
against `agents.updated_at`" as an instrument for DECIDING STALENESS, and it is right: the
digest is a total answer to "which pack does this corpus imply" and a second answer would
be drift. This column decides nothing. It is not read by the sweep, it is not compared to
anything, and no branch anywhere takes it as evidence about whether a pack is current --
`kb/delivery.py` derives every state from the digest comparison exactly as the sweep does,
and renders this only as a timestamp beside the verdict. It records WHEN, which the digest
provably cannot give: a hash of a corpus carries no clock.

`agents.updated_at` is the near miss and is wrong for the reason that docstring names --
it moves for a voice change, a call-cap change and nine other reasons, so it would date a
knowledge delivery to an unrelated edit. `KnowledgePack.built_at` is the other near miss
and is worse: it lives inside an object in a bucket, deliberately OUTSIDE the content hash
so that a rebuild that changes nothing keeps its id, which means the stored object's
`built_at` is the FIRST time that corpus was ever frozen and not the time this agent
started answering out of it.

ONE WRITER, AND IT IS THE STATEMENT THAT MOVES THE POINTER
-----------------------------------------------------------
`kb/pack.py::_RECORD_PACK_SQL` -- the single entry point every writer of the pointer
already goes through -- stamps this in the SAME `UPDATE`, so the pair can never disagree.
That statement carries `WHERE ... knowledge_pack_sha256 IS DISTINCT FROM :sha`, so a
republish of an unchanged corpus writes no row and this timestamp does NOT move. That is
the intended reading and the honest one: it means "when the pack this agent is answering
out of became the pack it is answering out of", not "when somebody last pressed publish".
A client who republishes identical text has changed nothing about what their agent knows,
and a timestamp that jumped would tell them their correction had landed when the pointer
proves it was already there.

NULL means no pack has ever been recorded for this agent -- the same day-one state the
pointer's own NULL means, and they are NULL together by construction. Rows that predate
this migration carry a pointer and a NULL timestamp, which `kb/delivery.py` renders as
"live" with no date rather than inventing one; the next real publish fills it.

TENANCY (hard rule 1)
---------------------
`agents` is already FORCE-RLS'd under `tenant_isolation`, and a policy is a rule about
ROWS: a new column on an existing tenant table inherits it with nothing to add. No new
table, so hard rule 1's "ships WITH its policy" has nothing to bind.
`tests/knowledge_delivery_rls_test.py` proves the inheritance rather than assuming it.

LOCKING
-------
One `ALTER TABLE ... ADD COLUMN` with no default and no constraint: no rewrite and no
scan on any supported Postgres, so the lock is brief on a hot table.

DOWNGRADE
---------
Drops the column. Nothing is stranded -- the pointer, which is the load-bearing half,
stays, and the timestamp refills on the next publish of any source on the agent. Hard
rule 8 satisfied without a refusal branch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b18c7d2e59"
down_revision: str | None = "d7c2f4a91b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "agents",
        sa.Column("knowledge_pack_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("agents", "knowledge_pack_recorded_at")
