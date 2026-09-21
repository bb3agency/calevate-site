"""The sender can actually record the notice every outbound dial depends on.

THE DEFECT THIS PINS. `autodialer_notice_blocker` was wired into `check_dispatch` and
refuses every outbound dial for a tenant with no notice on file — and for one release
`record_autodialer_notice` had NO CALLER anywhere in the product: no route, no client
screen, no admin screen. The gate was unconditional and unclearable, while the readiness
row told the client to "record the date here" for a here that did not exist. These tests
exist so that a route nobody mounted cannot be that silent again.

Run: uv run pytest -q tests/autodialer_notice_route_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.autodialer import autodialer_notice_blocker
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

PATH = "/v1/compliance/autodialer-notice"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> str:
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
    return f"dev:client:{user_id}"


async def _tenant() -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="Notice Motors",
        slug=f"note-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    await accept_agreements(uuid.UUID(str(created["id"])))
    return created


async def _headers(org: dict[str, Any], role: str = "owner") -> dict[str, str]:
    token = await _member(uuid.UUID(str(org["id"])), role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])}


def _body(**over: Any) -> dict[str, Any]:
    return {
        "access_provider": "Airtel",
        "objective": "Delivery reminders for orders our customers placed",
        "notified_on": "2026-09-01",
        **over,
    }


@pytest.mark.asyncio
async def test_an_account_with_nothing_on_file_reads_as_not_recorded() -> None:
    """A 200 with `recorded: false`, never a 404 — it is the state of every new account,
    and a 404 arrives at the fetch layer indistinguishable from a moved route."""
    org = await _tenant()
    async with _client() as http:
        response = await http.get(PATH, headers=await _headers(org))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is False
    assert body["effective"] is False


@pytest.mark.asyncio
async def test_recording_a_notice_opens_the_gate_that_was_refusing_every_dial() -> None:
    """THE WHOLE POINT, asserted through the gate and not through the response.

    The route could return anything it liked; what matters is that
    `autodialer_notice_blocker` — the predicate `check_dispatch` actually calls — stops
    refusing. Asserting the response alone would pass on a route that wrote nothing.
    """
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))

    async with tenant_session(tenant_id) as session:
        assert await autodialer_notice_blocker(session, tenant_id=tenant_id) is not None

    async with _client() as http:
        response = await http.post(PATH, headers=await _headers(org), json=_body())
    assert response.status_code == 201, response.text
    assert response.json()["effective"] is True

    async with tenant_session(tenant_id) as session:
        assert await autodialer_notice_blocker(session, tenant_id=tenant_id) is None


@pytest.mark.asyncio
async def test_a_notice_dated_in_the_future_is_kept_and_still_holds_outbound() -> None:
    """A client who wrote to their provider today naming next Monday has done the right
    thing. Recording it must not open the gate early, and refusing the write would push
    them to record a date they did not write — worse evidence than a true one."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    ahead = (datetime.now(UTC) + timedelta(days=7)).date().isoformat()

    async with _client() as http:
        response = await http.post(PATH, headers=await _headers(org), json=_body(notified_on=ahead))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["recorded"] is True
    assert body["state"] == "notified"
    assert body["effective"] is False, "a future notice must not carry outbound yet"

    async with tenant_session(tenant_id) as session:
        blocker = await autodialer_notice_blocker(session, tenant_id=tenant_id)
    assert blocker is not None
    assert blocker[0] == "autodialer_notice_not_yet_effective"


@pytest.mark.asyncio
async def test_withdrawing_stops_outbound_and_keeps_the_notice_that_was_live() -> None:
    """Hard rule 4 on the sender's own declaration: a withdrawal is a NEW row, so the
    history still shows the notice was live while last month's calls were placed."""
    org = await _tenant()
    tenant_id = uuid.UUID(str(org["id"]))
    headers = await _headers(org)

    async with _client() as http:
        await http.post(PATH, headers=headers, json=_body())
        withdrawn = await http.post(PATH, headers=headers, json=_body(withdraw=True))
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["state"] == "withdrawn"
    assert withdrawn.json()["effective"] is False

    async with tenant_session(tenant_id) as session:
        blocker = await autodialer_notice_blocker(session, tenant_id=tenant_id)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM autodialer_notices WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert blocker is not None
    assert blocker[0] == "autodialer_notice_withdrawn"
    assert rows == 2, "the withdrawal is a second row, never an edit of the first"


@pytest.mark.asyncio
async def test_staff_may_look_but_not_record() -> None:
    """`staff` deliberately does not hold `org:manage` — the role exists so a client's own
    team can run the phone line without reaching billing, members and account settings.

    Recording the notice is a DECLARATION BY THE BUSINESS to its own access provider,
    which is the owner's to make, so it sits on the mutating permission rather than on the
    one that lets staff change a voice. Reading stays open, because the person who notices
    nothing is dialling is as likely to be staff as the owner.
    """
    org = await _tenant()
    headers = await _headers(org, role="staff")
    async with _client() as http:
        seen = await http.get(PATH, headers=headers)
        refused = await http.post(PATH, headers=headers, json=_body())
    assert seen.status_code == 200, seen.text
    assert refused.status_code == 403, refused.text


@pytest.mark.asyncio
async def test_a_neighbour_cannot_read_or_write_this_accounts_notice() -> None:
    """Hard rule 1 on a compliance declaration: one account's notice is not another's."""
    mine = await _tenant()
    theirs = await _tenant()
    async with _client() as http:
        await http.post(PATH, headers=await _headers(mine), json=_body())
        seen = await http.get(PATH, headers=await _headers(theirs))
    assert seen.status_code == 200, seen.text
    assert seen.json()["recorded"] is False, "a neighbour's notice must not be visible"


@pytest.mark.asyncio
async def test_the_refusals_name_the_field_that_is_wrong() -> None:
    """Two fields, two codes. A client fixing the wrong one learns nothing."""
    org = await _tenant()
    headers = await _headers(org)
    async with _client() as http:
        blank = await http.post(PATH, headers=headers, json=_body(access_provider="   "))
        long_ref = await http.post(PATH, headers=headers, json=_body(notice_reference="x" * 400))
    assert blank.status_code == 422, blank.text
    assert long_ref.status_code == 422, long_ref.text
