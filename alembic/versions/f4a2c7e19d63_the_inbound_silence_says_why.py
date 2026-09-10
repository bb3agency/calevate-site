"""the inbound silence says WHY it is silent (D-564)

Revision ID: f4a2c7e19d63
Revises: e91d3c47ab58
Create Date: 2026-09-10 16:40:00.000000

ONE NULLABLE COLUMN, ONE BACKFILL AND ONE CHECK on `agents`.

--------------------------------------------------------------------------------
WHY
--------------------------------------------------------------------------------

`agents.inbound_silenced_at` (d1a7f39c50be) is a mirror of the engine: the instant the
vendor was last observed to hold something other than this agent's own words. It was
built when exactly one thing could put it there — an empty prepaid wallet — so the column
answers "since when" and the reason was implied by the only mechanism that could write it.

D-564 gives it a second writer with a different remedy, a different message and a
different precedence. When the half-hourly drift sweep PROVES an agent is running a prompt
with no truthful-answer directive in it (`engine_agent_routes.drift_state =
'truthful_answer_missing'`, e91d3c47ab58), D-562 already refuses its OUTBOUND dials — and
the agent went on ANSWERING, telling anyone who asked whether it was an AI whatever the
vendor's console was last used to write. That is hard rule 5's floor, on a live call.

With two reasons, an implied one is a bug waiting for its first republish: a top-up would
clear a silence it did not cause, and a credit reconciliation would restore a phone that
must not answer. The column has to say which.

--------------------------------------------------------------------------------
THE SHAPE, AND THE TWO THAT WERE REJECTED
--------------------------------------------------------------------------------

A COLUMN BESIDE THE STAMP, holding one word from a fixed vocabulary.

REJECTED — a side table (`agent_inbound_silences`, one row per reason). It models a set,
and the thing being recorded is not a set: the engine holds exactly ONE state for one
agent, and two rows claiming different states for it is a mirror that can contradict
itself. It would also put a join on the end of every publish, which is the one path this
mirror exists to keep free of round trips.

REJECTED — derive it, with no column at all. The compliance verdict is genuinely already
in the database (`engine_agent_routes.drift_state`), so "should this agent be silent" needs
nothing new. But "what is the engine holding RIGHT NOW" cannot be derived from a verdict —
that is exactly the distinction `d1a7f39c50be` spends its "what this column is NOT"
section on, pointing the other way. Without a mirror of the reason, every publish would
have to re-issue the vendor calls to find out, and idempotence is the property that lets
`_settle_inbound_silence` run on all thirteen republish paths for free.

    credits                   the wallet is at zero or below; the engine holds the
                              credit-stop script (`agents.service.CREDIT_STOP_MESSAGE`).
    truthful_answer_missing   the sweep proved the truthful-answer directive gone; the
                              agent's numbers are UNBOUND and nothing answers them.

The second value is spelled exactly as `agents/reconciliation.TRUTHFUL_ANSWER_MISSING`,
because it mirrors that verdict and a second spelling of one word is where drift starts.

--------------------------------------------------------------------------------
THE CHECK, AND WHY IT IS AN EQUIVALENCE
--------------------------------------------------------------------------------

    (inbound_silenced_at IS NULL) = (inbound_silence_reason IS NULL)

Both halves are OURS and are written by one function in one statement, which is the
condition `d1a7f39c50be` said it did not have when it declined a CHECK of its own (the
other half of THAT fact lives at a third party). A stamp with no reason is a silence
nobody can end correctly; a reason with no stamp is a claim about an engine that is
answering normally. Neither is a state any code path should be able to produce, so the
database refuses both.

--------------------------------------------------------------------------------
BACKFILL, LOCKING, RLS AND DOWNGRADE
--------------------------------------------------------------------------------

BACKFILL to `credits`, and it is evidence rather than a guess (hard rule 11): until this
revision `reconcile_inbound_answering` and `_settle_inbound_credit_state` were the ONLY
writers of `inbound_silenced_at`, and both write it for one reason. Every existing
non-NULL stamp therefore means the credit-stop script, and saying so is reporting what the
old code did, not inventing a measurement. It runs BEFORE the CHECK is added, or the
constraint could not validate.

ADD COLUMN of a nullable column with no default is catalogue-only (PG 11+); the CHECK
validates by scanning a table holding one row per agent — tens, not millions — under
ACCESS EXCLUSIVE bounded by `lock_timeout` (hard rule 8). No index: both readers already
have the row in hand (`agents.service._ANSWERING_AGENT_COLUMNS` under RLS, and the
single-agent read beside it).

RLS: none to add. `agents` is already tenant-scoped with its FORCEd policy; a column
inherits it.

DOWNGRADE drops the CHECK and the column, which is reversible in the sense hard rule 8
asks for: no other table references it and no money or consent is recorded here. What it
loses is the ability to tell the two silences apart, so a downgraded deployment is back to
the pre-D-564 behaviour where a republish ends any silence — the state this revision
exists to leave. Nothing is dropped that is still being written: the code that reads this
column ships in the same release.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a2c7e19d63"
down_revision: str | None = "e91d3c47ab58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK_NAME = "ck_agents_inbound_silence_reason"

# Spelled here rather than imported from the application, for `e91d3c47ab58`'s reason: a
# migration must keep describing the schema IT created even after the constant moves on.
# `tests/inbound_compliance_silence_test.py` compares this constraint against
# `agents/service.INBOUND_SILENCE_REASONS`, so the two cannot drift apart unnoticed.
REASONS = ("credits", "truthful_answer_missing")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("agents", sa.Column("inbound_silence_reason", sa.Text(), nullable=True))
    # THE FORCE BRACKET (`d3b71c9a5e08`). `agents` is FORCE-RLS'd, so the migration's own
    # owner role is subject to `tenant_isolation` too — and that policy is fail-closed on
    # an unset `app.tenant_id`, which a migration has no business setting. Without the
    # bracket this UPDATE would match ZERO rows on a populated database and report success,
    # leaving every existing silence with a NULL reason and the CHECK below unable to
    # validate. It lifts RLS for the OWNER only (`calevate_app` is NOSUPERUSER NOBYPASSRLS
    # and keeps every policy), and DDL is transactional, so FORCE is restored before commit.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE agents SET inbound_silence_reason = 'credits' "
        "WHERE inbound_silenced_at IS NOT NULL"
    )
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.create_check_constraint(
        op.f(CHECK_NAME),
        "agents",
        "(inbound_silenced_at IS NULL) = (inbound_silence_reason IS NULL) "
        "AND (inbound_silence_reason IS NULL OR inbound_silence_reason IN ("
        + ", ".join(f"'{r}'" for r in REASONS)
        + "))",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_constraint(op.f(CHECK_NAME), "agents", type_="check")
    op.drop_column("agents", "inbound_silence_reason")
