"""re-run the Inbound-line and campaign-source backfills with `organizations` readable

`d8b2f5a7c3e1` (Inbound lines) and `e3c7a1d9b4f2` (campaign sources) each walked tenants one
at a time under that tenant's `app.tenant_id`, which is right for the writes, but listed the
tenants with `SELECT id FROM organizations` BEFORE any tenant was set. `organizations` is
FORCE-RLS'd and its policy is fail-closed on an unset tenant, so wherever the owner role is
bound by RLS (production, DEPLOYMENT §9.3a) the list was empty and neither backfill ran:

* an answering number on an agent got no Inbound line;
* a campaign's files and notes were never carried into `campaign_sources`, so the campaign
  reads as working from nothing. `campaign_materials` still holds them.

The same walks, with only the tenant list read under a `NO FORCE` bracket on `organizations`;
every write still runs under its own tenant's policy.

* Lines: only numbers that answer calls, on agents that answer them (neither `direction` is
  `outbound`). An outbound-only agent's caller number needs no line, and putting it on one
  would make that line answer it.
  `d8b2f5a7c3e1` did not make that distinction; on deployments where it ran, its lines stay.
* Sources: only campaigns with no pick yet, so a campaign the owner has already re-picked
  for, or one `e3c7a1d9b4f2` carried over where it did run, is left as it is and no note is
  made twice.

DOWNGRADE deletes nothing: these rows cannot be told apart from the ones the originals would
have written, and the owner may have edited them since.

Revision ID: bd9b4b153d5a
Revises: a0849ad2f893
Create Date: 2026-11-19 23:40:00.000000
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from logging import getLogger
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "bd9b4b153d5a"
down_revision: str | None = "a0849ad2f893"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: `d8b2f5a7c3e1`'s uuid v7 expression, copied: a migration is a snapshot.
_UUID7 = (
    "encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid()) placing "
    "substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) "
    "from 3) from 1 for 6), 52, 1), 53, 1), 'hex')::uuid"
)

_LINES = f"""
INSERT INTO inbound_lines (id, tenant_id, name, agent_id, script, created_at, updated_at)
SELECT {_UUID7}, a.tenant_id, left(a.name, 80), a.id, pv.structured_script, now(), now()
  FROM agents a
  LEFT JOIN prompt_versions pv ON pv.id = a.live_prompt_id
 WHERE a.tenant_id = :t AND a.deleted_at IS NULL AND a.direction <> 'outbound'
   AND EXISTS (SELECT 1 FROM phone_numbers n WHERE n.agent_id = a.id
                AND n.released_at IS NULL AND n.inbound_line_id IS NULL
                AND n.direction <> 'outbound')
RETURNING id, agent_id
"""

_ATTACH = sa.text(
    "UPDATE phone_numbers SET inbound_line_id = :lid WHERE tenant_id = :t AND agent_id = :aid "
    "AND released_at IS NULL AND inbound_line_id IS NULL AND direction <> 'outbound'"
)

_UNPICKED = sa.text(
    "SELECT DISTINCT m.campaign_id FROM campaign_materials m WHERE m.archived_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM campaign_sources s WHERE s.campaign_id = m.campaign_id)"
)


def _campaign_sources_revision() -> ModuleType:
    """`e3c7a1d9b4f2`'s carry-over, used as written rather than copied."""
    path = Path(__file__).with_name("e3c7a1d9b4f2_campaign_sources.py")
    spec = importlib.util.spec_from_file_location("_revision_e3c7a1d9b4f2", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tenants(bind: sa.Connection) -> list[object]:
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    try:
        return list(bind.execute(sa.text("SELECT id FROM organizations ORDER BY id")).scalars())
    finally:
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    # Both walks read and write row by row, so they have no SQL form to render offline.
    if probe_skipped_offline(
        "bd9b4b153d5a: Inbound lines and campaign sources were NOT re-backfilled (needs a "
        "connection); upgrade online to run them"
    ):
        return
    bind = op.get_bind()
    carry_over = _campaign_sources_revision()._carry_over
    entry = bind.execute(sa.text("SELECT current_setting('app.tenant_id', true)")).scalar()
    lines = campaigns = 0
    # Lifted for the owner only, inside this transaction; every statement on them names its
    # tenant. `kb_sources` and `kb_documents` are `e3c7a1d9b4f2`'s own bracket.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE inbound_lines NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_sources NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_documents NO FORCE ROW LEVEL SECURITY")
    try:
        for tenant_id in _tenants(bind):
            bind.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            for line_id, agent_id in bind.execute(sa.text(_LINES), {"t": tenant_id}).all():
                bind.execute(_ATTACH, {"lid": line_id, "t": tenant_id, "aid": agent_id})
                lines += 1
            unpicked = set(bind.execute(_UNPICKED).scalars())
            if unpicked:
                carry_over(bind, tenant_id, unpicked)
                campaigns += len(unpicked)
    finally:
        bind.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": entry or ""})
        op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_sources FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE inbound_lines FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE prompt_versions FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    log.info("re-backfill under RLS: %s Inbound lines, %s campaigns carried over", lines, campaigns)


def downgrade() -> None:
    """Deliberately empty; see the docstring."""
