"""An agent can be archived without being erased — D-432

Revision ID: e4b90d27c1f6
Revises: a7e3b91c04df

WHAT WAS MISSING. `agents.status` held three values — `draft`, `live`, `paused` — and the
only way to take an agent out of a client's roster for good was `deleted_at`, which is the
ERASURE column: it is written by the DPDP deletion path (`compliance/deletion.py`,
`workers/retention.py`), it hides the row from every read in the tree, and `calls.agent_id`
is `ON DELETE RESTRICT` precisely because a call's agent has to stay readable. So a client
who had finished with an agent had two options, and both were wrong: leave it `paused` in
the working roster forever, or reach for a soft delete that means "this client's data was
erased" and takes the agent's own call history off every screen with it.

`archived` is the fourth status and it is NOT a delete. The row stays; its calls, its
prompt versions, its extraction schema and its audit trail stay readable; it is simply
never dialled and never assignable. The two facts are enforced in code by the gates that
already exist — `compliance/service.check_dispatch` refuses `status <> 'live'` per contact
and `campaigns/service.launch_blockers` refuses it per launch, so an archived agent stops
dialling on the very next dispatch tick without either gate learning a new word.

WHY `archived_at` IS A COLUMN AND NOT A DERIVATION. "Archived" is a state and "when it was
archived" is the ordering key of the history list the client reads; `updated_at` cannot
serve, because every republish, voice change and disclosure toggle moves it. The pair is
held together by `ck_agents_archived_at_matches_status` — an EQUIVALENCE, not an
implication, so neither half can drift: a row cannot be `archived` with no timestamp, and
cannot carry a timestamp in any other state. The restore path clears it in the same
statement that moves the status, which is the only reason that constraint is satisfiable.

WHY THE CHECK IS DROPPED AND RECREATED rather than widened in place. Postgres has no
"widen a CHECK" — a constraint is immutable — so the old one goes and the new one arrives
`NOT VALID` and is then validated, which is the shape migration a4e7b2c95d18 uses on this
same table and for the same reason: `ADD CONSTRAINT` without `NOT VALID` holds ACCESS
EXCLUSIVE on `agents` for the length of its scan, and `agents` is on the publish path.

THE `NO FORCE ROW LEVEL SECURITY` BRACKET is a4e7b2c95d18's too, and it is load-bearing
for the DOWNGRADE rather than the upgrade: the downgrade has to move any `archived` row
back to `paused` before it can narrow the CHECK, and `agents` is `FORCE ROW LEVEL
SECURITY` — which, unlike plain RLS, applies to the table's OWNER as well. With no
`app.tenant_id` set the policy's `USING` is NULL for every row, so that UPDATE matches
none, reports success, and the narrowing then fails with a CheckViolation naming rows the
migration believed it had already moved. A downgrade that cannot run on data its own
upgrade permitted is not reversible (hard rule 8).

**IT CANNOT BE DEMONSTRATED ON A DEVELOPER MACHINE, WHICH IS WHY IT IS WRITTEN DOWN.** The
local `ALEMBIC_DATABASE_URL` role is a SUPERUSER, and a superuser bypasses row security
outright — so the bracketed and unbracketed downgrades both report `UPDATE 54` on a laptop
and the difference only appears where `ALEMBIC_DATABASE_URL` names the plain table owner,
i.e. in production. Deleting the bracket therefore passes every local check and breaks the
one environment that matters, which is precisely the shape a4e7b2c95d18 recorded.

NO NEW INDEX. The roster reads are `WHERE tenant_id = ...` under RLS with an optional
status filter, over a table that holds a handful of rows per tenant — `ix_agents_tenant_id`
answers them, and an index on a four-value column of a small per-tenant set would be read
by nothing (DATA-MODEL §10's measured-index rule).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e4b90d27c1f6"
down_revision = "a7e3b91c04df"
branch_labels = None
depends_on = None

TABLE = "agents"
CK_STATUS = "ck_agents_status_enum"
CK_ARCHIVED = "ck_agents_archived_at_matches_status"

_STATUS_BEFORE = ("draft", "live", "paused")
_STATUS_AFTER = ("draft", "live", "paused", "archived")


def _status_check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in values) + ")"


# An EQUIVALENCE. `status = 'archived'` and `archived_at IS NOT NULL` are two spellings of
# one fact, and a one-way implication would let the other direction rot unnoticed.
_ARCHIVED_CHECK = "(status = 'archived') = (archived_at IS NOT NULL)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(TABLE, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {CK_STATUS}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_STATUS} "
        f"CHECK ({_status_check(_STATUS_AFTER)}) NOT VALID"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_ARCHIVED} CHECK ({_ARCHIVED_CHECK}) NOT VALID"
    )
    # Every existing row is `draft`/`live`/`paused` with a NULL `archived_at`, so both
    # scans prove what they already know — they run so the constraints are not left
    # NOT VALID, where the planner ignores them and a later ADD CONSTRAINT re-scans.
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_STATUS}")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_ARCHIVED}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_ARCHIVED}")
    # See the docstring: the bracket is what makes this UPDATE reach the rows. An
    # archived agent becomes `paused` — the state it came from and the one the narrowed
    # vocabulary can hold — rather than being deleted, because a downgrade that destroys
    # a client's agent to fit an older schema is worse than the schema it is restoring.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"UPDATE {TABLE} SET status = 'paused', archived_at = NULL WHERE status = 'archived'")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {CK_STATUS}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_STATUS} "
        f"CHECK ({_status_check(_STATUS_BEFORE)}) NOT VALID"
    )
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_STATUS}")
    op.drop_column(TABLE, "archived_at")
