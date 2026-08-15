"""a dashboard assist is metered by its own key, on a row a call-shaped index cannot see

Revision ID: e1a7c93d5b02
Revises: d4b8e1c73f05
Create Date: 2026-08-15 19:20:00.000000

D-127's G-3 meters dashboard AI per tenant into `usage_events`. This revision is the
schema that makes such a row *addressable*, *unique* and *countable* — and it exists
because the metering guarantee `b8d3f47c2a19` bought does not reach these rows at all.

--------------------------------------------------------------------------------
THE THREE WAYS A DASHBOARD-AI ROW ESCAPED THE EXISTING KEY
--------------------------------------------------------------------------------

`ux_usage_events_tenant_call_unit`, read at `b8d3f47c2a19:185` and confirmed against
`pg_indexes` on a live database before this file was written:

    ON usage_events (tenant_id, call_id, unit_type)
     WHERE call_id IS NOT NULL
       AND unit_type IN ('telephony_s','platform_min','stt_s','tts_chars','llm_tok_out')
       AND created_at >= '2026-08-15 10:14:00+00:00'

1. **`call_id IS NOT NULL` is an explicit PREDICATE.** A dashboard assist has no call,
   so the row is not in the index AT ALL. This is worth separating from the familiar
   "NULLs do not collide in a btree" fact, because the remedies differ: a NULL inside an
   index can be reached with `NULLS NOT DISTINCT` (pg15+), while a row excluded by
   predicate can only ever be covered by a DIFFERENT index. Hence a second index rather
   than an alteration of the first.
2. **The unit list omits `llm_tok_in`** — and that column is not the answer anyway: it
   has no writer anywhere in the tree, which is a live finding PLAN Part 18 owns. Giving
   it one here would erase the finding without fixing it.
3. **`llm_tok_out` already means something else.** `apps/workers/pipeline.py:1201`
   writes it as `qty = 1` — *one call's LLM leg* — priced at the whole leg cost, because
   the engine bills legs with no token count (TRD §5), and `billing/service.py:770`
   treats it as a cost input a client never sees. Metering real tokens there would put
   two units in one column.

--------------------------------------------------------------------------------
WHAT THIS REVISION ADDS
--------------------------------------------------------------------------------

* **`usage_events.ref`** (nullable text) — the idempotency key for a row that has no
  call to be keyed by. The realistic duplicate here is a DOUBLE-CLICK on a console
  button, not an ARQ retry, so the key is minted per REQUEST by the caller.
* **Two new unit types**, `ai_assist_ktok_in` / `ai_assist_ktok_out`, added to
  `ck_usage_events_unit_type_enum`. `ktok` — thousands of tokens — because
  `unit_cost_paid` is NUMERIC(12,4) and a per-token price of ~₹0.000008 stores as
  0.0000; the argument in full is on `billing/models.py::AI_ASSIST_UNIT_TYPES`.
* **`ux_usage_events_tenant_unit_ref`** — `(tenant_id, unit_type, ref)` partial on
  `ref IS NOT NULL AND call_id IS NULL`.
* **`platform_ai_spend`** — the platform's own monthly total, because a cross-tenant sum
  of an RLS'd table is unaskable in app code (`billing/models.py::PlatformAiSpend`).

--------------------------------------------------------------------------------
WHY THE TWO INDEXES ARE DISJOINT RATHER THAN MERELY DIFFERENT
--------------------------------------------------------------------------------

    old:  WHERE call_id IS NOT NULL  AND ...
    new:  WHERE call_id IS NULL      AND ref IS NOT NULL

`call_id IS NOT NULL` and `call_id IS NULL` partition every row, so **no row is in both
indexes**, neither can shadow the other, and neither can be widened later without the
conflict being visible in one line. The alternative considered and rejected was one
index over `(tenant_id, COALESCE(call_id::text, ref), unit_type)`: it collapses two
namespaces into one column — the exact defect `ux_credit_ledger_tenant_reason_ref`
carries `reason` in its key to avoid — and it makes a call id and a request key
collidable by construction.

**No grandfather line here, and that is a property rather than an omission.** The
`created_at >=` clause on the older index exists because hard rule 4 forbids deleting the
duplicate rows a pre-fix race left behind, so a full index could never build. `ref` is
being created by THIS statement, so no existing row can satisfy `ref IS NOT NULL`: the
predicate matches zero rows on every database in existence and there is no residue to
grandfather. A cutoff would have been a permanent hole for nothing.

**`ON CONFLICT DO NOTHING` at the writer, not `DO UPDATE`.** `usage_events` is in
`db/registry.APPEND_ONLY_TABLES`, so `DO UPDATE` fires `calevate_forbid_mutation` and the
transaction dies. And `DO NOTHING` must repeat the predicate above VERBATIM as an
`index_predicate` or Postgres will not infer a partial index at all
(postgresql.org/docs/16/sql-insert.html, "unique index inference" — READ AT SOURCE; the
same citation `b8d3f47c2a19` leaves for exactly this future writer).
`billing/ai_quota.py::_INSERT_USAGE` is that writer and
`tests/ai_quota_test.py::test_the_writer_infers_the_partial_index_rather_than_raising`
fails if the predicate ever drifts from this file.

--------------------------------------------------------------------------------
LOCKING
--------------------------------------------------------------------------------

The index is built CONCURRENTLY for `b8d3f47c2a19`'s reason: `usage_events` is written
on every completed call, and a plain `CREATE UNIQUE INDEX` holds a SHARE lock for the
whole build. CONCURRENTLY cannot run inside a transaction, hence `autocommit_block()`,
and `lock_timeout` is set with plain `SET` (there is no transaction for `SET LOCAL` to
scope to) at 30s rather than 3s — CONCURRENTLY waits on concurrent transactions as well
as on the table lock.

The column, the CHECK and the new table go FIRST, inside the migration's transaction,
because the index cannot be built on a column that does not exist yet. The consequence a
reviewer should have in front of them: **if the CONCURRENTLY build fails, those three
are already committed and `alembic_version` has not advanced.** Recovery is exactly what
`downgrade()` issues first — `DROP INDEX IF EXISTS ux_usage_events_tenant_unit_ref` —
followed by `alembic upgrade head`, which re-runs the whole revision; the column add and
the CHECK swap are written so a re-run of them is the failure a person should see
(`column already exists`) rather than a silent half-state.

**RLS.** No new TENANT table, so no new policy. `usage_events` keeps its FORCEd
`tenant_isolation` policy and the new index inherits the table's protection — index
builds are not RLS-filtered, so this revision issues no DML and needs no `NO FORCE`
bracket. `platform_ai_spend` carries no `tenant_id` at all: it is platform state, the
shape `platform_state` and `platform_settings` already have, and `check_rls_coverage`
judges it by the same rule that passes those. The cross-tenant zero-rows check hard rule
1 requires of a change touching a tenant-scoped table is
`tests/ai_quota_test.py::test_two_tenants_may_hold_the_same_ref_without_colliding`, and
what it proves is that the new index is not a side channel: `tenant_id` leads the key.

**Downgrade** is reversible in the sense hard rule 8 means, and it REFUSES rather than
destroys. Narrowing the CHECK back is a real narrowing and dropping `ref` would delete
idempotency keys off an append-only ledger, so the downgrade counts the rows that would
be harmed and raises BEFORE it drops anything — the shape `d7b1c48a2e93` established.
Both directions were run end to end (upgrade → downgrade → upgrade) against a database
built from `base` before this file was committed, because a previous wave shipped a
downgrade that dropped a trigger and not its function and failed `DuplicateFunction` on
re-upgrade. There is no function and no trigger here to orphan.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a7c93d5b02"
down_revision: str | None = "d4b8e1c73f05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_usage_events_unit_type_enum"
INDEX = "ux_usage_events_tenant_unit_ref"
SPEND_TABLE = "platform_ai_spend"

# The unit types as they stand at THIS revision, frozen as literals. A migration is a
# historical fact and must not change meaning because a constant elsewhere was edited
# later — `b8d3f47c2a19` freezes its five for the same reason, and
# `tests/ai_quota_test.py` holds the live constraint equal to
# `billing/models.py::UNIT_TYPES` so drift fails the suite instead of a client's insert.
ORIGINAL_UNITS = (
    "telephony_s",
    "stt_s",
    "tts_chars",
    "llm_tok_in",
    "llm_tok_out",
    "platform_min",
    "number_rental",
    "other",
)
AI_UNITS = ("ai_assist_ktok_in", "ai_assist_ktok_out")


def _enum(units: Sequence[str]) -> str:
    return "unit_type IN (" + ", ".join(f"'{unit}'" for unit in units) + ")"


ORIGINAL_CHECK = _enum(ORIGINAL_UNITS)
WIDENED_CHECK = _enum((*ORIGINAL_UNITS, *AI_UNITS))

# THE PREDICATE, and it is spelled once. `billing/ai_quota.py` repeats it verbatim as an
# `index_predicate`; the test named in the docstring reads both and fails on a drift of
# one character, because a predicate that ALMOST matches does not infer the index — it
# raises `there is no unique or exclusion constraint matching the ON CONFLICT
# specification`, which is a 500 on a button a client just pressed.
INDEX_PREDICATE = "ref IS NOT NULL AND call_id IS NULL"

CREATE_INDEX = (
    f"CREATE UNIQUE INDEX CONCURRENTLY {INDEX} "
    "ON usage_events (tenant_id, unit_type, ref) "
    f"WHERE {INDEX_PREDICATE}"
)

DROP_INDEX = f"DROP INDEX IF EXISTS {INDEX}"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    op.add_column("usage_events", sa.Column("ref", sa.Text(), nullable=True))

    # Drop and add is the only route: Postgres has no `ALTER TABLE ... ALTER CONSTRAINT`
    # for a CHECK's expression. Safe in the widening direction — the new predicate is
    # strictly weaker, so no existing row can violate it and there is nothing for
    # `NOT VALID` + `VALIDATE` to buy (the argument `d7b1c48a2e93` makes in full).
    op.drop_constraint(op.f(CONSTRAINT), "usage_events", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "usage_events", WIDENED_CHECK)

    op.create_table(
        SPEND_TABLE,
        # IST billing month, 'YYYY-MM' — the same cut `billing/service._IST_MONTH` makes
        # on the per-tenant rows, so the platform total and the tenant totals close on
        # one instant.
        sa.Column("month", sa.Text(), nullable=False),
        sa.Column("spend_inr", sa.Numeric(12, 4), server_default=sa.text("0"), nullable=False),
        sa.Column("requests", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("month", name=op.f("pk_platform_ai_spend")),
        # A counter that can go backwards is a brake that can be released by a bug.
        sa.CheckConstraint(
            "spend_inr >= 0 AND requests >= 0", name=op.f("ck_platform_ai_spend_non_negative")
        ),
    )

    # Outside the migration's transaction: CONCURRENTLY cannot run inside one, and the
    # alternative — a SHARE lock held for the whole build — blocks every metering write.
    with op.get_context().autocommit_block():
        # Plain SET, not SET LOCAL: there is no transaction here for LOCAL to scope to.
        op.execute("SET lock_timeout = '30s'")
        op.execute(CREATE_INDEX)


def downgrade() -> None:
    bind = op.get_bind()
    # COUNTED BEFORE ANYTHING IS DROPPED, so a refused downgrade leaves the schema
    # exactly as it found it rather than half-narrowed. Both halves are real losses: a
    # narrowed CHECK would reject the AI rows Postgres is about to re-validate, and
    # dropping `ref` would delete idempotency keys off a ledger hard rule 4 forbids
    # editing — the row would survive and the key that proves it was written once would
    # not.
    stranded = bind.execute(
        sa.text(
            "SELECT count(*) FILTER (WHERE unit_type = ANY(:units)), "
            "       count(*) FILTER (WHERE ref IS NOT NULL) "
            "FROM usage_events"
        ),
        {"units": list(AI_UNITS)},
    ).one()
    if stranded[0] or stranded[1]:
        raise RuntimeError(
            f"{stranded[0]} usage_events row(s) carry a dashboard-AI unit type and "
            f"{stranded[1]} carry an idempotency ref. Downgrading past {revision} would "
            "either reject them or silently drop the key that makes them idempotent. "
            "Export or compensate for those rows first (hard rule 4 forbids deleting "
            "them), then re-run this downgrade."
        )

    # UNCONDITIONAL and IF EXISTS, so this also cleans up an INVALID index left behind by
    # a CONCURRENTLY build that failed on a database whose alembic_version never advanced
    # — which is the documented recovery for exactly that state.
    op.execute(DROP_INDEX)
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_table(SPEND_TABLE)
    op.drop_constraint(op.f(CONSTRAINT), "usage_events", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "usage_events", ORIGINAL_CHECK)
    op.drop_column("usage_events", "ref")
