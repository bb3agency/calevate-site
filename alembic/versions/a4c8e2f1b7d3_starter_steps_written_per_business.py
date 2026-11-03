"""organizations: each business's own steps for the ready-made jobs

Revision ID: a4c8e2f1b7d3
Revises: f7d2b9c4e1a8
Create Date: 2026-11-03

`starter_plans` holds, per ready-made job, the steps rewritten for this business: a title in
its words and one line of focus per step (`agents/starter_plans`). The count, order,
instruction and "done when" stay the platform's; the "pick a job" screen shows these titles,
a new agent's first script names its sections with them, and the script writer keeps them.
Written by `workers/starter_steps` whenever what the business sells changes.

`organizations` already carries FORCEd row-level security; a column adds no policy. The
CHECK is added NOT VALID and then validated, so the brief ACCESS EXCLUSIVE does not wait on
a scan.

Data: one `write_starter_steps` outbox message per live account whose business profile lists
what it sells, deduped as `maybe_write_starter_steps` dedupes, so existing clients get their
steps too. DOWNGRADE drops the column; the steps are display and drafting input only, and an
agent already created keeps the script it was created with.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from apps.api.db.migration_offline import execute_data_statement

revision: str = "a4c8e2f1b7d3"
down_revision: str | None = "f7d2b9c4e1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

# Spelled out rather than imported: a migration is a snapshot.
JOB = "write_starter_steps"
_CK = "ck_organizations_starter_plans_is_object"

QUEUE = (
    "INSERT INTO outbox_messages (id, job, payload, dedupe_key, status, attempt_count, "
    "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', "
    "o.id::text, 'services', md5(bp.services::text)), 'starter-steps:' || o.id::text || ':' "
    "|| md5(bp.services::text), 'pending', 0, now(), now() FROM organizations o "
    "JOIN business_profiles bp ON bp.tenant_id = o.id WHERE o.deleted_at IS NULL "
    "AND jsonb_array_length(bp.services) > 0 "
    "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column(
            "starter_plans",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        f"ALTER TABLE organizations ADD CONSTRAINT {_CK} "
        "CHECK (jsonb_typeof(starter_plans) = 'object') NOT VALID"
    )
    op.execute(f"ALTER TABLE organizations VALIDATE CONSTRAINT {_CK}")
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE business_profiles NO FORCE ROW LEVEL SECURITY")
    queued = execute_data_statement(
        sa.text(QUEUE).bindparams(job=JOB),
        note="Queued the starter-step writing job for accounts with a business profile.",
    )
    log.info("starter steps: %s account(s) queued", queued)
    op.execute("ALTER TABLE business_profiles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE organizations DROP CONSTRAINT IF EXISTS {_CK}")
    op.drop_column("organizations", "starter_plans")
