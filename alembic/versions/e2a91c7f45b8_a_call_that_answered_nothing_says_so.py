"""a call that answered nothing says so: calls.knowledge_state

Revision ID: e2a91c7f45b8
Revises: d8a05e4c7b13
Create Date: 2026-09-20 00:00:00.000000

WHAT THIS IS FOR
----------------
When a client's knowledge pack fails to load, `voice_worker/knowledge.py` answers
`temporarily_unavailable` to EVERY question for the whole call -- deliberately, because a
conversation that dies because the KB did not load is worse than one where the agent says
it cannot verify something right now. What was missing is the other half: nothing in our
own records said it had happened. The only trace was a loguru line inside a container
Pipecat Cloud operates, so from the product nobody could tell afterwards that a call had
answered nothing at all.

WHY A COLUMN ON `calls` AND NOT A TABLE
---------------------------------------
The fact is one word per call, written once, by the writer that already upserts that row
in that transaction, and read beside the call it describes. A table would add a tenant
policy, an append-only decision, a retention arm, an erasure arm and a join, to hold one
enum that has exactly one value per call and never changes -- which is the definition of a
column. `calls.caller_memory_state` is the same shape for the same reason (D-513).

The near miss is `call_metering_refusals`, which IS a table: a call can be refused on
several legs, each with its own prose and remediation, and a refusal is evidence about one
settlement attempt rather than a property of the call. Knowledge is not like that. One
call, one pack, one answer.

WHY THE STATE AND NOT ONLY THE FAILURE
---------------------------------------
Six values, not four. `available` and `no_pack` are recorded as deliberately as the four
failures, because otherwise NULL would mean both "this call was fine" and "no worker ever
said" -- and an operator counting degraded calls cannot tell a healthy fleet from a silent
one. NULL now means exactly one thing: nothing reported. Every call placed before this
column existed, and every call of the rented Bolna engine (which has no such report), is
honestly NULL and stays that way; no backfill can invent a state for a call nobody
observed.

`no_pack` is a state and NOT a degradation: an agent whose client published no knowledge
base says so, which is a different sentence from an agent that cannot look right now.
Only the four failure states are counted or alarmed on.

THE VOCABULARY IS THE WIRE'S
----------------------------
The CHECK is written from `calevate_shared.worker_api.KNOWLEDGE_STATES`, the same Literal
the worker's `UnavailableReason` is aliased to and the same one the request body validates
against, so a reason invented in one deployable cannot reach this column from the other.

THE INDEX IS THE WARM-CONTAINER HALF
------------------------------------
One fetch failure is not one bad call. Pipecat Cloud reuses a container across sessions,
so a store outage during one agent's calls degrades every call that lands on that
container until it is replaced. `worker/service.record_observations` therefore counts this
agent's recently degraded calls when it raises the alarm, so an operator reads "the 7th
call in an hour" rather than "a call". PARTIAL on the four failure states because they are
the rare rows -- a healthy platform's index holds nothing at all -- and keyed
`(agent_id, created_at)` because that is the count's own WHERE and ORDER.

TENANCY (hard rule 1)
---------------------
`calls` is already FORCE-RLS'd under `tenant_isolation`, and a policy is a rule about ROWS:
a new column on an existing tenant table inherits it with nothing to add. No new table, so
"ships WITH its policy" has nothing to bind.

LOCKING
-------
`ADD COLUMN` with no default and no rewrite, then the CHECK as NOT VALID and a separate
VALIDATE: the constraint is therefore never taken against every existing row under an
ACCESS EXCLUSIVE lock. The index is CREATE INDEX (not CONCURRENTLY) because alembic runs
this chain inside a transaction; it is partial over a predicate no existing row satisfies,
so it builds against an empty set.

DOWNGRADE
---------
Drops the index, the constraint and the column. Nothing is stranded: the alarm still fires
(it is raised from the report on the request, not from the column) and only the durable
count is lost. Hard rule 8 satisfied without a refusal branch.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from calevate_shared.worker_api import DEGRADED_KNOWLEDGE_STATES, KNOWLEDGE_STATES

revision: str = "e2a91c7f45b8"
down_revision: str | None = "b6e41d9c3a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Both lists come from the wire vocabulary, sorted so the emitted DDL is stable across
#: runs. Every character is a Literal member typed in this repository -- no runtime value
#: is spliced into either statement (D-172).
_ALL = ", ".join(f"'{state}'" for state in sorted(KNOWLEDGE_STATES))
_DEGRADED = ", ".join(f"'{state}'" for state in sorted(DEGRADED_KNOWLEDGE_STATES))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("calls", sa.Column("knowledge_state", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE calls ADD CONSTRAINT ck_calls_knowledge_state_enum "
        f"CHECK (knowledge_state IS NULL OR knowledge_state IN ({_ALL})) NOT VALID"
    )
    op.execute("ALTER TABLE calls VALIDATE CONSTRAINT ck_calls_knowledge_state_enum")
    op.execute(
        "CREATE INDEX ix_calls_knowledge_degraded ON calls (agent_id, created_at) "
        f"WHERE knowledge_state IN ({_DEGRADED})"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP INDEX IF EXISTS ix_calls_knowledge_degraded")
    op.execute("ALTER TABLE calls DROP CONSTRAINT IF EXISTS ck_calls_knowledge_state_enum")
    op.drop_column("calls", "knowledge_state")
