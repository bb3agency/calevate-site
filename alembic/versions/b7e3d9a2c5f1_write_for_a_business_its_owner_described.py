"""queue job steps and detail names for businesses described only in the owner's words

Revision ID: b7e3d9a2c5f1
Revises: a4c8e2f1b7d3
Create Date: 2026-11-03

a4c8e2f1b7d3 and f7d2b9c4e1a8 queued the writing only for accounts whose profile listed what
they sell. An owner who described the business in "Meet your agent" (`first_runs.brief`) and
left that list empty got neither, though the brief is the richest description we hold. Both
are now written from either (`agents/starter_plans.business_known`); this queues them for
every live account that has a description and does not yet have its steps or its names,
under the same dedupe keys the app uses.

Data only. DOWNGRADE does nothing: a queued message is consumed or dead-lettered on its own.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "b7e3d9a2c5f1"
down_revision: str | None = "a4c8e2f1b7d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

# Spelled out rather than imported: a migration is a snapshot. Same expression as
# `starter_plans.BUSINESS_KNOWN_SQL`, with `MIN_BRIEF_CHARS` (20) as it stood.
_KNOWN = (
    "(coalesce(length(btrim(fr.brief)), 0) >= 20 "
    "OR coalesce(jsonb_array_length(bp.services), 0) > 0)"
)
_DIGEST = "md5(coalesce(fr.brief, '') || '|' || coalesce(bp.services::text, '[]'))"
_DESCRIBED = (
    "FROM organizations o LEFT JOIN business_profiles bp ON bp.tenant_id = o.id "
    f"LEFT JOIN first_runs fr ON fr.tenant_id = o.id WHERE o.deleted_at IS NULL AND {_KNOWN}"
)

STEPS = (
    "INSERT INTO outbox_messages (id, job, payload, dedupe_key, status, attempt_count, "
    "created_at, updated_at) SELECT gen_random_uuid(), 'write_starter_steps', "
    f"jsonb_build_object('tenant_id', o.id::text, 'known', {_DIGEST}), "
    f"'starter-steps:' || o.id::text || ':' || {_DIGEST}, 'pending', 0, now(), now() "
    f"{_DESCRIBED} AND o.starter_plans = '{{}}'::jsonb "
    "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING"
)

NAMES = (
    "INSERT INTO outbox_messages (id, job, payload, dedupe_key, status, attempt_count, "
    "created_at, updated_at) SELECT gen_random_uuid(), 'name_core_details', "
    "jsonb_build_object('tenant_id', o.id::text), "
    f"'core-labels:' || o.id::text || ':' || {_DIGEST}, 'pending', 0, now(), now() "
    f"{_DESCRIBED} AND o.core_field_labels = '{{}}'::jsonb "
    "AND o.core_labels_drafted_at IS NULL "
    "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING"
)

_TABLES = ("organizations", "business_profiles", "first_runs")


def upgrade() -> None:
    # The FORCE bracket (`f4a2c7e19d63`): all three are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    steps = execute_data_statement(
        sa.text(STEPS), note="Queued job steps for described accounts without them."
    )
    names = execute_data_statement(
        sa.text(NAMES), note="Queued detail names for described accounts without them."
    )
    log.info("described businesses: %s step writing(s), %s naming(s) queued", steps, names)
    for table in reversed(_TABLES):
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    pass
