"""the owned-runtime LLM unit types, and a home for a leg we could not price

Revision ID: a3f1c6e82d47
Revises: d7c2f4a91b83
Create Date: 2026-09-15 00:00:00.000000

WHAT THIS IS FOR
----------------
`docs/PIPECAT-MIGRATION.md` §1.3 and §6 step 11's last sentence: the worker's container
bootstrap, whose sink writes `calls`, `transcript_turns` and `usage_events` while the call
is still happening. Two things in the schema stood between that writer and a row it could
legally insert, and both are here.

1. `usage_events` ADMITS `llm_ktok_in` / `llm_ktok_out`
-------------------------------------------------------
`voice_worker/meter.py` has spelled these two unit tokens since it was written, with a
comment saying so out loud: *"`llm_ktok_in` / `llm_ktok_out` are REQUESTED, not assumed —
the enum is rendered verbatim into `ck_usage_events_unit_type_enum`, so until that
migration lands an insert of these rows is refused by the database rather than accepted
wrongly."* This is that migration. The refusal was the correct failure and it is now
answered rather than worked around: nothing was folded onto `llm_tok_in`/`llm_tok_out`,
which mean a different thing (the RENTED engine reports a leg CHARGE with no token count,
so those rows carry `qty = 1` and the whole leg — TRD §5).

**PER THOUSAND, and the `k` is a money decision, not a naming one.** `unit_cost_paid` is
NUMERIC(12,4), so the smallest non-zero price per unit of `qty` is ₹0.0001. `gpt-4o-mini`
input is about ₹0.0000144 a token, which stores as `0.0000` — the input leg of every call
would meter as exactly free. `billing/models.AI_ASSIST_UNIT_TYPES` and migration
`f4b90c1d7e26` (`tts_kchars`) make the identical argument at the identical column; this is
the third leg to meet it and it takes the same answer rather than a fourth one.

A UNIQUE INDEX comes with them, partial on the two new types, because the writer's
`ON CONFLICT DO NOTHING` needs something to infer and because a re-settlement must converge
on one row per leg rather than append a second. It carries **no `created_at` floor**, unlike
`ux_usage_events_tenant_call_unit`: that floor exists to exempt rows written before the
index, and these two unit types have no rows at all — the CHECK constraint above made them
unwritable until this statement ran.

2. `call_metering_refusals` — A LEG WE COULD NOT PRICE, RECORDED
-----------------------------------------------------------------
Hard rule 7 says a `usage_event` carries OUR real cost; §1.3 says five legs are now metered
independently and that *"a leg we cannot price raises... that must not be softened by
defaulting any leg to zero"*. Both are satisfied by refusing — and a refusal with nowhere
to go is a log line in a container that will be gone by morning.

So the refusal gets a row. `voice_worker/meter.py::LegNotMeterableError` already carries
exactly the four fields an operator acts on (`leg`, `code`, `detail`, `remediation`); this
table is those four, plus the call and the instant. `admin/health.py::calls_unmetered`
already stops the board for a completed call with no usage rows; this is what says WHICH
leg and WHAT to do.

**Append-only** (`db/registry.APPEND_ONLY_TABLES`), with the blanket
`calevate_forbid_mutation` trigger and no exception: the row is evidence about one
settlement attempt at one instant, and a later attempt that succeeds writes `usage_events`
rows rather than editing the record of the one that did not.

**Tenant-isolated** (hard rule 1), FORCEd, with the strict `tenant_id = <guc>` form and NO
global-read exemption. It is asked per call and therefore per tenant; there is no
cross-tenant question this table answers, and the audit that found three policies admitting
`OR <guc> IS NULL` (migration `b8e2d47f0c19`) is the reason that shape is not reached for
here even though an ops-console reader would have been convenient.

**No PII, guaranteed by the schema rather than by the writer's manners** (hard rule 6):
every column is an id, a machine code, or prose this repository authored. `call_id` is
`ON DELETE RESTRICT`, matching `usage_events` — there is nothing here for an erasure to
reach, because there is no column a subject's data could have been put in.

LOCKING
-------
One CHECK constraint dropped and re-created on `usage_events` — ACCESS EXCLUSIVE, and it
VALIDATES against every existing row. The new list is a strict SUPERSET of the old one so
no row can fail, but the scan is real, which is why `lock_timeout` is set: on a large table
the statement must fail fast and be re-run in a quiet window rather than queue in front of
the meter. The new table is `CREATE TABLE` on a table nothing references yet; its FK to
`calls` is added inline rather than NOT VALID because the table is empty at creation, so
there is nothing to validate.

The new unique index is created NOT concurrently, deliberately: `CREATE INDEX CONCURRENTLY`
cannot run inside a transaction block and Alembic wraps a migration in one, and the index is
PARTIAL on two unit types that no row can currently hold — so the build scans a predicate
that matches nothing and takes the same lock the CHECK re-creation above already took.

DOWNGRADE
---------
Drops the table and re-narrows the CHECK. The CHECK half REFUSES rather than stranding
rows (`f4b90c1d7e26`'s pattern): silently deleting metered cost rows to make a constraint
fit is how a month stops adding up. Dropping the refusals table loses the record of what
was unmetered and nothing else — no money moves, because the whole point of those rows is
that no money was ever recorded for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f1c6e82d47"
down_revision: str | None = "d7c2f4a91b83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `billing/models.UNIT_TYPES`, as every migration that
# has touched this constraint does: a migration states what the schema was and became at
# THIS revision, and importing today's constant would make an old revision re-render itself
# against a list that has moved since.
_BEFORE = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "tts_kchars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
)
_AFTER = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "tts_kchars",
    "llm_tok_in",
    "llm_tok_out",
    "llm_ktok_in",
    "llm_ktok_out",
    "platform_min",
    "number_rental",
    "other",
    "ai_assist_ktok_in",
    "ai_assist_ktok_out",
)

_KTOK_INDEX = "ux_usage_events_tenant_call_ktok"
_KTOK_PREDICATE = (
    "call_id IS NOT NULL AND unit_type IN ('llm_ktok_in', 'llm_ktok_out')"
)

_TABLE = "call_metering_refusals"

# DATA-MODEL §1 verbatim. NULLIF: a pooled connection that once had the GUC returns '' when
# unset, and ''::uuid ERRORs instead of failing closed to zero rows.
_POLICY = (
    f"CREATE POLICY tenant_isolation ON {_TABLE} USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def _recheck(units: tuple[str, ...]) -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE usage_events DROP CONSTRAINT ck_usage_events_unit_type_enum")
    op.execute(
        "ALTER TABLE usage_events ADD CONSTRAINT ck_usage_events_unit_type_enum "
        f"CHECK (unit_type IN {units!r})"
    )


def upgrade() -> None:
    _recheck(_AFTER)
    op.execute(
        f"CREATE UNIQUE INDEX {_KTOK_INDEX} ON usage_events "
        f"(tenant_id, call_id, unit_type) WHERE {_KTOK_PREDICATE}"
    )

    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("leg", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_metering_refusals")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f("fk_call_metering_refusals_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        # RESTRICT, exactly as `usage_events.call_id` is, and for the reason
        # `scripts/check_ledger_immutability.py::_cascade_hits` enforces: a CASCADE is a
        # DELETE nobody wrote, and an append-only table that a cascade can empty is not
        # append-only. This repository does not delete `calls` rows — a DPDP erasure
        # redacts and anonymises them — so RESTRICT blocks nothing that happens, and the
        # day something needs to delete a call it will have to say what becomes of this
        # evidence instead of finding out afterwards.
        sa.ForeignKeyConstraint(
            ["call_id"],
            ["calls.id"],
            name=op.f("fk_call_metering_refusals_call_id_calls"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_call_metering_refusals_tenant_id"), _TABLE, ["tenant_id"], unique=False
    )
    # "What is unmetered, newest first" — the ops question, and the only one this table is
    # read for.
    op.create_index(
        "ix_call_metering_refusals_tenant_occurred",
        _TABLE,
        ["tenant_id", sa.text("occurred_at DESC")],
    )

    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(_POLICY)

    op.execute(
        f"CREATE TRIGGER {_TABLE}_append_only "
        f"BEFORE UPDATE OR DELETE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {_TABLE}_forbid_truncate "
        f"BEFORE TRUNCATE ON {_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    # ALWAYS: without it the trigger is disabled for a session with `session_replication_role
    # = replica`, which is what a restore runs as — and an append-only guarantee that a
    # restore can step around is not one. Every other ledger in this repo is armed the same
    # way.
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_append_only")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ALWAYS TRIGGER {_TABLE}_forbid_truncate")


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
    op.execute(f"DROP INDEX IF EXISTS {_KTOK_INDEX}")
    _recheck(_BEFORE)
