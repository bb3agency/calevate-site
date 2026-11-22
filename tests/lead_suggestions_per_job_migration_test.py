"""D-1029, migration f3b8d2a6c1e4: lead-detail suggestions move from the agent to its jobs.

The suggestions waiting on an agent and the fingerprints its owner turned down are copied onto
each of that agent's open campaigns and lines; an archived job gets nothing; the downgrade
drops the new columns and leaves the agent's own copies as they were; and the chain runs back
up.

SHARED DATABASE DISCIPLINE: every organisation is minted here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from sqlalchemy import create_engine, text
from tests.agent_lifecycle_test import _tenant
from tests.notes_per_job_test import _campaign, _line

pytestmark = pytest.mark.rls

STEM = "f3b8d2a6c1e4_lead_suggestions_per_job"
WAITING = [
    {
        "id": "0123456789abcdef",
        "kind": "add_choices",
        "field_key": "bhk_size",
        "field_label": "BHK",
        "values": ["6BHK"],
        "reason": "Two callers asked for 6BHK.",
        "source": "calls",
    }
]


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_waiting_and_turned_down_suggestions_follow_onto_the_agents_open_jobs() -> None:
    revision = _revision()
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    archived_line = await _line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET field_suggestions = CAST(:s AS jsonb), "
                "field_suggestions_dismissed = '[\"fedcba9876543210\"]'::jsonb, "
                "field_suggestions_state = 'done', field_suggestions_at = now() WHERE id = :a"
            ),
            {"s": json.dumps(WAITING), "a": agent_id},
        )
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"),
            {"l": archived_line},
        )

    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:

                def read(sql: str, job_id: UUID) -> object:
                    connection.execute(
                        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                    )
                    return connection.execute(text(sql), {"j": str(job_id)}).one()

                campaign_sql = (
                    "SELECT field_suggestions, field_suggestions_dismissed, "
                    "field_suggestions_state, field_suggestions_inputs FROM campaigns "
                    "WHERE id = :j"
                )
                line_sql = (
                    "SELECT field_suggestions, field_suggestions_dismissed, "
                    "field_suggestions_state, field_suggestions_inputs FROM inbound_lines "
                    "WHERE id = :j"
                )
                agent_sql = "SELECT field_suggestions FROM agents WHERE id = :j"
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    revision.upgrade()
                    for sql, job_id in ((campaign_sql, campaign_id), (line_sql, line_id)):
                        suggestions, dismissed, state, inputs = read(sql, job_id)  # type: ignore[misc]
                        assert suggestions == WAITING
                        assert dismissed == ["fedcba9876543210"]
                        assert state == "done" and inputs is None
                    assert tuple(read(line_sql, archived_line)) == (None, [], None, None)  # type: ignore[arg-type]
                    revision.downgrade()
                    assert tuple(read(agent_sql, agent_id)) == (WAITING,)  # type: ignore[arg-type]
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
