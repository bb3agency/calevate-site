"""outbox messages carry a consume deadline and the revision that queued them

Revision ID: f5a9c3e1d7b2
Revises: e3b8d1f6a924
Create Date: 2026-11-05 18:00:00.000000

Two nullable columns on `outbox_messages` (no tenant data, no policy: the table has none by
design, `db/registry`).

- `consume_by`: a published message whose run never succeeded used to be invisible, its
  payload already scrubbed (L5-03). The payload is now kept until the run succeeds, and a
  message past this deadline with no `consumed_at` is alarmed and re-published
  (`reliability/service.sweep_unconsumed_outbox`). Rows published before this revision keep
  NULL: their payload is gone, so there is nothing to re-publish.
- `min_revision`: a migration that queues work stamps its own revision, and only a
  dispatcher whose image contains that revision claims the row, so the old release still
  running between migrate and swap cannot run the new message with old code (L5-04).

Two one-off messages are queued, each stamped with this revision, so only the new workers
run them:

- `refile_caller_memories` per account holding notes from outbound calls: they were filed
  under the business's own calling number (L5-02) and go under the person called.
- `recheck_call_quality` per account holding an open knowledge gap: the narrowed question
  test and the deferral rule (L5-05, L5-06) clear the gaps they no longer find.

`downgrade()` queues the refile back to the calling number (undoing the repair; it runs on
any release that has the job, otherwise it is dead-lettered and replayable), then drops the
index and both columns. Gaps the recheck removed were false findings and are not restored.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f5a9c3e1d7b2"
down_revision: str | None = "e3b8d1f6a924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN: `apps/workers/caller_memory_distil.REFILE_JOB` and its `file_under` values, and
#: `apps/workers/call_quality_recheck.JOB_NAME`, on the day this ran.
REFILE_JOB = "refile_caller_memories"
RECHECK_JOB = "recheck_call_quality"

_ACCOUNTS_WITH_OUTBOUND_MEMORIES = (
    "SELECT DISTINCT m.tenant_id FROM caller_memories m JOIN calls c ON c.id = m.source_call_id "
    "WHERE c.direction <> 'inbound' AND m.scrubbed_at IS NULL"
)
QUEUE_REFILE = (
    "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
    "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', "
    "t.tenant_id::text, 'file_under', :file_under), 'pending', 0, :revision, now(), now() "
    f"FROM ({_ACCOUNTS_WITH_OUTBOUND_MEMORIES}) t"
)
QUEUE_RECHECK = (
    "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
    "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object('tenant_id', "
    "t.tenant_id::text), 'pending', 0, :revision, now(), now() "
    "FROM (SELECT DISTINCT tenant_id FROM knowledge_gaps WHERE status = 'open') t"
)
_FORCED = ("caller_memories", "calls", "knowledge_gaps")


def _unforced() -> None:
    # The FORCE bracket (`f4a2c7e19d63`): FORCE-RLS'd tables read as empty to the owner.
    for table in _FORCED:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")


def _forced() -> None:
    for table in _FORCED:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column("outbox_messages", sa.Column("consume_by", sa.DateTime(timezone=True)))
    op.add_column("outbox_messages", sa.Column("min_revision", sa.Text()))
    # The sweep's predicate exactly, so it reads the few live rows and never the 90 days of
    # consumed history the prune keeps.
    op.create_index(
        "ix_outbox_unconsumed",
        "outbox_messages",
        ["consume_by"],
        postgresql_where=sa.text(
            "status = 'published' AND consumed_at IS NULL AND consume_by IS NOT NULL"
        ),
    )
    _unforced()
    refiles = execute_data_statement(
        sa.text(QUEUE_REFILE).bindparams(job=REFILE_JOB, file_under="other_party", revision=revision),
        note="Queued the caller-memory refile for accounts with notes from outbound calls.",
    )
    rechecks = execute_data_statement(
        sa.text(QUEUE_RECHECK).bindparams(job=RECHECK_JOB, revision=revision),
        note="Queued the knowledge-gap recheck for accounts with open gaps.",
    )
    _forced()
    log.info("queued %s refile(s) and %s recheck(s)", refiles, rechecks)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _unforced()
    execute_data_statement(
        sa.text(QUEUE_REFILE.replace(", min_revision", "").replace(", :revision", "")).bindparams(
            job=REFILE_JOB, file_under="calling_number"
        ),
        note="Queued the caller-memory refile back to the calling number.",
    )
    _forced()
    op.drop_index("ix_outbox_unconsumed", table_name="outbox_messages")
    op.drop_column("outbox_messages", "min_revision")
    op.drop_column("outbox_messages", "consume_by")
