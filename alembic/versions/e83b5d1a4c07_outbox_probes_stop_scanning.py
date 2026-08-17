"""The four "have we already promised this?" probes stop sequential-scanning the outbox

Revision ID: e83b5d1a4c07
Revises: c4f18a6b90e2
Create Date: 2026-08-16 19:10:00.000000

THE DEFECT (P6.7). `outbox_messages` carries exactly one index — `(status, created_at)`
— nothing on `job`, no GIN on `payload`. Four places ask "did a previous run already
queue this?" as `WHERE job = :job AND payload @> :matcher`, which no index can answer, so
each is a sequential scan of a table **nothing ever deletes from**:

  * `pipeline._already_enqueued` twice per completed call — the CRM fan-out probe runs
    while holding `lock_call_writes`, on the 2-minute SLO path, contending with
    `dispatch_outbox` every 10 seconds;
  * `whatsapp.enqueue_hot_lead_whatsapp` and `enqueue_campaign_escalation`;
  * and `pipeline._pipeline_settled`'s `has_crm_fanout`, on every completed execution in
    the poller's 30-minute window, every tick.

`LIMIT 1` does not help. The common case is "no prior enqueue", which reads every row
before it can say so, and the table grows forever.

THIS MIGRATION REPLACES THE PROBE WITH THE FACT IT STANDS IN FOR, in two shapes, because
the four sites are not asking one question.

1. `calls.crm_notified_at` — the CRM fan-out (D-23) happens at most once per call, and
   the call row is already SELECTed by both askers. So the outbox probe becomes a column
   read on a row already in hand: zero extra statements in the pipeline, and one fewer
   correlated EXISTS in the poller's probe. Backfilled from the outbox rows that are the
   current answer, so no call in flight across this deploy is fanned out twice.

2. `outbox_messages.dedupe_key` + a PARTIAL UNIQUE index — the other three ask about a
   (lead, call) or a (contact), have no natural home column, and each writes exactly ONE
   outbox row. A unique key is strictly stronger than the indexed probe the finding asks
   for: `INSERT … ON CONFLICT DO NOTHING` makes once-only a database fact rather than a
   check-then-write that only `lock_call_writes` makes safe. It is also the pattern this
   repo already uses one table over — `webhook_inbox_events`' UNIQUE(provider, event_key)
   — so it is the house answer to "this side effect happens once", not a new one.

   PARTIAL (`WHERE dedupe_key IS NOT NULL`) because most outbox rows are legitimately
   un-keyed: the CRM fan-out writes one row per subscribed endpoint and they are not
   duplicates of each other. A NOT NULL column with a synthesised key per row would make
   the index meaningless and the intent unreadable.

THE BACKFILL DOES NOT CLAIM MORE THAN IT CAN. Where duplicates already exist — and they
can, from before `lock_call_writes` landed — only the FIRST row per key is stamped and
the rest stay NULL, so the unique index builds and the existing duplicates are left as
the historical fact they are. The index guards writes from here on; it does not rewrite
what already happened.

PRUNING (the other half of P6.7). `outbox_messages` and `webhook_inbox_events` are both
never-pruned, and neither is only a performance problem: an outbox payload carries a
lead's name, number and call summary, so unbounded retention of it is a DPDP exposure the
tenant retention sweep cannot reach (neither table has a `tenant_id`). The sweep lands in
`apps/workers/retention.py` with this release; the index it needs on the inbox is created
here, since `outbox_messages` already has `(status, created_at)` and can serve its own.

NO RLS CHANGE, AND THAT IS DELIBERATE. `calls` is already FORCE-RLS'd, so the new column
inherits its policy. `outbox_messages` and `webhook_inbox_events` are infra tables with no
`tenant_id` by design (`ops/routes.py` states the contract) — this migration adds no
column that changes that.

REVERSIBLE. The downgrade drops both columns and both indexes. Hard rule 8's two-step
governs removing a column the code still writes; it does not govern un-applying a release
whole.
"""

