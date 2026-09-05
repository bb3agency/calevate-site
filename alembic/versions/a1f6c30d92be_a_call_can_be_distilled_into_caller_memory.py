"""a call can be distilled into caller memory, and a tenant can attest to it

Revision ID: a1f6c30d92be
Revises: b7e35c2f81da
Create Date: 2026-09-02

Three columns, no new table, and each closes one half of the gap
`compliance/caller_memory.py`'s header wrote down (D-513).

--------------------------------------------------------------------------------
1. `calls.caller_memory_state` — THE THIRD STATE, WHICH IS THE WHOLE POINT
--------------------------------------------------------------------------------
`caller_memories.source_call_id` cannot be the distiller's idempotency key, and the
reason is the one `kb_documents.gloss_state` was added for: it can only ever say
"this call produced a row". It has no way to say **"this call was read and owed
nothing"** — the answer most calls give — so a retry, an overlapping tick or a
redeploy would re-send the same transcript to the same model, pay for the same
answer, and (when the model happened to phrase a fact differently) file a second row
for one conversation. A durable NEGATIVE is a state, not the absence of a row.

Four values, and each is a different fact an operator may have to act on:

* `pending`   — nobody has looked. The DEFAULT, so a call becomes work by existing.
* `remembered`— looked at, facts written.
* `nothing`   — looked at, nothing worth remembering. Settled, and never re-read.
* `skipped`   — not looked at and never will be, because this agent does not
                remember callers (or its tenant's vertical refuses it, D-507(b)).
                Distinct from `nothing` deliberately: `nothing` cost a model call
                and `skipped` cost none, and an operator asking "is this feature
                doing anything for this client" cannot tell them apart otherwise.

THE PARTIAL INDEX IS ON `pending` for `ix_kb_documents_gloss_pending`'s reason —
the worklist is the small, shrinking side of the column, and an index over the whole
table would be paid on every call insert to serve a query that only ever wants the
head of it. `ended_at` is in the index because the sweep takes oldest-first: a
truncated tick must resume where it stopped rather than re-shuffling.

--------------------------------------------------------------------------------
2. `organizations.caller_memory_attested_at` / `_attested_by` — THE PERMISSION
--------------------------------------------------------------------------------
`compliance/caller_memory.SPDI_REFUSED_VERTICALS` says of itself that it is "a PROXY
AND KNOWN TO BE ONE ... the enable path — when one is built — is where a per-tenant
attestation belongs". This is that path's storage.

It is on `organizations` and not on `agents` because the fact being attested is about
the BUSINESS ("we do not take health, financial or other sensitive personal data over
these calls, and our callers are told we keep notes"), not about one agent. A client
running four agents attests once; an agent-level column would ask them the same
question four times and let three of the answers rot.

NULLABLE with no backfill and no default, deliberately: every existing tenant has NOT
attested, which is the true state, and the enable route refuses on it. A default of
`now()` would have silently granted the permission to the entire fleet.

`caller_memory_attested_by` is the USER who clicked, `ON DELETE SET NULL` — an
attestation survives the departure of the person who made it (it is the
organisation's, not theirs), and the audit log holds the durable actor record anyway.

--------------------------------------------------------------------------------
DDL ONLY — NO `NO FORCE`/`FORCE` BRACKET
--------------------------------------------------------------------------------
`tests/migration_rls_bracket_test.py` guards migrations that write ROWS to FORCE-RLS
tables (`b7e35c2f81da` is the repair of the seven that did not). Nothing here writes a
row: `add_column` with a `server_default` is DDL, applied by the table rewrite, and is
not subject to `tenant_isolation`. The `server_default` STAYS — see the comment in
`upgrade()`, which records the draft that dropped it and the two insert sites that
proved the premise wrong.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a1f6c30d92be"
down_revision = "c4b8e91d7a05"
branch_labels = None
depends_on = None

#: MUST equal `apps.api.compliance.caller_memory.CALLER_MEMORY_STATES`. Frozen here
#: rather than imported, for this tree's migration discipline: a CHECK constraint
#: records what the schema accepted ON THE DAY, and importing today's constant would
#: make an old migration silently mean something new. `tests/caller_memory_producer_test.py`
#: asserts the two agree, so they cannot drift without a red test.
STATES = ("pending", "remembered", "nothing", "skipped")
STATE_PENDING = "pending"

CHECK_NAME = "ck_calls_caller_memory_state_enum"
INDEX_NAME = "ix_calls_caller_memory_pending"


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column(
            "caller_memory_state",
            sa.Text(),
            nullable=False,
            server_default=STATE_PENDING,
        ),
    )
    # THE DEFAULT STAYS, AND AN EARLIER DRAFT OF THIS MIGRATION DROPPED IT.
    #
    # It dropped it on the premise that "`calls` rows are written in exactly one place",
    # so the state would have one writer and no reader would think the database decides
    # it. The premise is false: `agents/service.dispatch_call` writes the OUTBOUND row and
    # `workers/pipeline` writes the INBOUND one, and neither names this column — every
    # insert failed the NOT NULL the moment the default went away. That is the shape of
    # defect this column exists to prevent, one level up: `pending` means "nobody has
    # looked yet", which is true of every call the instant it is created, so the honest
    # value is exactly the one a default supplies for free. Making each insert site
    # restate it would make "a call becomes work by existing" depend on two call sites
    # remembering, and a third one forgetting would not error — it would silently make
    # that call invisible to the distiller for ever.
    op.create_check_constraint(
        CHECK_NAME,
        "calls",
        "caller_memory_state IN " + repr(STATES),
    )
    op.create_index(
        INDEX_NAME,
        "calls",
        ["agent_id", "ended_at"],
        postgresql_where=sa.text(f"caller_memory_state = '{STATE_PENDING}'"),
    )
    op.add_column(
        "organizations",
        sa.Column("caller_memory_attested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "caller_memory_attested_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "caller_memory_attested_by")
    op.drop_column("organizations", "caller_memory_attested_at")
    op.drop_index(INDEX_NAME, table_name="calls")
    op.drop_constraint(CHECK_NAME, "calls", type_="check")
    op.drop_column("calls", "caller_memory_state")
