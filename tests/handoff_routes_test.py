"""The client's handover screen, over HTTP (D-533, D-695).

The list is a SELECTION from the business's one escalation roster: names and numbers are
kept on the business profile, and each agent says only who of them it may put a caller
through to, in what order. Two things are worth asserting through the route:

* **The whole list is one write**, so a re-order and a removal land together or not at all.
* **The read answers "and is it working right now"**, which is the question the screen is
  for: it depends on the switch, on who is active, and on a clock.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.admin import service as admin_service
from apps.api.agents.handoff import HANDOFF_TRIGGER_DEFAULT, MAX_HANDOFF_MEMBERS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, business_contact


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _account(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
    """A client whose business profile is open round the clock (`accept_agreements`), so
    "who is on duty" is decided by the roster rather than by the hour this suite runs."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Handoff routes",
        slug=f"handoff-rt-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, agent_id, {"Authorization": f"Bearer dev:client:{user_id}"}


async def _member(tenant_id: uuid.UUID, label: str, phone: str, **kw: Any) -> dict[str, Any]:
    contact_id = await business_contact(tenant_id, phone=phone, label=label)
    return {"contact_id": str(contact_id), **kw}


async def test_the_roster_round_trips_and_the_order_is_the_order_chosen() -> None:
    tenant_id, agent_id, headers = await _account()
    members = [
        await _member(tenant_id, "Ravi", "+919000000001"),
        await _member(tenant_id, "Priya", "+919000000002"),
    ]
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": members},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["label"] for m in body["members"]] == ["Ravi", "Priya"]
    assert [m["contact_id"] for m in body["members"]] == [m["contact_id"] for m in members]
    assert [m["position"] for m in body["members"]] == [0, 1]
    # POSITION 0 IS WHO ANSWERS.
    assert body["on_duty_member_id"] == body["members"][0]["id"]
    assert body["members"][0]["on_duty"] is True
    assert body["members"][1]["on_duty"] is False
    assert body["unavailable_reason"] is None
    assert body["trigger"] is None
    assert body["effective_trigger"] == HANDOFF_TRIGGER_DEFAULT
    assert body["spoken_line"]


async def test_an_agent_may_take_a_subset_of_the_business_roster() -> None:
    tenant_id, agent_id, headers = await _account()
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    await _member(tenant_id, "Priya", "+919000000002")
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [ravi]},
            headers=headers,
        )
    assert [m["label"] for m in response.json()["members"]] == ["Ravi"]


async def test_a_reorder_and_a_removal_are_one_write() -> None:
    tenant_id, agent_id, headers = await _account()
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    priya = await _member(tenant_id, "Priya", "+919000000002")
    sunil = await _member(tenant_id, "Sunil", "+919000000003")
    async with _client() as client:
        await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [ravi, priya, sunil]},
            headers=headers,
        )
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [priya, {**ravi, "active": False}]},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["label"] for m in body["members"]] == ["Priya", "Ravi"]
    assert body["members"][1]["active"] is False
    assert body["on_duty_member_id"] == body["members"][0]["id"]


async def test_the_same_person_twice_is_refused_rather_than_normalised() -> None:
    tenant_id, agent_id, headers = await _account()
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [ravi, ravi]},
            headers=headers,
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("handoff_duplicate_contact")


async def test_switching_it_on_with_nobody_on_the_list_is_refused() -> None:
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": []},
            headers=headers,
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("handoff_no_members")


async def test_an_eleventh_person_is_refused_at_the_boundary() -> None:
    tenant_id, agent_id, headers = await _account()
    members = [
        await _member(tenant_id, f"P{i}", f"+9190000001{i:02d}")
        for i in range(MAX_HANDOFF_MEMBERS + 1)
    ]
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": members},
            headers=headers,
        )
    assert response.status_code == 422


async def test_a_contact_that_is_not_on_file_is_refused_and_nothing_is_written() -> None:
    tenant_id, agent_id, headers = await _account()
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    async with _client() as client:
        refused = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [ravi, {"contact_id": str(uuid.uuid4())}]},
            headers=headers,
        )
        after = await client.get(f"/v1/agents/{agent_id}/handoff", headers=headers)
    assert refused.status_code == 404, refused.text
    assert after.json()["members"] == []


async def test_the_read_says_why_nobody_is_on_duty_and_what_to_do_about_it() -> None:
    tenant_id, agent_id, headers = await _account()
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    async with _client() as client:
        await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": False, "members": [ravi]},
            headers=headers,
        )
        response = await client.get(f"/v1/agents/{agent_id}/handoff", headers=headers)
    body = response.json()
    assert body["on_duty_member_id"] is None
    assert body["unavailable_reason"] == "disabled"
    assert body["remediation"]
    assert body["published"] is False, "this agent has never been published"


async def test_a_staff_member_may_read_the_list_and_not_rewrite_it() -> None:
    tenant_id, agent_id, headers = await _account(role="staff")
    ravi = await _member(tenant_id, "Ravi", "+919000000001")
    async with _client() as client:
        read = await client.get(f"/v1/agents/{agent_id}/handoff", headers=headers)
        write = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [ravi]},
            headers=headers,
        )
    assert read.status_code == 200
    assert write.status_code == 403


async def test_another_tenants_agent_is_not_reachable_through_the_path() -> None:
    _first_tenant, first_agent, _first_headers = await _account()
    _second_tenant, _second_agent, second_headers = await _account()
    async with _client() as client:
        response = await client.get(f"/v1/agents/{first_agent}/handoff", headers=second_headers)
    assert response.status_code == 404
