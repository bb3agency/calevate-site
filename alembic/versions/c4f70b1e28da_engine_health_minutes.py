"""The state a "5xx spike" needs, because a spike is a rate and a process is not

Revision ID: c4f70b1e28da
Revises: e7b45c19a308
Create Date: 2026-08-18

OPERATIONS §4 has promised an "engine 5xx spike" alarm since the alerting section was
written and nothing anywhere raised one. The reason it was never raised is in this
migration's subject line: the condition is "N failures in M minutes", and every place
that could observe a failure — two uvicorn worker processes on `api`, however many ARQ
workers — sees only its own share of them. A module-level counter would make the
threshold mean N-times-more than it says, which is the defect D-160 fixed for the alert
suppression window and would have re-introduced here.

WHY A TABLE AND NOT REDIS. Redis is already in this deployment and `alert_admission`
already counts in it, so the boring answer was available and is deliberately refused:
that counter may only ever SUPPRESS an alert (it fails open, absolutely), while this one
CREATES one. A counter that can invent a page has to be at least as durable as the thing
it reports on, and Redis here is one container with `appendonly yes`, no replica and no
backup. CLAUDE.md's "Postgres before new infra" points the same way.

WHY (engine, minute) AND NOT A ROW PER FAILURE. A hard vendor outage is not one failure,
it is every dial, every publish and every poll failing for as long as it lasts —
thousands of rows a minute, written by the code path that is already having a bad time.
An upsert into a per-minute bucket makes the table's size a function of TIME (1,440 rows
per engine per day, and `engine.health.prune_engine_health` keeps 7 days) rather than of
how bad the outage is. The counter is incremented in the UPDATE clause, so two workers
racing on the same minute add rather than overwrite — no read-then-write and no CAS loop
(BACKEND-PATTERNS §5).

TWO COUNTERS, NOT ONE. `server_errors` is "the vendor's application answered 5xx";
`unreachable` is "nothing answered at all" (DNS, TCP, TLS, read timeout). They are
separate columns because an operator's first move differs — one is the vendor, the other
is the path to it — and they are SUMMED by the spike rule because from a dial's point of
view they are the same outage. Counting only the first would have been the worse mistake:
a vendor that is completely down usually refuses the connection rather than answering
502, so the "5xx spike" alarm would have stayed silent through the total outage and fired
only for the partial one.

**RLS.** No `tenant_id`, and never will have one: the engine is answering or it is not,
and that is one fact for the whole platform. Registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that reason, the same shape and the same
judgement `platform_state` and `platform_ai_spend` already carry. Holds an engine name,
a minute and two integers — no tenant, no call, no number, so nothing here is reachable
by a cross-tenant read even in principle.

AND ONE INDEX FOR THE SECOND MISSING ALARM. `complaint-spike on campaign` is the other
§4 promise with no call site, and its condition — "how many of this campaign's connected
calls ended in an opt-out" — is the FIRST query in this repo that filters `calls` by
`campaign_id`. That column has carried no index since it was created, because until now
nothing asked it anything; the complaint check runs once per running campaign per
30-second dispatch tick, which is exactly the shape that must not be a sequential scan of
a tenant's whole call history. `(campaign_id, started_at)`, partial on
`campaign_id IS NOT NULL`, because inbound calls are the majority of the table and belong
to no campaign at all.

Both halves are in one revision because they are one capability — OPERATIONS §4's alarms
getting the state they need — and because a half-applied pair is a state no code path
wants: the complaint check without its index is the slow query it was written to avoid,
and the engine table without the check is a table nothing writes.

**Reversible** (hard rule 8): `downgrade` drops the table and the index, which is the
whole change. Nothing else reads either, so the drop cannot orphan a column somebody is
still writing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4f70b1e28da"
down_revision: str | Sequence[str] | None = "e7b45c19a308"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "platform_engine_health"
CALLS_INDEX = "ix_calls_campaign_started"
CREATE_CALLS_INDEX = (
    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {CALLS_INDEX} "
    "ON calls (campaign_id, started_at) WHERE campaign_id IS NOT NULL"
)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "server_errors", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("unreachable", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("engine", "bucket_start", name=op.f("pk_platform_engine_health")),
        # A counter that can go backwards is an alarm that can be switched off by a bug —
        # the same reasoning `ck_platform_ai_spend_non_negative` carries.
        sa.CheckConstraint(
            "server_errors >= 0 AND unreachable >= 0",
            name=op.f("ck_platform_engine_health_non_negative"),
        ),
    )
    # The spike read is "sum the last N minutes for this engine" and the prune is "delete
    # everything older than X". The primary key (engine, bucket_start) serves the first
    # exactly; the second is a rare full scan of a table that cannot exceed a few
    # thousand rows, so it gets no index of its own.

    # Outside the migration's transaction, for the reason `e1a7c93d5b02` states:
    # CONCURRENTLY cannot run inside one, and the alternative — a SHARE lock held for the
    # whole build — blocks every call the post-call pipeline is trying to write.
    with op.get_context().autocommit_block():
        # Plain SET, not SET LOCAL: there is no transaction here for LOCAL to scope to.
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE_CALLS_INDEX)


def downgrade() -> None:
    # IF EXISTS and outside the transaction for the same reasons as the build, and
    # unconditional so it also clears an INVALID index left behind by a CONCURRENTLY
    # build that failed on a database whose `alembic_version` never advanced.
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {CALLS_INDEX}")
    op.drop_table(TABLE)
