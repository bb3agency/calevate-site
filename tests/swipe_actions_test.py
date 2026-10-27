"""The phone swipe's actions (D-869): mark a call, undo a lead status, call back later, and
the WhatsApp follow-up.

1. A call's mark is a compare-and-swap: the undo names what it expects and a colleague's
   later mark is never overwritten; a neighbour's call is a 404 (hard rule 1).
2. A lead status undo is the existing PATCH with `expected_status`, refused with 409 when
   the lead moved since.
3. "Call back later" needs an `Idempotency-Key`, keeps to 09:00-21:00 IST, replays, moves an
   earlier one rather than piling up, uses an agent that can place calls, and is refused at
   once for a number on the do-not-call list.
4. The WhatsApp follow-up is refused without a connected account, refused without the
   person's messaging consent, sent once per key, and every attempt lands on the lead's
   timeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from apps.api.compliance.consent import record_messaging_consent
from apps.api.compliance.service import DispatchDecision
from apps.api.core.errors import ProblemError
from apps.api.crm import swipe
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.whatsapp import accounts
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import mark_paid_for_tests

_IST = timedelta(hours=5, minutes=30)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _code(response: httpx.Response) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


def _tomorrow_ist(hour: int) -> str:
    day: date = (datetime.now(UTC) + _IST).date() + timedelta(days=1)
    return f"{day.isoformat()}T{hour:02d}:00:00+05:30"


async def _tenant() -> tuple[uuid.UUID, dict[str, str], uuid.UUID, str]:
    """A paid account with its inbound agent and one lead. Returns (tenant, headers, lead
    id, lead phone)."""
    tenant_id, slug, token = await _make_tenant()
    await mark_paid_for_tests(tenant_id)
    async with tenant_session(tenant_id) as session:
        lead = (await session.execute(text("SELECT id, phone_e164 FROM leads LIMIT 1"))).one()
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    return tenant_id, headers, uuid.UUID(str(lead[0])), str(lead[1])


async def _outbound_agent(tenant_id: uuid.UUID) -> uuid.UUID:
    agent_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, caller_memory_notice_line, status, "
                "engine, created_at, updated_at) VALUES (:id, :tid, 'Caller', 'outbound', "
                "'Idi AI assistant.', 'Idi AI assistant.', 'This call is being recorded.', "
                "'I keep a short note.', 'live', 'fake', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
    return agent_id


async def _audit(object_id: str, action: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE object_id = :o AND action = :a"),
                    {"o": object_id, "a": action},
                )
            ).scalar_one()
        )


# --- 1. a call's mark -----------------------------------------------------------------


async def test_a_call_mark_is_a_compare_and_swap_with_an_undo() -> None:
    tenant_id, headers, _lead, _phone = await _tenant()
    _other, other_headers, _l, _p = await _tenant()
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"sw-{uuid.uuid4().hex}"},
        )
    url = f"/v1/calls/{call_id}/follow-up"
    async with _client() as http:
        marked = await http.put(url, headers=headers, json={"state": "resolved"})
        again = await http.put(url, headers=headers, json={"state": "resolved"})
        stale_undo = await http.put(
            url, headers=headers, json={"state": None, "expected_state": "needs_you"}
        )
        undo = await http.put(
            url, headers=headers, json={"state": None, "expected_state": "resolved"}
        )
        listed = await http.get("/v1/calls", headers=headers)
        neighbour = await http.put(url, headers=other_headers, json={"state": "needs_you"})

    assert marked.status_code == 200, marked.text
    assert marked.json()["previous_state"] is None and marked.json()["changed"] is True
    assert again.json()["changed"] is False
    assert stale_undo.status_code == 409 and _code(stale_undo) == "call_follow_up_changed"
    assert undo.json() | {"set_at": None} == {
        "call_id": str(call_id),
        "state": None,
        "previous_state": "resolved",
        "set_at": None,
        "set_by": None,
        "changed": True,
    }
    assert [c["follow_up_state"] for c in listed.json() if c["id"] == str(call_id)] == [None]
    assert neighbour.status_code == 404
    assert await _audit(str(call_id), "call.follow_up_marked") == 2


# --- 2. lead status undo ------------------------------------------------------------------


async def test_a_lead_status_undo_refuses_when_the_lead_moved_since() -> None:
    _tenant_id, headers, lead_id, _phone = await _tenant()
    url = f"/v1/leads/{lead_id}"
    async with _client() as http:
        won = await http.patch(url, headers=headers, json={"status": "won"})
        undo = await http.patch(
            url, headers=headers, json={"status": "new", "expected_status": "won"}
        )
        stale = await http.patch(
            url, headers=headers, json={"status": "lost", "expected_status": "won"}
        )
    assert won.json()["status"] == "won"
    assert undo.status_code == 200 and undo.json()["status"] == "new"
    assert stale.status_code == 409


# --- 3. call back later ---------------------------------------------------------------


async def test_call_back_later_is_gated_idempotent_and_moves_rather_than_piles_up() -> None:
    tenant_id, headers, lead_id, phone = await _tenant()
    outbound = await _outbound_agent(tenant_id)
    url = f"/v1/leads/{lead_id}/callbacks"
    body = {"at": _tomorrow_ist(16), "note": "Price for the 2BHK"}
    async with _client() as http:
        no_key = await http.post(url, headers=headers, json=body)
        night = await http.post(
            url, headers=headers | {"Idempotency-Key": "k0"}, json={"at": _tomorrow_ist(22)}
        )
        first = await http.post(url, headers=headers | {"Idempotency-Key": "k1"}, json=body)
        replay = await http.post(url, headers=headers | {"Idempotency-Key": "k1"}, json=body)
        moved = await http.post(
            url, headers=headers | {"Idempotency-Key": "k2"}, json={"at": _tomorrow_ist(17)}
        )

    assert no_key.status_code == 400
    assert night.status_code == 422 and _code(night) == "callback_time_not_allowed"
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "scheduled"
    callback_id = first.json()["callback_id"]
    assert replay.json() == first.json()
    assert moved.json()["callback_id"] == callback_id and moved.json()["rescheduled"] is True

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT agent_id, source_execution_id, requested_at, status "
                    "FROM scheduled_callbacks WHERE lead_id = :l"
                ),
                {"l": lead_id},
            )
        ).all()
    assert len(rows) == 1
    # The lead's own agent only answers calls, so the account's outbound agent rings back.
    assert rows[0].agent_id == outbound
    assert rows[0].source_execution_id.startswith("client-schedule:")
    assert (rows[0].requested_at + _IST).hour == 17
    assert await _audit(str(lead_id), "lead.callback_scheduled") == 2

    # Undo is the existing cancel.
    async with _client() as http:
        cancelled = await http.delete(f"/v1/callbacks/{callback_id}", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"

    # A number on the do-not-call list is refused now, not booked to fail later.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, created_at) "
                "VALUES (:id, :t, :p, 'tenant', 'manual', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
    async with _client() as http:
        blocked = await http.post(url, headers=headers | {"Idempotency-Key": "k3"}, json=body)
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["blocked_rule"] == "dnc"


def test_the_call_back_window_is_nine_to_nine_ist() -> None:
    now = datetime(2026, 10, 24, 3, 0, tzinfo=UTC)  # 08:30 IST
    ok = datetime(2026, 10, 24, 15, 29, tzinfo=UTC)  # 20:59 IST
    swipe.check_schedule_time(ok, now=now)
    for refused in (
        datetime(2026, 10, 24, 15, 30, tzinfo=UTC),  # 21:00 IST
        datetime(2026, 10, 24, 3, 29, tzinfo=UTC),  # 08:59 IST
        datetime(2026, 12, 1, 6, 0, tzinfo=UTC),  # beyond 30 days
        datetime(2026, 10, 24, 4, 31),  # no offset
    ):
        with pytest.raises(ProblemError):
            swipe.check_schedule_time(refused, now=now)


# --- 4. WhatsApp follow-up --------------------------------------------------------------


async def test_whatsapp_needs_a_connected_account() -> None:
    _tenant_id, headers, lead_id, _phone = await _tenant()
    async with _client() as http:
        options = await http.get(f"/v1/leads/{lead_id}/whatsapp", headers=headers)
        send = await http.post(
            f"/v1/leads/{lead_id}/whatsapp",
            headers=headers | {"Idempotency-Key": "w0"},
            json={"template_id": str(uuid.uuid4()), "values": []},
        )
    assert options.status_code == 200, options.text
    assert options.json()["available"] is False
    assert options.json()["rule"] == "whatsapp_not_connected"
    assert send.json()["status"] == "blocked"


def _stub_whatsapp(monkeypatch: pytest.MonkeyPatch) -> tuple[uuid.UUID, list[Any]]:
    """The account, its one template ("Hi, this is {{1}} following up.") and the wire stood
    in for (no WABA here). The dispatch gate answers `allowed`, because whether it allows a
    number at this hour of the test run is its own suite's business. Returns the template's
    id and the list each sent request lands in."""
    template_id = uuid.uuid4()
    account = accounts.Account(
        id=uuid.uuid4(),
        credential_id=uuid.uuid4(),
        waba_id="1",
        phone_number_id="123",
        business_id=None,
        display_phone_number=None,
        verified_name=None,
        name_status=None,
        quality_rating=None,
        messaging_limit=None,
        onboarding="new",
        status="connected",
        registered=True,
        webhooks_subscribed=True,
        setup_error=None,
        templates_seeded_at=None,
        last_event_at=None,
        account_alert=None,
        account_alert_at=None,
        last_send_error=None,
        last_send_error_at=None,
        connected_at=None,
        disconnected_at=None,
        created_at=datetime.now(UTC),
    )
    choice = swipe.WhatsAppTemplateChoiceOut(
        id=template_id,
        name="follow_up",
        language="en",
        category="UTILITY",
        body="Hi, this is {{1}} following up.",
        variables=[{"label": "Business"}],
    )
    sent: list[Any] = []

    async def _account(_session: Any) -> accounts.Account:
        return account

    async def _approved(_session: Any, _account_id: Any) -> list[Any]:
        return [choice]

    async def _token(*_a: Any, **_k: Any) -> str:
        return "token"

    async def _send(request: Any) -> int:
        sent.append(request)
        return 200

    async def _allowed(*_a: Any, **_k: Any) -> DispatchDecision:
        return DispatchDecision(allowed=True)

    monkeypatch.setattr(swipe, "_connected_account", _account)
    monkeypatch.setattr(swipe, "_approved", _approved)
    monkeypatch.setattr(accounts, "account_token", _token)
    monkeypatch.setattr(swipe, "_send", _send)
    monkeypatch.setattr("apps.api.actions.whatsapp.check_dispatch", _allowed)

    return template_id, sent


async def test_whatsapp_is_sent_only_with_consent_and_once_per_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consent read and the timeline are real; the rest is `_stub_whatsapp`."""
    tenant_id, headers, lead_id, phone = await _tenant()
    template_id, sent = _stub_whatsapp(monkeypatch)
    url = f"/v1/leads/{lead_id}/whatsapp"
    body = {"template_id": str(template_id), "values": ["Sri Homes"]}
    async with _client() as http:
        before = await http.get(url, headers=headers)
        refused = await http.post(url, headers=headers | {"Idempotency-Key": "w1"}, json=body)
        wrong_count = await http.post(
            url,
            headers=headers | {"Idempotency-Key": "w2"},
            json={"template_id": str(template_id), "values": []},
        )

    assert before.json()["available"] is False
    assert before.json()["rule"] == "whatsapp_recipient_not_opted_in"
    assert refused.json()["status"] == "blocked"
    assert wrong_count.status_code == 422
    assert sent == []

    await _grant_whatsapp_consent(tenant_id, phone)

    async with _client() as http:
        ok = await http.post(url, headers=headers | {"Idempotency-Key": "w3"}, json=body)
        replay = await http.post(url, headers=headers | {"Idempotency-Key": "w3"}, json=body)

    assert ok.json() == {"status": "sent", "reason": None, "rule": None}
    assert replay.json() == ok.json()
    assert len(sent) == 1
    assert sent[0].json_body["template"]["name"] == "follow_up"
    async with tenant_session(tenant_id) as session:
        statuses = (
            (
                await session.execute(
                    text(
                        "SELECT payload->>'status' FROM lead_events WHERE lead_id = :l "
                        "AND type = 'notification' ORDER BY created_at"
                    ),
                    {"l": lead_id},
                )
            )
            .scalars()
            .all()
        )
    assert statuses == ["blocked", "sent"]
    assert await _audit(str(lead_id), "lead.whatsapp_follow_up") == 2


