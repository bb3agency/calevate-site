"""The telephony carrier becomes a processor an erasure can open a task against.

The published sub-processor register tells clients the carrier receives "the caller and
called numbers, call detail records, and the live audio of the call in both directions" —
and `processor_erasure_tasks` could only name `voice_engine`, `speech` and `llm`. So a DPDP
§12 certificate enumerated three vendor copies and was structurally incapable of naming the
one vendor the register says holds both the number and the audio. `compliance/
processor_erasure.PROCESSORS` gained `telephony`; without this the INSERT raises
`IntegrityError` and the role is a constant nothing can use.

TWO-STEP SAFE AND REVERSIBLE. Widening a CHECK admits values that were refused before, so
every existing row still satisfies it and the downgrade is only unsafe if a `telephony` row
exists by then — which is why the downgrade DELETES those rows first rather than failing
with a constraint violation that names no cause. That is a deliberate, narrow destruction of
rows this migration itself made possible, and it is the only shape of downgrade that leaves
the database in the state the previous revision describes.

Revision ID: e3a7c05b91d4
Revises: c7f1a9d4e620
"""

from __future__ import annotations

from alembic import op

revision = "e3a7c05b91d4"
down_revision = "c7f1a9d4e620"
branch_labels = None
depends_on = None

_OLD = "processor IN ('voice_engine', 'speech', 'llm')"
_NEW = "processor IN ('voice_engine', 'speech', 'llm', 'telephony')"
#: THE BARE NAME, NOT THE RENDERED ONE. `alembic/env.py` sets a naming convention, so
#: `op.drop_constraint` runs whatever it is given back through `ck_%(table_name)s_
#: %(constraint_name)s` — handing it the already-rendered name produced
#: `ck_processor_erasure_tasks_ck_processor_erasure_tasks_p_f73a` and a DROP that named
#: nothing. Both directions of this migration pass the bare name for that reason.
_NAME = "processor_is_known"


def upgrade() -> None:
    op.drop_constraint("processor_is_known", "processor_erasure_tasks", type_="check")
    op.create_check_constraint(
        "processor_is_known", "processor_erasure_tasks", _NEW
    )


def downgrade() -> None:
    # The rows this revision made insertable have to go before the narrower constraint can
    # hold. Scoped to exactly those rows: nothing that predates this revision is touched.
    #
    # ⚠ **BRACKETED, AND WITHOUT THE BRACKET THIS DOWNGRADE WAS SILENTLY BROKEN.**
    # `processor_erasure_tasks` is FORCE RLS and `tenant_isolation` is fail-closed on an
    # unset `app.tenant_id`, so a migration's DELETE matches ZERO rows and reports success —
    # after which `create_check_constraint` fails on the rows it believed gone, naming a
    # constraint violation rather than the real cause. `tests/migration_rls_bracket_test.py`
    # caught exactly this. The bracket lifts RLS for the OWNER only: `calevate_app` is
    # NOSUPERUSER NOBYPASSRLS and keeps every policy, and DDL is transactional so FORCE is
    # restored before commit (`d3b71c9a5e08` is the precedent and carries the full argument).
    op.execute("ALTER TABLE processor_erasure_tasks NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM processor_erasure_tasks WHERE processor = 'telephony'")
    op.execute("ALTER TABLE processor_erasure_tasks FORCE ROW LEVEL SECURITY")
    op.drop_constraint("processor_is_known", "processor_erasure_tasks", type_="check")
    op.create_check_constraint(
        "processor_is_known", "processor_erasure_tasks", _OLD
    )
