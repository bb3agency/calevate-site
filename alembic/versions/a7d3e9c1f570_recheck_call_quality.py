"""Stored gaps and call mistakes found by checks since narrowed are read again (D-970)

Revision ID: a7d3e9c1f570
Revises: c4e7a2f9d1b8
Create Date: 2026-11-05

On the Rytu Khata calls of 4 Nov 2026 the caller's "I will try." was listed as a question to
answer, a number read again because the caller asked counted as "said the same line again",
and a goodbye after the caller signed off counted as "said goodbye while the caller was still
asking". The checks are narrowed in code; this queues one `recheck_call_quality` outbox
message per account holding an open gap or one of those two mistake kinds, and the worker
(`apps/workers/call_quality_recheck.py`) removes what the current checks no longer find. The
filter here is wider than the worker's: the reading happens in one place, the worker.

DOWNGRADE queues nothing and restores nothing: a removed row was a false finding.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "a7d3e9c1f570"
down_revision: str | None = "c4e7a2f9d1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN: `apps/workers/call_quality_recheck.JOB_NAME` on the day this ran.
JOB = "recheck_call_quality"

QUEUE = (
    "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, created_at, "
    "updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', "
    "t.tenant_id::text), 'pending', 0, now(), now() FROM ("
    "SELECT tenant_id FROM knowledge_gaps WHERE status = 'open' "
    "UNION SELECT tenant_id FROM call_mistakes "
    "WHERE kind IN ('said_again', 'goodbye_while_asking')) t"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE knowledge_gaps NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_mistakes NO FORCE ROW LEVEL SECURITY")
    queued = execute_data_statement(
        sa.text(QUEUE).bindparams(job=JOB),
        note="Queued the call-quality recheck for accounts with open gaps or call mistakes.",
    )
    log.info("call quality recheck: %s account(s) queued", queued)
    op.execute("ALTER TABLE call_mistakes FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_gaps FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing: see the module docstring."""
