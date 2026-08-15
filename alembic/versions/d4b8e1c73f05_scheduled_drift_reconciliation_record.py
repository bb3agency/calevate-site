"""a place to keep what the reconciliation sweep found (D-123)

Revision ID: d4b8e1c73f05
Revises: f3a71c9e26b4
Create Date: 2026-08-15 14:30:00.000000

Three columns on `engine_agent_routes`, which is the row that already stands for ONE
VENDOR-SIDE AGENT OBJECT. D-121 built `engine_drift_for()` and
`GET /v1/agents/{agent_id}/engine-state` and nothing ran them on a schedule, so a drift
was found by whoever thought to look at one agent's screen. This revision is the place
the periodic sweep writes its answer down.

--------------------------------------------------------------------------------
WHY ON `engine_agent_routes` AND NOT ON `agents`
--------------------------------------------------------------------------------

`agents` is the obvious home and it is the wrong one, for a reason that is structural
rather than aesthetic. `agents` is FORCE-RLS'd (hard rule 1), so:

* the SWEEP would have to open a tenant session per tenant to order a global work queue
  by staleness — i.e. it could not order one at all, only N of them, and a per-tenant
  round-robin is not the same bound as a global one;
* the OPS CONSOLE reads `GET /v1/ops/platform` on a global session and would see zero
  rows for every tenant, which is exactly the defect `report_stalled_pipeline` was fixed
  for (an alarm that had never once been able to fire).

The alternative to this table is an RLS EXEMPTION on `agents`, and that trade is not
close: `engine_agent_routes` is already the deliberately un-RLS'd bridge (its reason is
in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`), and it is already keyed on exactly the thing
being described — `(engine, engine_agent_ref)`, one vendor agent object. Recording "what
is the vendor holding for this object" against the row that IS that object is where it
belongs, and it keeps `agents` FORCE-RLS'd rather than punching the first hole in it.

**NOTHING TENANT-PRIVATE CROSSES.** The exemption's stated bound is "carries no PII and
no call data", and these three columns keep it: a verdict from a fixed five-value
vocabulary and two timestamps. No prompt body, no disclosure line, no detail sentence —
the operator-readable sentence stays on the per-agent endpoint, which is tenant-scoped.
That is a hard-rule-6 boundary as much as a hard-rule-1 one, and it is why `drift_detail`
is NOT a column here.

--------------------------------------------------------------------------------
THE THREE COLUMNS
--------------------------------------------------------------------------------

    drift_state        the verdict of the last sweep, or NULL for "never swept".
                       NULL is a distinct fact from every verdict, the argument
                       `live_verify_state`'s `unverified` value makes: a row nobody has
                       looked at must not read as a row we looked at and liked.
    drift_checked_at   when that verdict was produced. ALSO the sweep's work queue
                       ordering — oldest first, NULLs first — so coverage is a property
                       of the ordering rather than of a cursor somebody has to maintain.
    drift_detected_at  when the CURRENT run of not-in-sync began, NULL whenever the last
                       verdict was `applied`. Not derivable from the other two: `state`
                       says an agent is wrong now and `checked_at` says when we last
                       looked, and neither answers "for how long" — which is the number
                       that separates a publish that raced a sweep from a vendor-console
                       edit nobody has noticed for a week. Same role as
                       `DeadLetterQueue.oldest_created_at`, and it earns its column for
                       the same reason: age is what turns a count into a decision.

--------------------------------------------------------------------------------
THE FIVE VALUES
--------------------------------------------------------------------------------

    applied         read back; the engine holds what our row says it published.
    not_applied     read back; a property PROVABLY differs. THE DRIFT.
    unreadable      the engine answered and the adapter could not find the property.
    unreachable     the read itself failed.
    not_published   our row carries no `engine_agent_ref` — nothing to compare.

The first four are `verification.VerifyState` exactly; the fifth is `EngineDrift`'s extra
member for the never-published case. Unlike `agents.live_verify_state`, `not_applied` IS
storable here and must be: reconciliation is a READ, so it has no transaction to refuse
and roll back — recording the divergence IS its entire output. The CHECK exists for the
same reason it does there: an operator's screen renders this word.

--------------------------------------------------------------------------------
THE PARTIAL INDEX
--------------------------------------------------------------------------------

`ix_engine_agent_routes_drift_sweep (engine, drift_checked_at NULLS FIRST) WHERE active`
serves the sweep's one query and nothing else. Partial on `active` because a deactivated
route is an agent nobody publishes any more and a vendor round trip spent on it is a
round trip stolen from a live one. `engine` leads because the sweep only ever asks about
the CONFIGURED engine — a route left over from another vendor would be compared against
the wrong platform's answer.

`NULLS FIRST` is written into the index because it is written into the query: a never-
checked row is the most urgent one there is, and PostgreSQL's default for ASC is NULLS
LAST, so an index without it would leave the sweep's ORDER BY unservable.

--------------------------------------------------------------------------------
LOCKING, RLS AND DOWNGRADE
--------------------------------------------------------------------------------

Three nullable columns with no default: catalog-only, no rewrite, no scan. ACCESS
EXCLUSIVE for the length of the catalog update, bounded by `lock_timeout` (hard rule 8).
The index is built plainly rather than CONCURRENTLY: `engine_agent_routes` holds one row
per published agent — tens, not millions — and CONCURRENTLY cannot run inside alembic's
transaction, which would trade a millisecond of lock for a migration that can leave an
INVALID index behind on failure.

No RLS work: `engine_agent_routes` is a listed, reasoned exemption and columns are not
separate security objects.

DOWNGRADE drops the index, the CHECK and the three columns — everything this revision
created and nothing else. What is lost is only what they hold: the sweep's record. The
per-agent on-demand read (`GET /v1/agents/{agent_id}/engine-state`) is untouched by
either direction, so a downgrade returns the system to D-121's on-demand-only answer
rather than to no answer. Nothing is two-step-deprecated because nothing is removed
(hard rule 8), and the downgrade drops the CHECK BY NAME before the columns it constrains
so a re-upgrade cannot meet a leftover object of its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b8e1c73f05"
down_revision: str | None = "f3a71c9e26b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "engine_agent_routes"
CHECK_NAME = "ck_engine_agent_routes_drift_state"
INDEX_NAME = "ix_engine_agent_routes_drift_sweep"
# Written once and rendered into the CHECK rather than spelled a second time in SQL —
# a migration whose constant and whose constraint can disagree documents a schema it did
# not create. `agents/reconciliation.py::DRIFT_STATES` is the application-side twin and
# `tests/engine_drift_reconciliation_test.py` asserts the two sets are equal.
STATES = ("applied", "not_applied", "unreadable", "unreachable", "not_published")
CHECK_SQL = "drift_state IS NULL OR drift_state IN (" + ", ".join(f"'{s}'" for s in STATES) + ")"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("drift_state", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("drift_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("drift_detected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, CHECK_SQL)
    op.execute(
        f"CREATE INDEX {INDEX_NAME} ON {TABLE} "
        "(engine, drift_checked_at NULLS FIRST) WHERE active"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.drop_column(TABLE, "drift_detected_at")
    op.drop_column(TABLE, "drift_checked_at")
    op.drop_column(TABLE, "drift_state")
