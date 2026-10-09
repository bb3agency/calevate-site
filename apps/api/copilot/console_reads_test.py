"""D-698: the console read tools — what they return, whose rows they can see, who may run
them, and that they change nothing. Every test mints its own tenant."""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import service, tools
from apps.api.copilot.console_reads import CONSOLE_READ_TOOL_NAMES, CONSOLE_READ_TOOLS
from apps.api.db.session import tenant_session


async def _first(tenant_id: UUID, table: str) -> str:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text(f"SELECT id FROM {table} LIMIT 1"))).first()
    assert row is not None
    return str(row[0])


async def _read(name: str, tenant_id: UUID, role: str = "owner", **args: Any) -> str:
    return await tools.run_read_tool(
        name,
        json.dumps(args),
        context=tools.ToolContext(tenant_id=tenant_id, role=role),
        registry=service._read_tool_registry("client"),
    )


def test_the_console_reads_follow_the_first_reads_in_both_realms() -> None:
    client = [tool.name for tool in service.realm_read_tools("client")]
    admin = [tool.name for tool in service.realm_read_tools("admin")]
    console = [tool.name for tool in CONSOLE_READ_TOOLS]
    assert client == [*[t.name for t in tools.READ_TOOLS], *console]
    assert admin[-len(client) :] == client
    assert not CONSOLE_READ_TOOL_NAMES & tools.READ_TOOL_NAMES


def test_no_console_read_can_change_anything() -> None:
    for tool in CONSOLE_READ_TOOLS:
        source = inspect.getsource(tool.run).lower()
        for verb in ("insert into", "update ", "delete from", "session.add", "commit("):
            assert verb not in source, f"{tool.name} looks like it writes"


def test_every_console_read_schema_is_strict_shaped() -> None:
    for tool in CONSOLE_READ_TOOLS:
        params = tool.parameters
        assert params["additionalProperties"] is False, tool.name
        assert sorted(params["required"]) == sorted(params["properties"]), tool.name


async def test_agent_detail_names_the_notices_and_the_truthful_answer() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _first(tenant_id, "agents")
    result = await _read("agent_detail", tenant_id, agent_id=agent_id)
    assert "Agent Reception" in result
    assert "always answers truthfully" in result
    assert f"[agent_id {agent_id}]" in result


async def test_a_neighbours_object_is_not_found_from_every_detail_read() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    other_id, _s, _t = await _make_tenant()
    for name, key, table in (
        ("agent_detail", "agent_id", "agents"),
        ("lead_detail", "lead_id", "leads"),
    ):
        result = await _read(name, tenant_id, **{key: await _first(other_id, table)})
        assert result.startswith("No "), (name, result)
    missing = await _read("call_detail", tenant_id, call_id=str(uuid.uuid4()))
    assert missing == "No call with that id in this account."
    assert "missing" in await _read("campaign_detail", tenant_id, campaign_id="not-an-id")


async def test_lead_detail_masks_the_number_and_lists_field_names_only() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _first(tenant_id, "leads")
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(
                text("SELECT phone_e164 FROM leads WHERE id = :i"), {"i": lead_id}
            )
        ).scalar()
        await session.execute(
            text("UPDATE leads SET data = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({"budget": "40 lakh"}), "i": lead_id},
        )
    result = await _read("lead_detail", tenant_id, lead_id=lead_id)
    assert str(phone) not in result
    assert "budget" in result and "40 lakh" not in result


async def test_call_detail_returns_the_redacted_transcript_and_no_recording_link() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    agent_id = await _first(tenant_id, "agents")
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, summary, started_at, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500002', 'completed', 'Asked for a quote.', "
                "now(), now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"cd_{uuid.uuid4().hex[:10]}"},
        )
    result = await _read("call_detail", tenant_id, call_id=str(call_id))
    assert "Asked for a quote." in result
    assert "There is no recording of this call." in result
    assert "+919876500002" not in result and "http" not in result


@pytest.mark.parametrize(
    "name",
    [
        "calls_live",
        "callbacks_list",
        "knowledge_sources",
        "billing_overview",
        "verification_status",
        "integrations_status",
        "needs_attention",
        "quality_reports",
        "team_members",
    ],
)
async def test_each_account_read_answers_a_fresh_account_in_a_sentence(name: str) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    args: dict[str, Any] = {}
    if name == "callbacks_list":
        args = {"open_only": None, "limit": None}
    if name == "needs_attention":
        args = {"limit": None}
    result = await _read(name, tenant_id, **args)
    assert result and "could not be read" not in result, result


async def test_verification_status_explains_and_never_offers_to_accept() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    result = await _read("verification_status", tenant_id)
    assert "not started" in result
    assert "Only the owner accepts it" in result
    assert "cannot upload documents or accept anything" in result


async def test_team_members_names_ids_and_never_emails() -> None:
    tenant_id, _slug, token = await _make_tenant()
    result = await _read("team_members", tenant_id)
    assert f"[user_id {UUID(token.rsplit(':', 1)[1])}]" in result
    assert "@example.com" not in result


async def test_a_role_without_the_screens_permission_reads_nothing() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    for tool in CONSOLE_READ_TOOLS:
        result = await _read(tool.name, tenant_id, role="ghost")
        assert result.startswith("Refused"), tool.name
