"""the drift sweep names the compliance divergence separately (D-562)

Revision ID: e91d3c47ab58
Revises: c72b9e40af15
Create Date: 2026-09-10 13:20:00.000000

ONE VALUE ADDED to `ck_engine_agent_routes_drift_state`, and nothing else changes.

--------------------------------------------------------------------------------
WHY
--------------------------------------------------------------------------------

D-123 gave the half-hourly sweep somewhere to write what it found and D-121 gave it the
read. Between them they PROVE, twice an hour, that a live agent is running a prompt with
no truthful-answer directive in it — the rule hard rule 5 says an agent may never be
without, the one a caller relies on when they ask outright whether they are talking to a
machine. What neither of them did is stop that agent. The verdict was `not_applied`, the
alert was a count and an engine name, and nothing on any call path read the column: the
agent kept answering and kept dialling until a human noticed the email.

Enforcing on `not_applied` itself is not the fix and would be a worse product. That value
covers every provable divergence there is, including a client's script coming back with
different whitespace — and stopping a paying client's calling over that is a bigger
failure than the one being closed. So the sweep now records WHICH divergence it found,
and exactly one of them is a dial refusal.

--------------------------------------------------------------------------------
THE VALUE
--------------------------------------------------------------------------------

    truthful_answer_missing   read back; the engine is running a prompt that does not
                              carry `TRUTHFUL_ANSWER_MARKER`.

It is a strict REFINEMENT of `not_applied`, not a sixth independent verdict:
`verification.judge` already returns `not_applied` the moment any checked property is
provably False, so this partitions that value rather than widening the vocabulary's
meaning. `agents/reconciliation.DRIFT_STATES_OUT_OF_SYNC` therefore holds BOTH, and every
count, alert body and console aggregate built on it keeps saying what it said.

A VALUE RATHER THAN A COLUMN, deliberately. A `truthful_answer_missing boolean` beside
`drift_state` would leave every existing reader seeing the familiar `not_applied` and free
not to look at the flag; a word they have never seen forces the question. It also keeps
this table's contents exactly the shape its RLS exemption is argued for in `d4b8e1c73f05`
— a verdict from a fixed vocabulary and two timestamps, no prose, no PII — and it adds no
column for `reliability/models.py` and `scripts/check_metadata_columns` to have to learn.

--------------------------------------------------------------------------------
LOCKING, DATA, RLS AND DOWNGRADE
--------------------------------------------------------------------------------

A CHECK constraint dropped and recreated. Recreating it VALIDATES the existing rows, which
is a scan of a table holding one row per published agent — tens, not millions — under
ACCESS EXCLUSIVE bounded by `lock_timeout` (hard rule 8). No column is added, no row is
rewritten, and no index changes: the sweep's queue index is on `(engine, drift_checked_at)`
and does not mention `drift_state`.

NO DATA MIGRATION, and that is the correct direction rather than an omission. Existing
`not_applied` rows are NOT reclassified: whether the truthful-answer directive was the
property that failed is a fact about a read-back nobody kept, and inventing it here would
put a dial refusal on an agent from a measurement that was never made (hard rule 11). The
sweep re-reads every live object within the day and stamps the truth.

DOWNGRADE narrows the CHECK back to the five values `d4b8e1c73f05` created, and FIRST
folds any `truthful_answer_missing` row back to `not_applied` — the value it refines and
the one it would have carried before this revision — because a downgrade whose constraint
rejects rows the database is already holding cannot apply. The fold loses only the
refinement; the divergence is still recorded, still counted as out of sync and still
alerted on, which is exactly the pre-D-562 behaviour a downgrade is asking for.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e91d3c47ab58"
down_revision: str | None = "c72b9e40af15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "engine_agent_routes"
CHECK_NAME = "ck_engine_agent_routes_drift_state"

# `d4b8e1c73f05`'s five, plus this revision's one. Spelled here rather than imported from
# the application: a migration must keep describing the schema it created even after the
# constant moves on, which is the whole reason that revision wrote its own tuple too.
# `tests/engine_drift_reconciliation_test.py` compares the LIVE constraint against
# `agents/reconciliation.DRIFT_STATES`, so the two cannot drift apart unnoticed.
OLD_STATES = ("applied", "not_applied", "unreadable", "unreachable", "not_published")
NEW_STATES = (*OLD_STATES, "truthful_answer_missing")


def _check_sql(states: tuple[str, ...]) -> str:
    return "drift_state IS NULL OR drift_state IN (" + ", ".join(f"'{s}'" for s in states) + ")"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, _check_sql(NEW_STATES))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "UPDATE engine_agent_routes SET drift_state = 'not_applied' "
        "WHERE drift_state = 'truthful_answer_missing'"
    )
    op.drop_constraint(op.f(CHECK_NAME), TABLE, type_="check")
    op.create_check_constraint(op.f(CHECK_NAME), TABLE, _check_sql(OLD_STATES))
