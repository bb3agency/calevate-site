"""Make a call (`POST /v1/one-calls`): one AI call to one person, by number, lead or call.

It is a door onto `crm/lead_dial` and the call-back booking, so what is proven here is what
the door adds and what it must not lose: a new person's lead is made only once the gate
allows the call; every refusal is the gate's 200 with a reason and no lead or call behind
it; a retry of one attempt rings once; a call later is one booked call-back row; and the
calls it places are the ones the screen's recent list reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.compliance.service import add_to_dnc
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from sqlalchemy import text
from tests.lead_dial_routes_test import (
    _client,
    _dialable_tenant,
    _finished_call,
    _lead,
    _outbound_calls,
    _staff_of,
)

#: 11:00 IST on a weekday, inside the calling window.
_DAYTIME = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _DAYTIME)


def _new_number() -> str:
    return f"+9197{uuid.uuid4().int % 100000000:08d}"


def _tomorrow_late_morning() -> datetime:
    """11:30 IST tomorrow: inside the window, past the two-minute minimum, within 30 days."""
    return (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )


def _ten_digits(e164: str) -> str:
    return e164.removeprefix("+91")


async def _leads_with(tenant_id: uuid.UUID, phone: str) -> list[tuple[str, str | None, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, name, source FROM leads WHERE phone_e164 = :p"), {"p": phone}
            )
        ).all()
    return [(str(r[0]), r[1], str(r[2])) for r in rows]


async def _post(headers: dict[str, str], body: dict[str, object], key: str | None = None):
    async with _client() as http:
        return await http.post(
            "/v1/one-calls",
            json=body,
            headers={**headers, "Idempotency-Key": key or f"one-{uuid.uuid4().hex[:12]}"},
        )


async def test_a_new_number_gets_a_lead_and_exactly_one_call_carrying_the_reason() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    phone = _new_number()

    response = await _post(
        headers,
        {
            "phone": _ten_digits(phone),
            "name": "Ravi",
            "agent_id": str(agent_id),
            "reason": "Confirm Saturday's visit",
            "details": "Prefers mornings",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued", body
    assert body["call_id"] and body["lead_id"]
    assert await _outbound_calls(tenant_id) == [(phone, "queued")]
    leads = await _leads_with(tenant_id, phone)
    assert leads == [(body["lead_id"], "Ravi", "manual")]
    async with tenant_session(tenant_id) as session:
        marked = (
            await session.execute(
                text("SELECT placed_by_person, lead_id FROM calls WHERE id = :id"),
                {"id": body["call_id"]},
            )
        ).one()
    assert marked[0] is True
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    contexts = [
        c["context"] for c in engine._calls.values() if c["context"]["lead_id"] == body["lead_id"]
    ]
    assert len(contexts) == 1
    assert contexts[0]["context_note"] == "Confirm Saturday's visit"
    assert contexts[0]["contact_details"].get("Note") == "Prefers mornings"


async def test_a_number_already_on_file_for_that_agent_is_called_as_that_lead() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)

    response = await _post(
        headers, {"phone": phone, "name": "Someone else", "agent_id": str(agent_id), "reason": "Hi"}
    )

    assert response.json()["status"] == "queued", response.text
    assert response.json()["lead_id"] == str(lead_id)
    assert await _leads_with(tenant_id, phone) == [(str(lead_id), "Priya", "inbound_call")], (
        "no second lead, and the name on file is not replaced"
    )


async def test_a_do_not_call_number_is_refused_and_leaves_no_lead_behind() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    phone = _new_number()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    for at in (None, _tomorrow_late_morning().isoformat()):
        body: dict[str, object] = {"phone": phone, "agent_id": str(agent_id), "reason": "Hi"}
        if at:
            body["at"] = at
        response = await _post(headers, body)
        assert response.status_code == 200, response.text
        out = response.json()
        assert out["status"] == "blocked" and out["blocked_rule"] == "dnc", out
        assert out["blocked_reason"]
    assert await _outbound_calls(tenant_id) == []
    assert await _leads_with(tenant_id, phone) == []


async def test_outside_calling_hours_the_refusal_names_the_next_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    monkeypatch.setattr(
        "apps.api.compliance.service.ist_now", lambda: datetime(2026, 8, 11, 22, 30, tzinfo=UTC)
    )

    response = await _post(
        headers, {"phone": _new_number(), "agent_id": str(agent_id), "reason": "Hi"}
    )

    out = response.json()
    assert out["status"] == "blocked" and out["blocked_rule"] == "calling_hours", out
    assert out["opens_at"], "the screen offers the next allowed time"
    assert "You can call from" in out["blocked_reason"]
    assert await _outbound_calls(tenant_id) == []


async def test_a_retry_of_one_attempt_rings_once() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    phone = _new_number()
    body = {"phone": phone, "agent_id": str(agent_id), "reason": "Hi"}
    key = f"one-{uuid.uuid4().hex[:12]}"

    first = await _post(headers, body, key)
    second = await _post(headers, body, key)

    assert first.json()["status"] == "queued", first.text
    assert second.json() == first.json()
    assert await _outbound_calls(tenant_id) == [(phone, "queued")]
    assert len(await _leads_with(tenant_id, phone)) == 1


async def test_a_call_later_is_one_booked_row_the_recent_list_reads() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    phone = _new_number()
    at = _tomorrow_late_morning()
    body = {
        "phone": phone,
        "agent_id": str(agent_id),
        "reason": "Remind about the visit",
        "at": at.isoformat(),
    }
    key = f"one-{uuid.uuid4().hex[:12]}"

    first = await _post(headers, body, key)
    second = await _post(headers, body, key)

    out = first.json()
    assert out["status"] == "scheduled", first.text
    assert second.json() == out
    assert await _outbound_calls(tenant_id) == [], "nothing rings until its time"
    async with _client() as http:
        listed = await http.get(
            "/v1/callbacks?open_only=true&booked_by_person=true", headers=headers
        )
    assert [row["id"] for row in listed.json()] == [out["callback_id"]]
    assert listed.json()[0]["note"] == "Remind about the visit"


async def test_the_recent_list_holds_the_calls_a_person_placed_and_nothing_else() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    await _finished_call(tenant_id, agent_id, lead_id, phone)  # not placed by a person
    placed = (
        await _post(headers, {"lead_id": str(lead_id), "agent_id": str(agent_id), "reason": "Hi"})
    ).json()

    async with _client() as http:
        listed = await http.get("/v1/calls?placed_by_person=true", headers=headers)

    assert [row["id"] for row in listed.json()] == [placed["call_id"]]


async def test_calling_from_a_call_follows_it_up_through_the_call_back() -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)

    response = await _post(headers, {"call_id": str(call_id)})

    out = response.json()
    assert out["status"] == "queued", response.text
    assert out["follow_up_number"] == 1
    assert out["lead_id"] == str(lead_id)
    async with tenant_session(tenant_id) as session:
        parent = (
            await session.execute(
                text("SELECT callback_of_call_id, placed_by_person FROM calls WHERE id = :id"),
                {"id": out["call_id"]},
            )
        ).one()
    assert str(parent[0]) == str(call_id) and parent[1] is True


@pytest.mark.parametrize(
    "body",
    [
        {"phone": "12345", "reason": "Hi"},
        {"phone": "+919800000000", "reason": "  "},
        {"phone": "+919800000000", "lead_id": str(uuid.uuid4()), "reason": "Hi"},
    ],
)
async def test_a_bad_request_is_refused_before_anything_rings(body: dict[str, object]) -> None:
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()

    response = await _post(headers, {"agent_id": str(agent_id), **body})

    assert response.status_code == 422, response.text
    assert await _outbound_calls(tenant_id) == []


async def test_a_role_without_dispatch_cannot_make_a_call() -> None:
    tenant_id, agent_id, slug, _headers = await _dialable_tenant()

    response = await _post(
        await _staff_of(tenant_id, slug),
        {"phone": _new_number(), "agent_id": str(agent_id), "reason": "Hi"},
    )

    assert response.status_code == 403, response.text
    assert await _outbound_calls(tenant_id) == []


async def test_a_neighbours_lead_and_agent_are_not_reachable() -> None:
    """RLS: tenant B naming tenant A's lead is told it does not exist; naming A's agent
    with a number is refused by the gate (the agent is not B's) and makes no lead."""
    tenant_a, agent_a, _slug_a, _headers_a = await _dialable_tenant()
    lead_a, _phone_a = await _lead(tenant_a, agent_a)
    tenant_b, _agent_b, _slug_b, headers_b = await _dialable_tenant()
    phone = _new_number()

    by_lead = await _post(
        headers_b, {"lead_id": str(lead_a), "agent_id": str(agent_a), "reason": "Hi"}
    )
    by_number = await _post(headers_b, {"phone": phone, "agent_id": str(agent_a), "reason": "Hi"})

    assert by_lead.status_code == 404, by_lead.text
    assert by_number.json()["status"] == "blocked", by_number.text
    assert await _outbound_calls(tenant_a) == [] and await _outbound_calls(tenant_b) == []
    assert await _leads_with(tenant_b, phone) == [] and await _leads_with(tenant_a, phone) == []
