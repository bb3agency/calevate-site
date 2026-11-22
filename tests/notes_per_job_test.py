"""D-1028: what a call notes belongs to its job (a campaign or an inbound line), not its agent.

1. The data step copies an agent's list into each of its campaigns and lines that had none,
   and leaves a list of their own alone.
2. A new campaign or line starts with the business's starting set (D-1029).
3. An inbound line's list has its own API: read, a whole-list save under a compare-and-set,
   the extraction rules, and another account's line answers 404 and holds zero rows.
4. The post-call pipeline notes the line's list for a line's call, the campaign's for a
   campaign's call (and its Test call), and only the core for a call with no job.
5. A line's engine agent asks for the line's list.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents import service as agents_service
from apps.api.campaigns import service as campaigns
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.main import app
from apps.workers.pipeline import _load_call_context
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript
from calevate_shared.lead_fields import CORE_KEYS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from tests.agent_lifecycle_test import _tenant
from tests.dispatch_budget_test import _dlt_rows

pytestmark = pytest.mark.rls

STEM = "e2a7c4f9b1d3_notes_per_job"
BUDGET = {"key": "budget", "label": "Budget", "type": "text", "reason": "to quote"}
AREA = {"key": "area", "label": "Area", "type": "text", "reason": "where they live"}


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _agent_keys(tenant_id: UUID, agent_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        raw = (
            await session.execute(
                text(
                    "SELECT es.fields FROM agents a JOIN extraction_schemas es "
                    "ON es.id = a.extraction_schema_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
    return [f["key"] for f in raw]


async def _keys(tenant_id: UUID, table: str, job_id: UUID) -> list[str]:
    sql = {
        "campaigns": "SELECT extraction_fields FROM campaigns WHERE id = :j",
        "inbound_lines": "SELECT extraction_fields FROM inbound_lines WHERE id = :j",
    }[table]
    async with tenant_session(tenant_id) as session:
        raw = (await session.execute(text(sql), {"j": job_id})).scalar_one()
    return [f["key"] for f in raw]


async def _campaign(tenant_id: UUID, agent_id: UUID) -> UUID:
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        return await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Follow-ups",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )


async def _line(tenant_id: UUID, agent_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )


async def _set_list(tenant_id: UUID, table: str, job_id: UUID, fields: list[Any]) -> None:
    sql = {
        "campaigns": "UPDATE campaigns SET extraction_fields = CAST(:f AS jsonb) WHERE id = :j",
        "inbound_lines": (
            "UPDATE inbound_lines SET extraction_fields = CAST(:f AS jsonb) WHERE id = :j"
        ),
    }[table]
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), {"f": json.dumps(fields), "j": job_id})


# --- 1 and 2: the data step and the starting list --------------------------------------


async def test_a_new_campaign_and_line_start_with_the_businesss_starting_set() -> None:
    """D-1029: whatever the agent's own list holds, a new job copies the business's set."""
    from apps.api.agents.lead_fields import starting_business_fields, vertical_of

    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE id = "
                "(SELECT extraction_schema_id FROM agents WHERE id = :a)"
            ),
            {"f": json.dumps([AREA]), "a": agent_id},
        )
        start = await starting_business_fields(
            session, tenant_id=tenant_id, vertical=await vertical_of(session, tenant_id=tenant_id)
        )
    starting_keys = [f.key for f in start]
    assert starting_keys, "the receptionist fixture's business type has a standard set"
    assert (
        await _keys(tenant_id, "campaigns", await _campaign(tenant_id, agent_id)) == starting_keys
    )
    assert (
        await _keys(tenant_id, "inbound_lines", await _line(tenant_id, agent_id)) == starting_keys
    )


async def test_the_data_step_copies_the_agents_list_only_into_empty_lists() -> None:
    revision = _revision()
    tenant_id, agent_id, _ = await _tenant()
    agent_keys = await _agent_keys(tenant_id, agent_id)
    empty_campaign = await _campaign(tenant_id, agent_id)
    own_campaign = await _campaign(tenant_id, agent_id)
    empty_line = await _line(tenant_id, agent_id)
    own_line = await _line(tenant_id, agent_id)
    await _set_list(tenant_id, "campaigns", empty_campaign, [])
    await _set_list(tenant_id, "campaigns", own_campaign, [BUDGET])
    await _set_list(tenant_id, "inbound_lines", empty_line, [])
    await _set_list(tenant_id, "inbound_lines", own_line, [AREA])

    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:

                def keys(table: str, job_id: UUID) -> list[str]:
                    connection.execute(
                        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
                    )
                    sql = {
                        "campaigns": "SELECT extraction_fields FROM campaigns WHERE id = :j",
                        "inbound_lines": (
                            "SELECT extraction_fields FROM inbound_lines WHERE id = :j"
                        ),
                    }[table]
                    raw = connection.execute(text(sql), {"j": str(job_id)}).scalar_one()
                    return [f["key"] for f in raw]

                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    assert keys("campaigns", empty_campaign) == agent_keys
                    assert keys("campaigns", own_campaign) == ["budget"]
                    assert keys("inbound_lines", empty_line) == agent_keys
                    assert keys("inbound_lines", own_line) == ["area"]
                    # The downgrade changes no data, and the chain runs back up.
                    revision.downgrade()
                    assert keys("campaigns", empty_campaign) == agent_keys
                    revision.upgrade()
            finally:
                transaction.rollback()
    finally:
        sync.dispose()


# --- 3: the line's notes API ------------------------------------------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_lines_list_is_read_and_saved_whole_under_its_digest() -> None:
    tenant_id, agent_id, token = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/v1/inbound-lines/{line_id}/notes"
    async with _client() as http:
        read = await http.get(path, headers=headers)
        assert read.status_code == 200, read.text
        body = read.json()
        assert [f["key"] for f in body["fields"]] == await _agent_keys(tenant_id, agent_id)
        assert {f["key"] for f in body["core_fields"]} == set(CORE_KEYS)
        assert body["applied_now"] is False

        saved = await http.put(
            path, json={"fields": [BUDGET], "expected_digest": body["digest"]}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        assert [f["key"] for f in saved.json()["fields"]] == ["budget"]

        stale = await http.put(
            path, json={"fields": [AREA], "expected_digest": body["digest"]}, headers=headers
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["type"].endswith("line_notes_changed_elsewhere")
        assert await _keys(tenant_id, "inbound_lines", line_id) == ["budget"]

        reserved = await http.put(
            path,
            json={"fields": [{"key": "phone", "label": "Phone", "type": "text"}]},
            headers=headers,
        )
        assert reserved.status_code == 422, reserved.text
        assert reserved.json()["type"].endswith("extraction_field_reserved_key")

    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'inbound_line.notes_saved' "
                    "AND object_id = :l"
                ),
                {"l": str(line_id)},
            )
        ).scalar_one()
    assert audited == 1


async def test_another_accounts_line_is_not_found_and_its_list_holds_zero_rows() -> None:
    tenant_a, agent_a, _ = await _tenant()
    _tenant_b, _agent_b, token_b = await _tenant()
    line_id = await _line(tenant_a, agent_a)
    headers = {"Authorization": f"Bearer {token_b}"}
    async with _client() as http:
        read = await http.get(f"/v1/inbound-lines/{line_id}/notes", headers=headers)
        write = await http.put(
            f"/v1/inbound-lines/{line_id}/notes", json={"fields": [BUDGET]}, headers=headers
        )
    assert read.status_code == 404
    assert write.status_code == 404
    async with tenant_session(_tenant_b) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    assert seen == 0
    assert await _keys(tenant_a, "inbound_lines", line_id) == await _agent_keys(tenant_a, agent_a)


# --- 4: what the pipeline notes ---------------------------------------------------------


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    campaign_id: UUID | None = None,
    line_id: UUID | None = None,
) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, inbound_line_id, "
                "engine_call_id, direction, status, from_e164, to_e164, started_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, :g, :l, :e, 'inbound', 'completed', "
                "'+919812345678', '+914000000000', now(), now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "g": campaign_id,
                "l": line_id,
                "e": f"npj-{call_id.hex}",
            },
        )
    return call_id


async def _noted(tenant_id: UUID, call_id: UUID) -> list[str]:
    spec = (await _load_call_context(tenant_id, call_id))[0]
    return [f.key for f in spec.fields if f.key not in CORE_KEYS]


async def test_each_call_notes_its_jobs_list_and_a_call_with_no_job_only_the_core() -> None:
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    await _set_list(tenant_id, "campaigns", campaign_id, [BUDGET])
    await _set_list(tenant_id, "inbound_lines", line_id, [AREA])

    assert await _noted(tenant_id, await _call(tenant_id, agent_id, line_id=line_id)) == ["area"]
    campaign_call = await _call(tenant_id, agent_id, campaign_id=campaign_id)
    assert await _noted(tenant_id, campaign_call) == ["budget"]
    # A campaign's Test call is kept on the campaign, not in `calls.campaign_id`.
    test_call = await _call(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET test_call_ids = array_append(test_call_ids, :c) WHERE id = :g"
            ),
            {"c": test_call, "g": campaign_id},
        )
    assert await _noted(tenant_id, test_call) == ["budget"]
    # The agent's own test call: only the core, whatever the agent's starting list holds.
    assert await _agent_keys(tenant_id, agent_id)
    assert await _noted(tenant_id, await _call(tenant_id, agent_id)) == []


# --- 5: what a line's calls ask for -----------------------------------------------------


async def test_a_lines_script_asks_for_the_lines_list() -> None:
    tenant_id, agent_id, _ = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _set_list(tenant_id, "inbound_lines", line_id, [BUDGET])
    async with tenant_session(tenant_id) as session:
        await lines.save_script(
            session,
            line_id,
            CallScript(
                schema_version=SCRIPT_SCHEMA_VERSION,
                opening_line="Namaste, how can I help you today?",
                goal="Book a visit.",
            ),
        )
        config = await agents_service.line_config(session, tenant_id=tenant_id, line_id=line_id)
    assert "Budget" in config.system_prompt
    assert uuid.UUID(config.agent_id) == agent_id


async def test_a_campaign_with_no_script_of_its_own_asks_for_the_campaigns_list() -> None:
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _set_list(tenant_id, "campaigns", campaign_id, [BUDGET])
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = NULL WHERE id = :c"), {"c": campaign_id}
        )
        agent = dict(await agents_service._load_agent(session, tenant_id, agent_id))
        agent["structured_script"] = CallScript(
            schema_version=SCRIPT_SCHEMA_VERSION,
            opening_line="Namaste, this is a quick follow-up call.",
            goal="Book a visit.",
        ).model_dump(mode="json")
        row = await agents_service.campaign_agent_row(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            agent=agent,  # type: ignore[arg-type]
        )
    assert "Budget" in row["prompt"]
