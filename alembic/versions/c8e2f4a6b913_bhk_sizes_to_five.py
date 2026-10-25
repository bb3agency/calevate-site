"""The real-estate BHK field names every size up to five (D-887)

Revision ID: c8e2f4a6b913
Revises: b3d7e2a9c461
Create Date: 2026-10-25 18:00:00.000000

On a production call of 25 Oct 2026 the caller said "Five", the agent read back "ఐదు బెడ్
రూమ్స్", and the lead was saved with `bhk_size = 3BHK`. The field offered 1BHK, 2BHK, 3BHK
and 4BHK+ under the reason "Flat size the caller asked for", so a count the list did not
name was mapped to a neighbouring value. `scripts/seed.VERTICAL_TEMPLATES` now carries
1BHK..4BHK and 5BHK+ with a reason that maps the spoken count, for agents made from now on.

Existing agents keep the schema they were made with, so this queues one
`refresh_field_reason` outbox message per account whose agents' CURRENT schema still holds
`bhk_size` with the previous reason AND the previous four choices, exactly
(`apps/workers/field_reason_refresh.py`, which re-checks both per agent under the row lock).
An owner who edited either keeps their field. Leads captured as `4BHK+` keep that value
under the schema version they were captured with; the Leads filter still offers it, marked
as no longer in the list (`crm/service.FacetValue.declared`).

DOWNGRADE queues the inverse for agents holding the new field exactly. The schema and
prompt versions the worker wrote stay on file as history.
"""

import json
from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c8e2f4a6b913"
down_revision: str | None = "b3d7e2a9c461"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
#: `tests/bhk_sizes_test.py` holds the new pair equal to the shipped template.
JOB = "refresh_field_reason"
KEY = "bhk_size"

OLD_REASON = (
    "Flat size the caller asked for. Not one the agent offered, and not one they rejected."
)
OLD_CHOICES: tuple[str, ...] = ("1BHK", "2BHK", "3BHK", "4BHK+")
NEW_REASON = (
    "Number of bedrooms the caller asked for, as they counted it: 'two BHK' or 'డబుల్ బెడ్ "
    "రూమ్' is 2BHK, 'four bedroom' is 4BHK, 'five', 'ఐదు బెడ్ రూమ్స్' or more is 5BHK+. "
    "Never round to a nearer size. Not one the agent offered, and not one they rejected."
)
NEW_CHOICES: tuple[str, ...] = ("1BHK", "2BHK", "3BHK", "4BHK", "5BHK+")


def _queue(
    old_reason: str, old_choices: Sequence[str], new_reason: str, new_choices: Sequence[str]
) -> int | None:
    """One message per account with an agent (not deleted) whose current schema holds the
    field with exactly `old_reason` and `old_choices`. `@>` narrows the scan; the equality
    on the element's `enum_values` is what makes a superset list not match."""
    return execute_data_statement(
        sa.text(
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object("
            "'tenant_id', t.tenant_id::text, 'key', CAST(:key AS text), "
            "'old_reason', CAST(:old AS text), 'new_reason', CAST(:new AS text), "
            "'old_enum_values', CAST(:old_choices AS jsonb), "
            "'new_enum_values', CAST(:new_choices AS jsonb)), "
            "'pending', 0, now(), now() FROM (SELECT DISTINCT a.tenant_id FROM agents a "
            "JOIN extraction_schemas es ON es.id = a.extraction_schema_id "
            "CROSS JOIN LATERAL jsonb_array_elements(es.fields) f "
            "WHERE a.deleted_at IS NULL AND f ->> 'key' = CAST(:key AS text) "
            "AND f ->> 'reason' = CAST(:old AS text) "
            "AND f -> 'enum_values' = CAST(:old_choices AS jsonb)) t"
        ).bindparams(
            job=JOB,
            key=KEY,
            old=old_reason,
            new=new_reason,
            old_choices=json.dumps(list(old_choices), ensure_ascii=False),
            new_choices=json.dumps(list(new_choices), ensure_ascii=False),
        ),
        note=f"Queued the new {KEY} field for accounts whose agents hold the other one.",
    )


def _queue_all(*, forward: bool) -> None:
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extraction_schemas NO FORCE ROW LEVEL SECURITY")
    if forward:
        queued = _queue(OLD_REASON, OLD_CHOICES, NEW_REASON, NEW_CHOICES)
    else:
        queued = _queue(NEW_REASON, NEW_CHOICES, OLD_REASON, OLD_CHOICES)
    log.info("field %s (%s): %s account(s) queued", KEY, forward, queued)
    op.execute("ALTER TABLE extraction_schemas FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _queue_all(forward=True)


def downgrade() -> None:
    _queue_all(forward=False)
