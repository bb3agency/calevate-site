"""where the KB drift sweep writes its answer (D-158)

Revision ID: a7c31e05b8d4
Revises: f8c1d47a90e3
Create Date: 2026-08-16 12:10:00.000000

Three more columns on `engine_agent_routes`, exactly parallel to `d4b8e1c73f05`'s and for
exactly its reasons. That revision gave the AGENT sweep a place to write what the vendor
was observed to be running; this one gives the KNOWLEDGE sweep a place to write what the
vendor was observed to be HOLDING. `kb/service._reconcile_engine_state` asks that question
only at publish time, and a knowledge base can go months between publishes — so a source
edited in Bolna's own dashboard, or a publish that committed at the vendor and rolled back
on our side, stayed invisible for exactly as long as nobody published.

--------------------------------------------------------------------------------
WHY HERE, AND WHY NOT ON `kb_sources`
--------------------------------------------------------------------------------

`kb_sources` is the obvious home and it is the wrong one twice over.

* **The unit of observation is the AGENT, not the source.** One `list_kb(agent_ref)` round
  trip answers for every source that agent holds, and the two divergences that matter —
  a handle the engine holds that no row of ours names, and a handle we recorded that the
  engine no longer lists — are both properties of the SET. Neither can be written against
  a single `kb_sources` row: the first has no row of ours to write it on at all.
* **`kb_sources` is FORCE-RLS'd** (hard rule 1), so the sweep could not order a global
  work queue by staleness from it, and `GET /v1/ops/platform` — a global session — would
  read zero rows for every tenant. That is the same structural argument `d4b8e1c73f05`
  made against putting the agent verdict on `agents`, and the same conclusion follows:
  record it against the row that already STANDS FOR one vendor-side agent object.

**NOTHING TENANT-PRIVATE CROSSES**, which is the bound the exemption in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` states. A verdict from a fixed six-value
vocabulary and two timestamps. No source name, no chunk text, no engine handle — a
`rag_id` is a vendor-issued opaque id and still not needed here, because the operator-
readable detail belongs on a tenant-scoped surface, not on a globally readable table.

--------------------------------------------------------------------------------
WHY NOT REUSE `drift_state`
--------------------------------------------------------------------------------

Because `drift_checked_at` is not merely a timestamp, it is the AGENT sweep's work queue:
writing it moves a row to the back of that queue. Two sweeps sharing one cursor would
each keep pushing the other's unread rows out of reach, and a platform whose agents were
swept every half hour would have its knowledge swept whenever the arithmetic happened to
line up. The two questions also have different verdicts, different cadences and different
alarms. Separate columns, separate index, separate queue.

--------------------------------------------------------------------------------
THE SIX VALUES
--------------------------------------------------------------------------------

    in_sync       the engine's handles for this agent are exactly the ones we recorded.
    unaccounted   the engine holds at least one handle NO row of ours names. The
                  dangerous direction: the agent can answer callers from text no human
                  approved, and a publish would stack a second copy on top of it (which
                  is the refusal `kb_engine_out_of_sync` already raises at publish time).
    missing       every handle the engine holds is accounted for, and at least one handle
                  we recorded is absent from its listing. The agent knows LESS than was
                  approved — it answers "I don't know" where it should quote a price.
    divergent     both at once. Kept distinct rather than collapsed into the worse of the
                  two, because the remediations differ and an operator handed only half
                  of them fixes only half of it.
    unreadable    the listing came back EMPTY for an agent we believe holds knowledge, and
                  nothing else in the tick proved the vendor's listing attributes rows to
                  agents at all. See `kb/reconciliation.classify_kb_drift` — this is pilot
                  gate 8's `kb_list_carries_agent_linkage`, still open, and filing it as
                  `missing` would put a fleet-wide false alarm on a schedule.
    unreachable   the read itself failed.

The first four are evidence; the last two are "we could not tell" and are counted apart,
the doctrine `agents/verification.py` established and `DRIFT_STATES_OUT_OF_SYNC` carries.
The CHECK exists for the same reason it does on `drift_state`: an operator's screen
renders this word, and a verdict the application can produce and the database rejects is
a sweep that starts failing every write at 00:23 with nothing on any screen to explain it.

--------------------------------------------------------------------------------
THE PARTIAL INDEX
--------------------------------------------------------------------------------

`ix_engine_agent_routes_kb_drift_sweep (engine, kb_drift_checked_at NULLS FIRST) WHERE
active` serves the KB sweep's one query and nothing else, and every clause of it is
`d4b8e1c73f05`'s: partial on `active` because a deactivated route is an agent nobody
publishes to any more; `engine` leads because the sweep only ever asks about the
CONFIGURED engine; `NULLS FIRST` is written into the index because it is written into the
query, and PostgreSQL's default for ASC is NULLS LAST, so an index without it would leave
the ORDER BY unservable.

--------------------------------------------------------------------------------
LOCKING, RLS AND DOWNGRADE
--------------------------------------------------------------------------------

Three nullable columns with no default: catalog-only, no rewrite, no scan. ACCESS
EXCLUSIVE for the length of the catalog update, bounded by `lock_timeout` (hard rule 8).
The index is built plainly rather than CONCURRENTLY, for `d4b8e1c73f05`'s reason: this
table holds one row per published agent — tens, not millions — and CONCURRENTLY cannot
run inside alembic's transaction, which would trade a millisecond of lock for a migration
that can leave an INVALID index behind on failure.

No RLS work. `engine_agent_routes` already carries the asymmetric pair `c4b70e928a1f`
installed (global SELECT, tenant-or-ops-isolated writes) and columns are not separate
security objects, so these three inherit it: a tenant session cannot stamp another
tenant's route, and the untenanted sweep can stamp any of them. `rls_sweep_test`'s
behavioural pin covers the write half without amendment.

DOWNGRADE drops the index, the CHECK and the three columns — everything this revision
created and nothing else. What is lost is only the sweep's record; the publish-time check
(`kb/service._reconcile_engine_state`) is untouched by either direction, so a downgrade
returns the system to "we find out at the next publish" rather than to no answer at all.
Nothing is two-step-deprecated because nothing is removed (hard rule 8), and the CHECK is
dropped BY NAME before the columns it constrains so a re-upgrade cannot meet a leftover
object of its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7c31e05b8d4"
down_revision: str | None = "f8c1d47a90e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "engine_agent_routes"
CHECK_NAME = "ck_engine_agent_routes_kb_drift_state"
INDEX_NAME = "ix_engine_agent_routes_kb_drift_sweep"
# Written once and rendered into the CHECK rather than spelled a second time in SQL — a
# migration whose constant and whose constraint can disagree documents a schema it did not
# create. `kb/reconciliation.py::KB_DRIFT_STATES` is the application-side twin and
# `tests/kb_drift_reconciliation_test.py` asserts the two sets against the LIVE catalog.
STATES = ("in_sync", "unaccounted", "missing", "divergent", "unreadable", "unreachable")
CHECK_SQL = (
    "kb_drift_state IS NULL OR kb_drift_state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("kb_drift_state", sa.Text(), nullable=True))
    op.add_column(
        TABLE, sa.Column("kb_drift_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        TABLE, sa.Column("kb_drift_detected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, CHECK_SQL)
    op.execute(
        f"CREATE INDEX {INDEX_NAME} ON {TABLE} "
        "(engine, kb_drift_checked_at NULLS FIRST) WHERE active"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.drop_column(TABLE, "kb_drift_detected_at")
    op.drop_column(TABLE, "kb_drift_checked_at")
    op.drop_column(TABLE, "kb_drift_state")
