"""Client in-call actions on ThinnestAI (D-700): registered as the agent's custom actions,
kept in step with what is live here, and executed through the one in-call door.

Uses the in-memory vendor of `thinnest_in_call_actions_test` (documented action shapes,
snapshots/2026-10-07 and 2026-10-08). SHARED DATABASE DISCIPLINE: every row is minted here.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.actions import credentials as creds
from apps.api.actions import in_call, service
from apps.api.actions.execution import ExecutionResult
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_actions import CALL_ID_FIELD, CALL_ID_HEADER, SECRET_HEADER
from apps.api.main import app as api_app
from apps.api.reliability.engine_actions import (
    ACTION_NAMES,
    CLIENT_DESCRIPTION_SUFFIX,
    THINNEST_CLIENT_ACTIONS_MAX,
    retire_agent_actions,
    sync_client_actions_now,
)
from apps.api.worker.engine_actions import NO_CALL_SAY
from sqlalchemy import text
from tests import thinnest_in_call_actions_test as base
from tests.thinnest_in_call_actions_test import (
    ENGINE,
    FakeThinnest,
    _ensure,
    _live,
    _published,
)

#: The in-memory vendor fixture of the platform-tools suite, reused under its own name.
vendor = base.vendor

pytestmark = [pytest.mark.rls]


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(url: str, *, field: str = "url") -> None:
        return None

    monkeypatch.setattr(service, "assert_public_http_url", _ok)


async def _add_tool(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str, *, master: bool = True, **kw: Any
) -> service.LoadedTool:
    async with tenant_session(tenant_id) as session:
        tool = await service.create_tool(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            kind=kw.get("kind", "custom_api"),
            provider=kw.get("provider"),
            name=name,
            description="Look up the caller's order by its number.",
            trigger="during_call",
            pre_call_message=kw.get("pre_call_message", "One moment, let me check."),
            credential_id=None,
            params=[
                {"name": "order_no", "source": "ai", "description": "The order number."},
                {"name": "who", "source": "lead_var", "lead_var": "caller_phone"},
            ],
            config={
                "method": "POST",
                "url": "https://api.shop.example/orders",
                "body": [{"key": "order", "param": "order_no"}, {"key": "phone", "param": "who"}],
            },
        )
        await service.set_actions_enabled(session, agent_id=agent_id, enabled=master)
    return tool


def _client_actions(vendor: FakeThinnest, ref: str) -> dict[str, dict[str, Any]]:
    held = vendor.actions.get(ref, {})
    return {a["name"]: a for a in held.values() if "/client/" in a["url"]}


async def test_a_live_action_is_registered_on_the_agent_with_our_header_and_its_line(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    await _add_tool(tenant_id, agent_id, "look_up_order")
    await _ensure(tenant_id, ref)
    (action,) = _client_actions(vendor, ref).values()
    assert action["url"].endswith(
        f"/v1/worker/engine-actions/{ENGINE}/client/look_up_order?agent={ref}"
    )
    assert action["description"].endswith(CLIENT_DESCRIPTION_SUFFIX)
    # Only what the model fills is declared; the caller's number is ours to apply.
    assert [p["name"] for p in action["parameters"]] == ["order_no"]
    assert action["speakBefore"] == "One moment, let me check."
    assert action["enabled"] is True
    assert vendor.sealed[action["id"]] == {SECRET_HEADER: secret}
    # The platform's own four are still there.
    names = {a["name"] for a in vendor.actions[ref].values()}
    assert set(ACTION_NAMES.values()) - {ACTION_NAMES["handoff"]} <= names


async def test_switching_an_action_off_removes_it_from_the_live_agent_at_once(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, _secret = await _published(vendor)
    tool = await _add_tool(tenant_id, agent_id, "look_up_order")
    await _ensure(tenant_id, ref)
    assert _client_actions(vendor, ref)
    async with tenant_session(tenant_id) as session:
        await service.set_enabled(session, agent_id=agent_id, tool_id=tool.id, enabled=False)
        assert await sync_client_actions_now(session, agent_id=agent_id) == "synced"
    assert _client_actions(vendor, ref) == {}
    # A console-made action and ours are untouched.
    assert len(vendor.actions[ref]) >= 3


async def test_the_master_switch_off_removes_every_client_action(vendor: FakeThinnest) -> None:
    tenant_id, agent_id, ref, _secret = await _published(vendor)
    await _add_tool(tenant_id, agent_id, "look_up_order")
    await _add_tool(tenant_id, agent_id, "check_stock")
    await _ensure(tenant_id, ref)
    assert len(_client_actions(vendor, ref)) == 2
    async with tenant_session(tenant_id) as session:
        await service.set_actions_enabled(session, agent_id=agent_id, enabled=False)
        await sync_client_actions_now(session, agent_id=agent_id)
    assert _client_actions(vendor, ref) == {}


async def test_more_actions_than_the_agent_may_carry_is_refused_by_name(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, _secret = await _published(vendor)
    for n in range(THINNEST_CLIENT_ACTIONS_MAX + 1):
        await _add_tool(tenant_id, agent_id, f"tool_number_{n}")
    with pytest.raises(ProblemError) as caught:
        await _ensure(tenant_id, ref)
    assert caught.value.code == "client_actions_over_limit"


async def test_unpublishing_removes_client_actions_too(vendor: FakeThinnest) -> None:
    tenant_id, agent_id, ref, _secret = await _published(vendor)
    await _add_tool(tenant_id, agent_id, "look_up_order")
    await _ensure(tenant_id, ref)
    removed = await retire_agent_actions(engine=ENGINE, engine_agent_ref=ref)
    assert removed >= 4
    assert _client_actions(vendor, ref) == {}


# --- the route ---------------------------------------------------------------------------


async def _post_client(
    name: str, ref: str, secret: str | None, body: dict[str, Any], *, call_id: str | None = None
) -> httpx.Response:
    headers = {SECRET_HEADER: secret} if secret is not None else {}
    if call_id is not None:
        headers[CALL_ID_HEADER] = call_id
        body = {CALL_ID_FIELD: call_id, **body}
    transport = httpx.ASGITransport(app=api_app, client=("127.0.0.1", 44444))
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as raw:
        return await raw.post(
            f"/v1/worker/engine-actions/{ENGINE}/client/{name}?agent={ref}",
            content=json.dumps(body),
            headers={**headers, "Content-Type": "application/json"},
        )


async def test_a_client_action_without_the_agents_secret_is_401(vendor: FakeThinnest) -> None:
    _tenant, _agent, ref, _secret = await _published(vendor)
    assert (await _post_client("look_up_order", ref, "wrong", {})).status_code == 401
    assert (await _post_client("look_up_order", ref, None, {})).status_code == 401


async def test_the_vendors_own_test_runs_nothing(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    await _add_tool(tenant_id, agent_id, "look_up_order")
    ran: list[Any] = []

    async def _never(*a: Any, **k: Any) -> Any:
        ran.append(k)

    monkeypatch.setattr(in_call, "execute_action", _never)
    response = await _post_client("look_up_order", ref, secret, {"order_no": "A1"})
    assert response.status_code == 200
    assert response.json() == {"status": "no_call", "say": NO_CALL_SAY}
    assert ran == []


async def test_a_live_call_runs_the_action_with_the_vendors_number_for_the_caller(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    await _add_tool(tenant_id, agent_id, "look_up_order")
    call_id, row = _live(ref, phone="919876522201")
    vendor.live.append(row)
    seen: dict[str, Any] = {}

    async def _fake(session: Any, **kw: Any) -> ExecutionResult:
        seen.update(kw)
        return ExecutionResult(
            ok=True, payload={"found": True, "details": {"status": "shipped"}}, status="found"
        )

    monkeypatch.setattr(in_call, "execute_action", _fake)
    response = await _post_client(
        "look_up_order", ref, secret, {"order_no": "A1", "who": "+910000000000"}, call_id=call_id
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found" and body["details"] == {"status": "shipped"}
    assert body["say"]
    assert seen["call"].caller_e164 == "+919876522201"
    assert seen["source"] == "in_call"
    assert seen["budget_s"] == in_call.IN_CALL_BUDGET_S
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT agent_id FROM calls WHERE engine_call_id = :e"), {"e": call_id}
            )
        ).all()
    assert rows == [(agent_id,)]


async def test_a_switched_off_action_answers_that_it_cannot_be_done(
    vendor: FakeThinnest,
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    tool = await _add_tool(tenant_id, agent_id, "look_up_order")
    async with tenant_session(tenant_id) as session:
        await service.set_enabled(session, agent_id=agent_id, tool_id=tool.id, enabled=False)
    call_id, row = _live(ref, phone="919876522202")
    vendor.live.append(row)
    body = (await _post_client("look_up_order", ref, secret, {}, call_id=call_id)).json()
    assert body == {"status": "unavailable", "say": in_call.NOT_AVAILABLE_SAY}


async def test_a_slow_write_is_acknowledged_and_queued(
    vendor: FakeThinnest, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id, ref, secret = await _published(vendor)
    async with tenant_session(tenant_id) as session:
        cred = await creds.create_credential(
            session,
            tenant_id=tenant_id,
            kind="zoho_crm",
            label="Zoho",
            secret="refresh-1234",
            non_secret={"api_domain": "https://www.zohoapis.in"},
        )
        await service.create_tool(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            kind="crm",
            provider="zoho",
            name="save_to_zoho",
            description="Save the caller's details to the CRM once you have their name.",
            trigger="during_call",
            pre_call_message=None,
            credential_id=cred.id,
            params=[{"name": "name", "source": "ai", "description": "Caller's last name."}],
            config={"module": "Leads", "fields": [{"crm_field": "Last_Name", "param": "name"}]},
        )
        await service.set_actions_enabled(session, agent_id=agent_id, enabled=True)
    queued: list[tuple[str, dict[str, Any]]] = []

    async def _enqueue(job: str, payload: dict[str, Any], **_: Any) -> str:
        queued.append((job, payload))
        return "job"

    monkeypatch.setattr(in_call, "enqueue", _enqueue)
    call_id, row = _live(ref, phone="919876522203")
    vendor.live.append(row)
    body = (
        await _post_client("save_to_zoho", ref, secret, {"name": "Rao"}, call_id=call_id)
    ).json()
    assert body["status"] == "accepted"
    ((job, payload),) = queued
    assert job == in_call.CLIENT_ACTION_JOB
    assert payload["args"] == {"name": "Rao"}
    # The caller's number never travels in the queue; the job reads it from the call row.
    assert "919876522203" not in json.dumps(payload)


async def test_a_view_as_operator_cannot_switch_an_action_on() -> None:
    from apps.api.core.auth import assert_view_as_may
    from apps.api.core.context import Principal

    principal = Principal(
        realm="admin",
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role="admin",
        impersonating=True,
    )
    with pytest.raises(ProblemError):
        assert_view_as_may(principal, "actions.switch_on")
    with pytest.raises(ProblemError):
        assert_view_as_may(principal, "integrations.connect")


async def test_an_inbound_lookup_runs_under_the_opening_line_with_no_filler(
    vendor: FakeThinnest,
) -> None:
    from apps.api.reliability.engine_actions import CALLER_LOOKUP_TIMING

    tenant_id, agent_id, ref, _secret = await _published(vendor)
    async with tenant_session(tenant_id) as session:
        await service.create_tool(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            kind="caller_lookup",
            provider="sheet",
            name="look_up_caller",
            description="Find out who is calling from the client sheet.",
            trigger="during_call",
            pre_call_message="Let me check.",
            credential_id=None,
            params=[],
            config={
                "spreadsheet_id": "a" * 44,
                "worksheet": "Customers",
                "match_header": "Phone",
                "return_headers": ["Name"],
            },
        )
        await service.set_actions_enabled(session, agent_id=agent_id, enabled=True)
    await _ensure(tenant_id, ref)
    action = _client_actions(vendor, ref)["look_up_caller"]
    assert action["speakBefore"] is None
    assert CALLER_LOOKUP_TIMING in action["description"]
    assert action["parameters"] == []
