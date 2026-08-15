"""ck_agents_engine_enum admits every engine ENGINE= can select, not the two it was born with

Revision ID: d7b1c48a2e93
Revises: c5a9e34b71d0
Create Date: 2026-08-15 12:05:00.000000

`agents.engine` has carried `CHECK (engine IN ('fake', 'bolna'))` since the first schema
migration (05bba2f3c19c), rendered from `apps/api/agents/models.py::ENGINES`. That tuple
was the THIRD hand-written copy of the engine set (D-103 found it while removing the
second), and it is the copy with teeth, because a CHECK constraint is not advisory.

WHAT WAS ACTUALLY BROKEN. `admin/service.py::_default_engine` writes
`get_settings().engine` into this column when a tenant is born. D-93/D-94 made `cartesia`
a value `config.EngineName` accepts, wired the adapter, and gave it a capability
descriptor — so a deployment could legitimately run `ENGINE=cartesia`, and on that
deployment the first thing a new client does, EXIST, failed with an IntegrityError out of
Postgres. Not a refusal anyone authored, not a message an operator could act on: a
constraint-violation traceback on the onboarding path, naming a constraint whose text
disagreed with the setting that produced the value.

WHY DROP-AND-RECREATE RATHER THAN `ALTER CONSTRAINT`. Postgres has no `ALTER TABLE ...
ALTER CONSTRAINT` for a CHECK's expression — `ALTER CONSTRAINT` only touches deferrability
on FKs. Drop and add is the only route, and it is safe in the widening direction: the new
predicate is strictly weaker, so no existing row can violate it and the ADD needs no
validation scan beyond the table read Postgres performs anyway.

WHY NOT `NOT VALID` + `VALIDATE CONSTRAINT`. That pair exists to avoid a long ACCESS
EXCLUSIVE lock while checking existing rows against a STRICTER predicate. Here the
predicate is weaker, so there is nothing to validate; adding `NOT VALID` would leave the
constraint permanently unvalidated for no benefit and hide a genuine violation later.

THE DOWNGRADE CAN REFUSE, AND THAT IS THE POINT. Narrowing back to `('fake', 'bolna')` is
a real narrowing: if any `agents` row carries `engine = 'cartesia'`, Postgres rejects the
ADD and the downgrade fails loudly. That is correct behaviour under hard rule 8 — a
reversible migration is one that either restores the old shape or refuses; one that
"reverses" by deleting client agent rows is not reversible, it is destructive. The
downgrade below therefore does the plain thing and lets Postgres be the judge, and says
so in its error path rather than leaving an operator to decode `23514`.

WHY THE PREDICATE IS SPELLED OUT HERE RATHER THAN INTERPOLATED FROM `ENGINES`. A migration
is a historical record of what the schema became at this revision; importing a constant
would make this file's meaning change every time that constant does, which is how a
migration stops describing the database it produced. The drift between the two is caught
where drift belongs — `tests/engine_name_drift_test.py` compares the LIVE constraint
against `SELECTABLE_ENGINES`, so adding a fourth engine to `EngineName` without a
migration fails the suite instead of failing a client's first insert.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7b1c48a2e93"
down_revision: str | None = "c5a9e34b71d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_agents_engine_enum"
WIDENED = "engine IN ('bolna', 'cartesia', 'fake')"
ORIGINAL = "engine IN ('fake', 'bolna')"


# `op.f(...)` — called INSIDE the two functions, twice, deliberately.
#
# WHAT IT DOES: marks the name as ALREADY conventionalised. Without it Alembic applies the
# metadata naming convention on top and looks for `ck_agents_ck_agents_engine_enum`, a
# constraint that has never existed. `05bba2f3c19c` wraps the same name the same way.
#
# WHY NOT HOISTED TO A MODULE CONSTANT: `op.f` needs the Operations proxy, which exists
# only during a migration run, while `check_wiring` IMPORTS every version module to find
# the head — a module-level `op.f` turns the head check into "the proxy object has not yet
# been established".
#
# WHY NOT A HELPER RETURNING `str`: `op.f` returns a `conv`, a `str` SUBCLASS whose type IS
# the marker. `str(op.f(name))` is a plain string again and the convention is reapplied —
# which looks identical at the call site and fails at runtime with the doubled name.


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "agents", WIDENED)


def downgrade() -> None:
    stranded = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM agents WHERE engine NOT IN ('fake', 'bolna')"))
        .scalar_one()
    )
    if stranded:
        # Raised BEFORE the drop, so a refused downgrade leaves the constraint intact
        # rather than dropping it and then failing to add the narrower one — which would
        # end with the table UNCONSTRAINED, the one outcome worse than either direction.
        raise RuntimeError(
            f"{stranded} agent row(s) carry an engine the pre-{revision} CHECK forbids. "
            "Downgrading would either reject or require deleting client agents. Repoint "
            "those agents at a permitted engine first, then re-run this downgrade."
        )
    op.drop_constraint(op.f(CONSTRAINT), "agents", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "agents", ORIGINAL)
