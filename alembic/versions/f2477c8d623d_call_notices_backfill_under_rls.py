"""re-run c4e8a2f61d93's call-notice backfill inside the RLS bracket, and put the notices back on the calls (D-1021)

`c4e8a2f61d93` moved the AI and recording notice switches onto the client account and turned
an account's switch on wherever any of its agents had it on. Its backfill ran without the
`NO FORCE` / `FORCE ROW LEVEL SECURITY` bracket on `organizations` and `agents`. Both are
FORCE-RLS'd, which binds the owner role migrations run as (`alembic/env.py`) to the fail-closed
tenant policy, so on a deployment whose owner is not a superuser (production, DEPLOYMENT §9.3a)
the UPDATE matched no rows and every account reads both notices OFF. The local superuser owner
bypasses RLS, which is why it passed locally.

This revision, run bracketed:

- adds `organizations.notice_generation`, which moves on every flip so each flip queues fresh
  opening rewrites (`agents/opening_notices`);
- turns an account's switch ON where it is still off, some agent of the account not deleted
  has the old per-agent switch on, and no `audit_log` row records a flip of THAT switch for the
  account (`organization.ai_disclosure_enabled|disabled`, resp. `recording_notice_*`): an
  owner who chose since the deploy keeps the choice. Idempotent: a healthy deployment (a
  superuser owner ran the original correctly) has nothing still off to turn on;
- queues one `refresh_account_notices` job per account turned on, stamped with this revision
  so only a release that contains it claims the job (`reliability.service.claim_outbox`). The
  job queues each opening's rewrite, each Inbound line's and campaign's, and a tenant live
  apply, exactly as a switch flip does, and writes the audit row for the switch it restored.

The job rather than a script: it runs on every deployment that applies this revision, with no
step for a person to forget, and the job is the one `set_account_notices` already performs.

DOWNGRADE drops `notice_generation` and leaves the switches as they are. Turning a notice back
off is an owner's decision; `c4e8a2f61d93`'s own downgrade then writes each account's value
onto its agents, which the code before D-1021 reads.

Revision ID: f2477c8d623d
Revises: c4e8a2f61d93
Create Date: 2026-11-19 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f2477c8d623d"
down_revision: str | None = "c4e8a2f61d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: The job `apps/workers/opening_notices.refresh_account_notices` runs. Spelled out: a
#: migration is a snapshot.
JOB = "refresh_account_notices"

#: (account column, old agent column, audit action stem).
_SWITCHES = (
    ("notice_ai_enabled", "ai_disclosure_enabled", "organization.ai_disclosure"),
    ("notice_recording_enabled", "recording_notice_enabled", "organization.recording_notice"),
)


def _restorable(account_column: str, agent_column: str, stem: str) -> str:
    return (
        f"(NOT o.{account_column} AND EXISTS (SELECT 1 FROM agents a WHERE a.tenant_id = o.id "
        f"AND a.deleted_at IS NULL AND a.{agent_column}) AND NOT EXISTS (SELECT 1 FROM "
        f"audit_log l WHERE l.tenant_id = o.id AND l.action IN ('{stem}_enabled', "
        f"'{stem}_disabled')))"
    )


def _repair() -> sa.TextClause:
    (ai_col, ai_agent, ai_stem), (rec_col, rec_agent, rec_stem) = _SWITCHES
    return sa.text(
        "WITH want AS (SELECT o.id, "
        f"{_restorable(ai_col, ai_agent, ai_stem)} AS ai, "
        f"{_restorable(rec_col, rec_agent, rec_stem)} AS recording "
        "FROM organizations o WHERE o.deleted_at IS NULL), "
        "repaired AS (UPDATE organizations o SET "
        f"{ai_col} = o.{ai_col} OR w.ai, {rec_col} = o.{rec_col} OR w.recording, "
        "notice_generation = o.notice_generation + 1, updated_at = now() "
        "FROM want w WHERE w.id = o.id AND (w.ai OR w.recording) "
        "RETURNING o.id, w.ai, w.recording) "
        "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, min_revision, "
        "dedupe_key, created_at, updated_at) "
        f"SELECT gen_random_uuid(), '{JOB}', jsonb_build_object('tenant_id', id::text, "
        "'ai', ai, 'recording', recording), 'pending', 0, :revision, "
        "'call-notices-repair:' || id::text || ':' || :revision, now(), now() FROM repaired "
        "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING"
    ).bindparams(revision=revision)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.add_column(
        "organizations",
        sa.Column("notice_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    try:
        queued = execute_data_statement(
            _repair(),
            note="Turned on the account notice switches c4e8a2f61d93's backfill missed.",
        )
        log.info("call notices backfill under RLS: %s accounts repaired", queued)
    finally:
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_column("organizations", "notice_generation")
