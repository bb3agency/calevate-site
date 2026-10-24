"""The lakh-valued money fields read a spoken range as a range (D-881)

Revision ID: b3d7e2a9c461
Revises: f4b8c1d6a273
Create Date: 2026-10-25 12:00:00.000000

On a production call of 24 Oct 2026 the caller said "One two crores, sir." (one to two
crore) and the lead was saved with `budget_lakhs = 120`: the field's reason, which is the
extraction model's instruction and is also compiled into the agent's script, gave '1.2
crore' as its only crore example. `scripts/seed.VERTICAL_TEMPLATES` carries the new wording
for real estate's `budget_lakhs` and insurance's `sum_assured` (the other lakh-valued
number, which said only "Cover amount in lakhs") for agents made from now on.

Existing agents keep the schema they were made with, so this queues one
`refresh_field_reason` outbox message per (account, field) where an agent's CURRENT schema
still holds that field with the previous reason word for word. The worker
(`apps/workers/field_reason_refresh.py`) writes a new schema version with the new reason,
recompiles the script and republishes a live agent; a reason anybody edited is not touched.
Nothing is rewritten in place: a lead records the schema version it was captured under
(TRD §7), and the earlier version must keep saying what the model was told then.

DOWNGRADE queues the inverse (new wording back to old) for agents holding the new wording
exactly, which includes agents made from the new template after this ran. The schema and
prompt versions the worker wrote stay on file as history.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "b3d7e2a9c461"
down_revision: str | None = "f4b8c1d6a273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
#: `tests/budget_reason_test.py` holds each new wording equal to the shipped template.
#: `apps/workers/field_reason_refresh.JOB_NAME`.
JOB = "refresh_field_reason"

#: (field key, the previous template reason, the new one).
REFRESHES: tuple[tuple[str, str, str], ...] = (
    (
        "budget_lakhs",
        "Budget in LAKHS of rupees: '50 lakhs' is 50, '1.2 crore' is 120. "
        "Never rupees, never a range — take the upper figure the caller "
        "states, and leave it empty if they state none.",
        "Budget in LAKHS of rupees: '50 lakhs' is 50, '2 crore' is 200. Two "
        "numbers before one unit are a range, never a decimal: 'one two crores', "
        "'ఒకటి రెండు కోట్లు' and '1-2 crore' mean one to two crore, so 200; 'two "
        "three lakhs' is 3. A decimal needs a point or a half: 'one point two "
        "crore' or '1.2 crore' is 120, 'ఒకటిన్నర కోటి' is 150. Never rupees; take "
        "the upper figure of a range; leave it empty if they state none.",
    ),
    (
        "sum_assured",
        "Cover amount in lakhs",
        "Cover amount in LAKHS of rupees: '5 lakhs' is 5, '1 crore' is 100. Two "
        "numbers before one unit are a range, take the upper figure: 'ten fifteen "
        "lakhs' or 'పది పదిహేను లక్షలు' is 15. A decimal needs a point or a half: "
        "'1.5 crore' is 150. Never rupees; leave it empty if they state none.",
    ),
)


def _queue(key: str, old: str, new: str) -> int | None:
    """One message per account with an agent (not deleted) whose current schema holds `key`
    with exactly `old`. `@>` on the array element is string equality on both values."""
    return execute_data_statement(
        sa.text(
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object("
            "'tenant_id', t.tenant_id::text, 'key', CAST(:key AS text), "
            "'old_reason', CAST(:old AS text), 'new_reason', CAST(:new AS text)), "
            "'pending', 0, now(), now() FROM (SELECT DISTINCT a.tenant_id FROM agents a "
            "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
            "WHERE a.deleted_at IS NULL AND es.fields @> jsonb_build_array("
            "jsonb_build_object('key', CAST(:key AS text), 'reason', CAST(:old AS text)))) t"
        ).bindparams(job=JOB, key=key, old=old, new=new),
        note=f"Queued the new {key} wording for accounts whose agents hold the other one.",
    )


def _queue_all(*, forward: bool) -> None:
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extraction_schemas NO FORCE ROW LEVEL SECURITY")
    for key, old, new in REFRESHES:
        queued = _queue(key, old, new) if forward else _queue(key, new, old)
        log.info("field reason %s (%s): %s account(s) queued", key, forward, queued)
    op.execute("ALTER TABLE extraction_schemas FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _queue_all(forward=True)


def downgrade() -> None:
    _queue_all(forward=False)
