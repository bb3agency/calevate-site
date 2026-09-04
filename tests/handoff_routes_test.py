"""The client's handover screen, over HTTP (D-533).

The two things worth asserting through the route rather than through the service:

* **The whole list is one write**, so a re-order and a removal land together or not at all.
  Four requests over rows can half-apply, and the half-applied states are two people at
  position 1 (which the unique index refuses, so a sensible edit becomes a 500) or a roster
  that is briefly empty — which, if a call lands in that instant, is a caller told nobody
  is available.
* **The read answers "and is it working right now"**, which is the question the screen is
  for. A list of names does not tell a shop owner whether their next caller will reach a
  person: that depends on the switch, on who is active, and on a clock.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.handoff import HANDOFF_TRIGGER_DEFAULT, MAX_HANDOFF_MEMBERS
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

pytestmark = pytest.mark.asyncio

OPEN_ALL_WEEK = {
    day: {"opens": "00:00", "closes": "23:59"}
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _account(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
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
        # Open all week, so "who is on duty" is decided by the roster rather than by the
        # hour this suite happens to run at.
        await session.execute(
            text("UPDATE agents SET business_hours = CAST(:h AS jsonb) WHERE id = :aid"),
            {"h": json.dumps(OPEN_ALL_WEEK), "aid": agent_id},
        )
    return tenant_id, agent_id, {"Authorization": f"Bearer dev:client:{user_id}"}


def _member(label: str, phone: str, **kw: Any) -> dict[str, Any]:
    return {"label": label, "phone_e164": phone, **kw}


async def test_the_roster_round_trips_and_the_order_is_the_order_typed() -> None:
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={
                "enabled": True,
                "members": [
                    _member("Ravi", "+919000000001"),
                    _member("Priya", "+919000000002"),
                ],
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["label"] for m in body["members"]] == ["Ravi", "Priya"]
    assert [m["position"] for m in body["members"]] == [0, 1]
    # POSITION 0 IS WHO ANSWERS. The later rung is reached because the earlier one is off
    # duty or switched off — never because they did not pick up.
    assert body["on_duty_member_id"] == body["members"][0]["id"]
    assert body["members"][0]["on_duty"] is True
    assert body["members"][1]["on_duty"] is False
    assert body["unavailable_reason"] is None
    # The default trigger is SHOWN rather than left as an empty box implying nothing
    # happens.
    assert body["trigger"] is None
    assert body["effective_trigger"] == HANDOFF_TRIGGER_DEFAULT
    assert body["spoken_line"]


async def test_a_reorder_and_a_removal_are_one_write() -> None:
    """ "Move Priya above Ravi and take Ravi off while he is away" is ONE intention."""
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={
                "enabled": True,
                "members": [
                    _member("Ravi", "+919000000001"),
                    _member("Priya", "+919000000002"),
                    _member("Sunil", "+919000000003"),
                ],
            },
            headers=headers,
        )
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={
                "enabled": True,
                "members": [
                    _member("Priya", "+919000000002"),
                    _member("Ravi", "+919000000001", active=False),
                ],
            },
            headers=headers,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["label"] for m in body["members"]] == ["Priya", "Ravi"]
    assert body["members"][1]["active"] is False
    assert body["on_duty_member_id"] == body["members"][0]["id"]


async def test_the_same_number_twice_is_refused_rather_than_normalised() -> None:
    """One person cannot be two rungs of a hunt list, and whichever copy is second is
    unreachable — so the client is told, on a screen where a person is looking."""
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={
                "enabled": True,
                "members": [
                    _member("Ravi", "+919000000001"),
                    _member("Ravi's other phone", "+919000000001"),
                ],
            },
            headers=headers,
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("handoff_duplicate_number")


async def test_switching_it_on_with_nobody_on_the_list_is_refused() -> None:
    """An agent that promises a caller a person and has none is the state this refusal
    exists to make unreachable."""
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
    """A bounded list, because the roster is read on every publish and a pasted contact
    export must not turn one publish into a thousand-row scan."""
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={
                "enabled": True,
                "members": [
                    _member(f"P{i}", f"+9190000001{i:02d}") for i in range(MAX_HANDOFF_MEMBERS + 1)
                ],
            },
            headers=headers,
        )
    assert response.status_code == 422


async def test_a_number_that_is_not_e164_never_reaches_the_column() -> None:
    """Doubled with the column's own CHECK deliberately: this number is DIALLED."""
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        response = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [_member("Ravi", "9000000001")]},
            headers=headers,
        )
    assert response.status_code == 422


async def test_the_read_says_why_nobody_is_on_duty_and_what_to_do_about_it() -> None:
    """Five causes, four of them a minute's work for the client. A screen that collapsed
    them into one silence would leave them with a feature that does not work and no
    sentence explaining it."""
    _tenant_id, agent_id, headers = await _account()
    async with _client() as client:
        await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": False, "members": [_member("Ravi", "+919000000001")]},
            headers=headers,
        )
        response = await client.get(f"/v1/agents/{agent_id}/handoff", headers=headers)
    body = response.json()
    assert body["on_duty_member_id"] is None
    assert body["unavailable_reason"] == "disabled"
    assert body["remediation"]
    assert body["published"] is False, "this agent has never been published"


async def test_a_staff_member_may_read_the_list_and_not_rewrite_it() -> None:
    """`agents:read` to see it, `org:manage` to change it. Putting a named person's
    personal mobile on a list that will be DIALLED is an owner's decision — and `org:manage`
    is what every other client-realm agent-configuration write already declares, so the
    boundary here is the product's existing one rather than a new opinion."""
    _tenant_id, agent_id, headers = await _account(role="staff")
    async with _client() as client:
        read = await client.get(f"/v1/agents/{agent_id}/handoff", headers=headers)
        write = await client.put(
            f"/v1/agents/{agent_id}/handoff",
            json={"enabled": True, "members": [_member("Ravi", "+919000000001")]},
            headers=headers,
        )
    assert read.status_code == 200
    assert write.status_code == 403


async def test_another_tenants_agent_is_not_reachable_through_the_path() -> None:
    """`assert_visible` before anything else, so naming a neighbour's agent is a 404 rather
    than an edit."""
    _first_tenant, first_agent, _first_headers = await _account()
    _second_tenant, _second_agent, second_headers = await _account()
    async with _client() as client:
        response = await client.get(f"/v1/agents/{first_agent}/handoff", headers=second_headers)
    assert response.status_code == 404
