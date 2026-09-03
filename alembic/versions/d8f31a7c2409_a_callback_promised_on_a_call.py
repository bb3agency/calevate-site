"""a callback promised on a call, and the tick that has to keep the promise

Revision ID: d8f31a7c2409
Revises: a1f6c30d92be
Create Date: 2026-09-02 00:00:00.000000

A caller says "ring me back Tuesday at four". Until now the agent could only say yes and
hope somebody read the transcript. `scheduled_callbacks` is where that promise lives, and
the shape of the table is decided by two facts about what it holds.

**IT IS A PROMISE TO A PERSON, SO EVERY ENDING IS ON THE ROW.** A campaign contact can sit
`pending` for a week and nobody is waiting; a callback cannot. `status` therefore has SIX
terminal spellings rather than one, and `last_refusal_rule`/`last_refusal_reason` carry the
gate's own words for the two that are refusals — so the client's screen can say WHY a call
they were told about did not happen. `tests/dispatch_refusal_settlement_test.py` records
three livelocks that shipped from getting exactly this wrong on the campaign side, all of
them invisible because nothing errored; the answer here is that no state is silent.

**IT IS BOOKED FROM AN UNSIGNED IN-CALL TOOL, SO THE IDENTITY IS THE EXECUTION.**
`source_execution_id` is NOT NULL and unique per tenant, and it is the upsert key. The
alternative — keying on `source_call_id` — cannot work at the moment of booking: the
`calls` row is written by the status webhook, which may not have arrived (or may have been
lost; D-31 makes the poller the guarantee of record), so the FK is nullable and is a
POINTER rather than the identity. Keying on the execution means the model invoking the
tool twice, the engine retrying it, and the caller changing their mind mid-sentence all
converge on ONE row — the last of which is the interesting case, and is why the upsert is
guarded by `booked_at` rather than by "do nothing": "make it five, not four" must move the
time, and two jobs racing must land on the caller's LATER word whichever of them commits
first.

**THE TICK FINDS THEM THROUGH `dispatch_scan()`, NOT THROUGH A SWEEP OF ITS OWN.**
`scheduled_callbacks` is FORCE-RLS'd, so "which tenants have one due" only exists inside a
tenant session — the identical problem c7e4b19d3f52 solved for scheduled campaign starts,
with the identical answer: a fifth output column on the same walk, under the same
per-tenant `app.tenant_id`, costing one more sub-select per tenant already being visited
and not one connection. A separate cron would have meant a second lease, a second scan, a
second overlap alarm and a second opinion about the outbound line budget — four new places
to disagree with the campaign tick about how many phones may ring at once.

The column asks "is one DUE", not "is there one", for the reason c7e4b19d3f52 states: a
callback booked for next Tuesday is not work, and the loose question would buy its tenant a
`tenant_session` every thirty seconds for a week. It stays a proven SUPERSET —
`callbacks.service` is the authority on what due MEANS — because a superset costs one
session and a subset silently never rings anybody.

**A `dialing` ROW COUNTS AS WORK TOO, and leaving it out was a bug caught while writing
this.** A callback whose dial has been placed is ended by `settle_dialled`, which runs
inside the same visit; if the screen only counted `scheduled` rows, the last callback of a
tenant's day would be dialled, the tenant would then have nothing "due", the tick would
stop visiting it, and the row would sit at "calling now" for ever with the call long since
finished. `dialing` is bounded and short-lived (the reaper ends it after the longest a call
may last), so it cannot become standing work.

`ix_scheduled_callbacks_due` is the twin of `ix_campaigns_scheduled`: fully partial on the
literal `'scheduled'` that appears in the function body, so the planner can prove the qual
implies the predicate (PG16 §11.8). `requested_at` is a real timestamptz column here — not
a JSON cast — so it goes IN the index rather than being left as a filter.

RLS: `tenant_id` with the FORCEd `tenant_isolation` policy, verbatim from DATA-MODEL §1.
Cross-tenant zero-rows test: `tests/scheduled_callback_rls_test.py`.

NO DML AT ALL in either direction, so no `NO FORCE`/`FORCE` bracket is needed (contrast
b7e35c2f81da, and `tests/migration_rls_bracket_test.py` which reads for it). Reversible:
`downgrade()` drops the index, the policy and the table, and restores the four-column
function verbatim.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f31a7c2409"
down_revision: str | Sequence[str] | None = "a1f6c30d92be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "dispatch_scan"
DUE_INDEX = "ix_scheduled_callbacks_due"

#: DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns ''
#: when unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    "CREATE POLICY tenant_isolation ON scheduled_callbacks USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)

#: The statuses a callback can be in. A CHECK rather than a comment, because five of the
#: seven are ENDINGS a screen renders differently and a typo would produce a row no screen
#: has a sentence for.
#:
#: * `scheduled` — booked, waiting for its time.
#: * `dialing`   — claimed by a tick; the dial is in flight or has rung.
#: * `completed` — the call happened. Written by the post-call pipeline's resolution.
#: * `cancelled` — the caller or the client called it off before it rang.
#: * `refused`   — the compliance gate said no, permanently (DNC, no consent, ...).
#: * `missed`    — the gate said no transiently until the promise went stale.
#: * `failed`    — we tried to dial and could not, or cannot prove we did not.
_STATUSES = (
    "'scheduled', 'dialing', 'completed', 'cancelled', 'refused', 'missed', 'failed'"
)

# One statement per tenant still (a8d4f21c9b06 measured the SPI round trip as the cost
# that matters at this iteration count): the fourth question rides along in the same
# SELECT rather than adding a fifth statement.
_FUNCTION_SQL_V3 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (
    scanned_tenant_id uuid,
    active_outbound integer,
    has_running_campaign boolean,
    has_due_schedule boolean,
    has_due_callback boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    live integer;
    running boolean;
    due boolean;
    callback_due boolean;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT (SELECT count(*) FROM calls c
                 WHERE c.direction = 'outbound'
                   AND c.status = ANY (active_statuses)
                   AND c.updated_at > now() - active_horizon),
               (SELECT EXISTS (SELECT 1 FROM campaigns c WHERE c.status = 'running')),
               (SELECT EXISTS (SELECT 1 FROM campaigns c
                                WHERE c.status = 'scheduled'
                                  AND CASE WHEN pg_input_is_valid(
                                                  c.schedule->>'start_at', 'timestamptz')
                                           THEN (c.schedule->>'start_at')::timestamptz <= now()
                                           ELSE false END)),
               (SELECT EXISTS (SELECT 1 FROM scheduled_callbacks s
                                WHERE (s.status = 'scheduled' AND s.requested_at <= now())
                                   OR s.status = 'dialing'))
          INTO live, running, due, callback_due;
        IF live > 0 OR running OR due OR callback_due THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            has_due_schedule := due;
            has_due_callback := callback_due;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""

# Verbatim from c7e4b19d3f52 — the downgrade target, kept whole rather than patched, so a
# rollback lands on the function that revision's tests describe.
_FUNCTION_SQL_V2 = f"""
CREATE FUNCTION {FUNCTION}(active_statuses text[], active_horizon interval)
RETURNS TABLE (
    scanned_tenant_id uuid,
    active_outbound integer,
    has_running_campaign boolean,
    has_due_schedule boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    entry_tenant text := current_setting('app.tenant_id', true);
    t uuid;
    live integer;
    running boolean;
    due boolean;
BEGIN
    FOR t IN SELECT DISTINCT r.tenant_id FROM engine_agent_routes r ORDER BY 1 LOOP
        PERFORM set_config('app.tenant_id', t::text, true);
        SELECT (SELECT count(*) FROM calls c
                 WHERE c.direction = 'outbound'
                   AND c.status = ANY (active_statuses)
                   AND c.updated_at > now() - active_horizon),
               (SELECT EXISTS (SELECT 1 FROM campaigns c WHERE c.status = 'running')),
               (SELECT EXISTS (SELECT 1 FROM campaigns c
                                WHERE c.status = 'scheduled'
                                  AND CASE WHEN pg_input_is_valid(
                                                  c.schedule->>'start_at', 'timestamptz')
                                           THEN (c.schedule->>'start_at')::timestamptz <= now()
                                           ELSE false END))
          INTO live, running, due;
        IF live > 0 OR running OR due THEN
            scanned_tenant_id := t;
            active_outbound := live;
            has_running_campaign := running;
            has_due_schedule := due;
            RETURN NEXT;
        END IF;
    END LOOP;
    PERFORM set_config('app.tenant_id', coalesce(entry_tenant, ''), true);
END;
$$
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.create_table(
        "scheduled_callbacks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # WHICH agent rings back. The one the caller was speaking to, resolved from the
        # execution by the booking worker — never taken from the tool payload, which is an
        # unauthenticated hint (D-31).
        sa.Column("agent_id", sa.UUID(), nullable=False),
        # The call the promise was made ON. Nullable and RESTRICT-free (`SET NULL`)
        # because the `calls` row may not exist yet at booking time and may be erased
        # later while the callback is still owed: the promise outlives the pointer.
        sa.Column("source_call_id", sa.UUID(), nullable=True),
        # The engine's own id for that conversation. NOT NULL — this is the identity, see
        # the module docstring.
        sa.Column("source_execution_id", sa.Text(), nullable=False),
        # The lead this belongs to, when the source call had one. Carried so the callback
        # shows on the lead's timeline and so the dial can pass `lead_id` to the one
        # outbound entry point.
        sa.Column("lead_id", sa.UUID(), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        # THE PROMISE, UTC (repo convention: timestamptz UTC in the DB, IST at the edge).
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        # When the caller asked. The upsert's ordering guard: two bookings in one
        # conversation land on the later word whichever job commits first.
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'scheduled'"), nullable=False
        ),
        # How many times a tick has claimed it. Bounded by the grace window rather than by
        # a max — see `callbacks/service.py`, and the livelock file it cites.
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # When a deferred callback may be claimed again. A SEPARATE column, and the reason
        # is a livelock caught while writing this table: the first draft pushed
        # `requested_at` forward on each transient refusal, which moved the promise itself
        # — so the two-hour staleness cutoff receded by five minutes every five minutes and
        # nothing could ever go stale. `requested_at` is what the caller was told and never
        # moves; this is bookkeeping.
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        # The gate's OWN rule name and OWN sentence for the last refusal. The rule is for
        # the metric and the runbook; the sentence is what the client reads.
        sa.Column("last_refusal_rule", sa.Text(), nullable=True),
        sa.Column("last_refusal_reason", sa.Text(), nullable=True),
        # The dial this became, once there was one.
        sa.Column("last_call_id", sa.UUID(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        # What the caller said about WHY, in the agent's words. Bounded at the boundary
        # (`callbacks/service.MAX_NOTE`), spoken back to the agent on the callback so the
        # dial arrives knowing what it is for.
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_scheduled_callbacks_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_scheduled_callbacks_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            name=op.f("fk_scheduled_callbacks_source_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_call_id"],
            ["calls.id"],
            name=op.f("fk_scheduled_callbacks_last_call_id_calls"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name=op.f("fk_scheduled_callbacks_lead_id_leads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_callbacks")),
        sa.CheckConstraint(
            f"status IN ({_STATUSES})", name=op.f("ck_scheduled_callbacks_status")
        ),
        # A settled row names its ending, and an unsettled one does not claim to have one.
        sa.CheckConstraint(
            "(status IN ('scheduled', 'dialing')) = (settled_at IS NULL)",
            name=op.f("ck_scheduled_callbacks_settled"),
        ),
    )
    op.create_index(
        op.f("ix_scheduled_callbacks_tenant_id"),
        "scheduled_callbacks",
        ["tenant_id"],
        unique=False,
    )
    # THE IDENTITY. One live promise per conversation, per tenant — the upsert key.
    op.create_index(
        "uq_scheduled_callbacks_execution",
        "scheduled_callbacks",
        ["tenant_id", "source_execution_id"],
        unique=True,
    )
    # What the tick claims from, and what `dispatch_scan()`'s new sub-select reads.
    op.create_index(
        DUE_INDEX,
        "scheduled_callbacks",
        ["tenant_id", "requested_at", "next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    # What the dashboard lists by, and what the DNC/cancel sweep finds a number's live
    # promises with.
    op.create_index(
        "ix_scheduled_callbacks_phone",
        "scheduled_callbacks",
        ["tenant_id", "phone_e164"],
        unique=False,
        postgresql_where=sa.text("status IN ('scheduled', 'dialing')"),
    )
    op.execute("ALTER TABLE scheduled_callbacks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE scheduled_callbacks FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    # The scan gains its fifth column. DROP + CREATE rather than CREATE OR REPLACE:
    # Postgres refuses to replace a function whose OUT parameters change.
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V3)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}(text[], interval)")
    op.execute(_FUNCTION_SQL_V2)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON scheduled_callbacks")
    op.drop_index("ix_scheduled_callbacks_phone", table_name="scheduled_callbacks")
    op.drop_index(DUE_INDEX, table_name="scheduled_callbacks")
    op.drop_index("uq_scheduled_callbacks_execution", table_name="scheduled_callbacks")
    op.drop_index(op.f("ix_scheduled_callbacks_tenant_id"), table_name="scheduled_callbacks")
    # Losing the promises on the way down is the honest ending rather than an unfortunate
    # one: a callback is a future intention, not a record of something that happened (hard
    # rule 4's concern), and a downgrade that kept the rows would leave a tick that no
    # longer exists as the only thing that could have honoured them.
    op.drop_table("scheduled_callbacks")