import sqlalchemy as sa
from alembic import op

revision = "e83b5d1a4c07"
down_revision = "c4f18a6b90e2"
branch_labels = None
depends_on = None

UX_OUTBOX_DEDUPE = "ux_outbox_dedupe_key"
IX_INBOX_PRUNE = "ix_inbox_prune"

#: The job names whose outbox rows ARE the current answer to "has this call been fanned
#: out to the client's CRM". Spelled here rather than imported: a migration is a
#: statement about the schema at one instant, and importing a constant that later changes
#: would silently change what this migration did (the argument `b1d5c8e73f04` makes).
CRM_JOB = "deliver_outbound_webhook"


def upgrade() -> None:
    op.add_column("calls", sa.Column("crm_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("outbox_messages", sa.Column("dedupe_key", sa.Text(), nullable=True))

    # --- backfill 1: the fan-out that already happened ------------------------
    # `created_at` of the EARLIEST outbox row for the call, not `now()`: this column is
    # read as "when did we tell the client", and stamping the deploy time would make
    # every historical call look like it was notified the minute this migration ran.
    op.execute(
        sa.text(
            "UPDATE calls c SET crm_notified_at = o.first_at FROM ("
            "  SELECT (payload -> 'data' ->> 'call_id')::uuid AS call_id, "
            "         min(created_at) AS first_at "
            "  FROM outbox_messages "
            f"  WHERE job = '{CRM_JOB}' "
            "    AND payload -> 'data' ->> 'call_id' ~ "
            "        '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' "
            "  GROUP BY 1"
            ") o WHERE c.id = o.call_id"
        )
    )

    # --- backfill 2: the three keyed promises ---------------------------------
    # One statement per job because the key is built from different payload fields, and
    # `row_number()` rather than a plain UPDATE because a pre-`lock_call_writes` double
    # enqueue would otherwise fail the unique index below. Only the first row of each
    # group is stamped; the duplicates keep NULL and stay visible as what they are.
    # A row whose payload lacks one of the fields concatenates to NULL and is skipped by
    # the `r.key IS NOT NULL` filter, which is the right answer: a promise we cannot name
    # is one this index cannot protect, and inventing a key for it would be worse.
    for job, key_expr in (
        (
            "notify_hot_lead",
            "'hot-lead:' || (payload ->> 'lead_id') || ':' || (payload ->> 'call_id')",
        ),
        (
            "send_hot_lead_whatsapp",
            "'hot-lead-whatsapp:' || (payload ->> 'lead_id') || ':' || (payload ->> 'call_id')",
        ),
        ("escalate_campaign_contact", "'campaign-escalation:' || (payload ->> 'contact_id')"),
    ):
        op.execute(
            sa.text(
                "UPDATE outbox_messages m SET dedupe_key = r.key FROM ("
                f"  SELECT id, {key_expr} AS key, "
                f"         row_number() OVER (PARTITION BY {key_expr} ORDER BY created_at, id) AS n "
                "  FROM outbox_messages "
                f"  WHERE job = '{job}'"
                ") r WHERE m.id = r.id AND r.n = 1 AND r.key IS NOT NULL"
            )
        )

    op.create_index(
        UX_OUTBOX_DEDUPE,
        "outbox_messages",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    # The prune sweep's predicate, leading with the column it filters on equality.
    # `outbox_messages` needs no twin: `ix_outbox_pending (status, created_at)` is
    # already exactly this shape.
    op.create_index(IX_INBOX_PRUNE, "webhook_inbox_events", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index(IX_INBOX_PRUNE, table_name="webhook_inbox_events")
    op.drop_index(UX_OUTBOX_DEDUPE, table_name="outbox_messages")
    op.drop_column("outbox_messages", "dedupe_key")
    op.drop_column("calls", "crm_notified_at")