async def _grant_whatsapp_consent(tenant_id: uuid.UUID, phone: str) -> None:
    """The person agreed on a call to be sent WhatsApp messages."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"wa-{uuid.uuid4().hex}"},
        )
        await record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="granted",
            source="inbound_call_verbal",
            call_id=call_id,
            evidence={"transcript_span": "turn 4", "asked": "shall I WhatsApp you?"},
        )


# --- 5. moving and calling off call-backs ------------------------------------------------


async def _booked(headers: dict[str, str], lead_id: uuid.UUID, hour: int) -> str:
    async with _client() as http:
        booked = await http.post(
            f"/v1/leads/{lead_id}/callbacks",
            headers=headers | {"Idempotency-Key": f"b-{uuid.uuid4()}"},
            json={"at": _tomorrow_ist(hour)},
        )
    assert booked.json()["status"] == "scheduled", booked.text
    return str(booked.json()["callback_id"])


async def test_a_waiting_call_back_is_moved_inside_the_window_and_not_once_it_ended() -> None:
    tenant_id, headers, lead_id, _phone = await _tenant()
    await _outbound_agent(tenant_id)
    _other, other_headers, _l, _p = await _tenant()
    callback_id = await _booked(headers, lead_id, 16)
    url = f"/v1/callbacks/{callback_id}"
    async with _client() as http:
        night = await http.patch(url, headers=headers, json={"at": _tomorrow_ist(22)})
        moved = await http.patch(url, headers=headers, json={"at": _tomorrow_ist(18)})
        neighbour = await http.patch(url, headers=other_headers, json={"at": _tomorrow_ist(18)})
        await http.delete(url, headers=headers)
        ended = await http.patch(url, headers=headers, json={"at": _tomorrow_ist(19)})

    assert night.status_code == 422 and _code(night) == "callback_time_not_allowed"
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "scheduled"
    moved_at = datetime.fromisoformat(moved.json()["requested_at"])
    assert (moved_at + _IST).hour == 18
    assert neighbour.status_code == 404
    assert ended.status_code == 409 and _code(ended) == "callback_not_stoppable"
    assert await _audit(callback_id, "callback.rescheduled") == 1
    assert await _audit(callback_id, "callback.cancelled") == 1


async def test_many_call_backs_are_moved_or_called_off_each_on_its_own() -> None:
    tenant_id, headers, lead_id, phone = await _tenant()
    await _outbound_agent(tenant_id)
    first = await _booked(headers, lead_id, 16)
    other_lead = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) SELECT :id, tenant_id, agent_id, :p, 'manual', 'new', "
                "now(), now() FROM leads WHERE id = :l"
            ),
            {"id": other_lead, "p": f"+9196{uuid.uuid4().int % 100000000:08d}", "l": lead_id},
        )
    second = await _booked(headers, other_lead, 17)
    async with _client() as http:
        no_time = await http.post(
            "/v1/callbacks/bulk", headers=headers, json={"action": "move", "callback_ids": [first]}
        )
        await http.delete(f"/v1/callbacks/{second}", headers=headers)
        moved = await http.post(
            "/v1/callbacks/bulk",
            headers=headers,
            json={"action": "move", "callback_ids": [first, second], "at": _tomorrow_ist(11)},
        )
    assert no_time.status_code == 422 and _code(no_time) == "callback_time_missing"
    assert moved.status_code == 200, moved.text
    assert moved.json()["changed"] == 1
    assert [r["status"] for r in moved.json()["results"]] == ["moved", "not_waiting"]

    # A number put on the do-not-call list since is left where it is, with the reason.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, created_at) "
                "VALUES (:id, :t, :p, 'tenant', 'manual', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "p": phone},
        )
    async with _client() as http:
        blocked = await http.post(
            "/v1/callbacks/bulk",
            headers=headers,
            json={"action": "move", "callback_ids": [first], "at": _tomorrow_ist(12)},
        )
        cancelled = await http.post(
            "/v1/callbacks/bulk",
            headers=headers,
            json={"action": "cancel", "callback_ids": [first]},
        )
    assert blocked.json()["results"][0]["status"] == "blocked"
    assert blocked.json()["results"][0]["reason"]
    assert cancelled.json() == {
        "results": [
            {"callback_id": first, "status": "cancelled", "requested_at": None, "reason": None}
        ],
        "changed": 1,
    }
    assert await _audit(first, "callback.rescheduled") == 1
    assert await _audit(first, "callback.cancelled") == 1
