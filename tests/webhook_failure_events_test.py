"""The failure-state and compliance webhook events (D-1049, MASTER-PLAN W2.4).

Each event is asserted PRODUCED by the writer that owns the fact, with its published
`data` keys (docs/WEBHOOKS.md §1.2), and with the phone masked for an endpoint that did not
opt into full numbers. `*` and `auto_subscribe_new_events` are the subscription half.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import events, service
from sqlalchemy import text
from tests.api_security_test import _make_tenant

PHONE = "+919812345670"


async def _endpoint(
    tenant_id: uuid.UUID,
    events_: list[str],
    *,
    auto: bool = False,
    raw_phone: bool = False,
) -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, auto_subscribe_new_events, active, created_at, updated_at) VALUES "
                "(:id, :tid, 'webhook', 'https://crm.example/hook', 'whsec_x', :events, "
                "CAST(:mapping AS jsonb), :auto, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "events": events_,
                "auto": auto,
                "mapping": json.dumps({"include_raw_phone": True} if raw_phone else {}),
            },
        )
    return endpoint_id


async def _outbox(tenant_id: uuid.UUID, event: str) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid AND payload->>'event' = :event "
                    "ORDER BY created_at, id"
                ),
                {"job": service.OUTBOUND_WEBHOOK_JOB, "tid": str(tenant_id), "event": event},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def _feed(tenant_id: uuid.UUID, event: str) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, data FROM integration_events WHERE event_type = :e ORDER BY id"),
                {"e": event},
            )
        ).all()
    return [(uuid.UUID(str(r[0])), dict(r[1])) for r in rows]


async def _call(
    tenant_id: uuid.UUID, *, direction: str, status: str, test_call: bool = False
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, paid_test_call, started_at, ended_at, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ecid, :dir, :st, :from_e, :to_e, :test, "
                "now(), now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"c_{call_id.hex}",
                "dir": direction,
                "st": status,
                "from_e": PHONE if direction == "inbound" else "+914000000000",
                "to_e": PHONE if direction == "outbound" else "+914000000000",
                "test": test_call,
            },
        )
    return call_id


def test_the_five_events_are_offered_and_have_a_sheet_layout() -> None:
    for event in (
        events.CALL_NOT_CONNECTED_EVENT,
        events.CALL_INBOUND_MISSED_EVENT,
        events.CAMPAIGN_STATUS_CHANGED_EVENT,
        events.LEAD_CONSENT_CHANGED_EVENT,
        events.DNC_ADDED_EVENT,
    ):
        assert event in service.EVENT_TYPES
        assert service.DEFAULT_SHEET_COLUMNS[event]
        # Every sample the test delivery sends carries exactly the layout's keys.
        assert set(events.sample_data(event)) == set(service.DEFAULT_SHEET_COLUMNS[event])


async def test_an_unanswered_outbound_call_is_not_connected_once_with_a_masked_phone() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.CALL_NOT_CONNECTED_EVENT])
    call_id = await _call(tenant_id, direction="outbound", status="no_answer")

    for _ in range(2):  # the pipeline re-runs; the event is once per call
        async with tenant_session(tenant_id) as session:
            await events.emit_call_ended_unreached(
                session, tenant_id=tenant_id, call_id=call_id, lead_id=None
            )

    (payload,) = await _outbox(tenant_id, events.CALL_NOT_CONNECTED_EVENT)
    data = payload["data"]
    assert set(data) == set(service.DEFAULT_SHEET_COLUMNS[events.CALL_NOT_CONNECTED_EVENT])
    assert data["call_id"] == str(call_id)
    assert data["reason"] == "no_answer"
    assert data["rule"] is None
    assert data["phone"] != PHONE and PHONE not in json.dumps(payload)
    ((event_id, stored),) = await _feed(tenant_id, events.CALL_NOT_CONNECTED_EVENT)
    assert payload["event_id"] == str(event_id)
    # The feed keeps the domain data and masks when read (`feed.serialize`).
    assert stored["phone"] == PHONE


async def test_a_completed_call_or_a_test_call_is_never_reported_unreached() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.CALL_NOT_CONNECTED_EVENT])
    answered = await _call(tenant_id, direction="outbound", status="completed")
    test_call = await _call(tenant_id, direction="outbound", status="busy", test_call=True)
    async with tenant_session(tenant_id) as session:
        for call_id in (answered, test_call):
            assert (
                await events.emit_call_ended_unreached(
                    session, tenant_id=tenant_id, call_id=call_id, lead_id=None
                )
                == 0
            )
    assert await _outbox(tenant_id, events.CALL_NOT_CONNECTED_EVENT) == []


async def test_a_missed_inbound_call_is_inbound_missed_with_the_raw_phone_when_opted_in() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.CALL_INBOUND_MISSED_EVENT], raw_phone=True)
    call_id = await _call(tenant_id, direction="inbound", status="no_answer")
    async with tenant_session(tenant_id) as session:
        await events.emit_call_ended_unreached(
            session, tenant_id=tenant_id, call_id=call_id, lead_id=None
        )

    (payload,) = await _outbox(tenant_id, events.CALL_INBOUND_MISSED_EVENT)
    data = payload["data"]
    assert set(data) == set(service.DEFAULT_SHEET_COLUMNS[events.CALL_INBOUND_MISSED_EVENT])
    assert data["phone"] == PHONE
    assert data["call_back"] is None  # no line, so no Follow-up rings them back


async def test_a_dial_the_gate_settled_is_not_connected_with_its_rule() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.CALL_NOT_CONNECTED_EVENT])
    campaign_id, contact_id = uuid7(), uuid7()
    opens = datetime.now(UTC) + timedelta(hours=3)
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Renewals', 'service', 'running')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "created_at, updated_at) VALUES (:id, :t, :c, :p, 'pending', now(), now())"
            ),
            {"id": contact_id, "t": tenant_id, "c": campaign_id, "p": PHONE},
        )
        await events.emit_dial_refused(
            session, contact_id=contact_id, rule="dnc", deferred=False, opens_at=None
        )
        await events.emit_dial_refused(
            session,
            contact_id=contact_id,
            rule="person_contact_pacing",
            deferred=True,
            opens_at=opens,
        )
        await session.execute(text("UPDATE campaigns SET status = 'cancelled'"))

    refused, deferred = (p["data"] for p in await _outbox(tenant_id, "call.not_connected"))
    assert (refused["reason"], refused["rule"], refused["call_id"]) == ("refused", "dnc", None)
    assert refused["campaign_id"] == str(campaign_id)
    assert deferred["reason"] == "deferred"
    assert deferred["opens_at"] == opens.isoformat()


async def test_a_campaign_paused_for_a_spend_cap_says_why_and_its_resume_follows() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.CAMPAIGN_STATUS_CHANGED_EVENT])
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Diwali offers', 'service', 'running')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await campaigns.set_campaign_status(
            session,
            campaign_id=campaign_id,
            to_status="paused",
            from_statuses=("running",),
            auto_pause_reason="spend_cap",
        )
        # The second click moves nothing and says nothing.
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )
        await campaigns.set_campaign_status(
            session, campaign_id=campaign_id, to_status="running", from_statuses=("paused",)
        )
        await campaigns.set_campaign_status(
            session,
            campaign_id=campaign_id,
            to_status="cancelled",
            from_statuses=("running", "paused"),
        )

    sent = [p["data"] for p in await _outbox(tenant_id, events.CAMPAIGN_STATUS_CHANGED_EVENT)]
    assert [(d["change"], d["status"], d["reason"]) for d in sent] == [
        ("paused", "paused", "spend_cap"),
        ("resumed", "running", "owner"),
        ("stopped", "cancelled", "owner"),
    ]
    assert sent[0]["name"] == "Diwali offers"
    assert "phone" not in sent[0]


async def test_a_new_do_not_call_entry_is_dnc_added_once() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.DNC_ADDED_EVENT])
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=PHONE, source="call_optout")
        # Already on the list: nothing new to tell.
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=PHONE, source="call_optout")

    (payload,) = await _outbox(tenant_id, events.DNC_ADDED_EVENT)
    assert payload["data"]["source"] == "call_optout"
    assert PHONE not in json.dumps(payload)


async def test_a_consent_refusal_is_consent_changed_and_recording_consent_is_not() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, [events.LEAD_CONSENT_CHANGED_EVENT])
    async with tenant_session(tenant_id) as session:
        assert (
            await events.emit_consent_changed(
                session,
                tenant_id=tenant_id,
                phone=PHONE,
                purpose="recording",
                status="granted",
                source="in_call_recording_notice",
            )
            == 0
        )
        await events.emit_consent_changed(
            session,
            tenant_id=tenant_id,
            phone=PHONE,
            purpose="callback",
            status="declined",
            source="web_form_optin",
        )

    (payload,) = await _outbox(tenant_id, events.LEAD_CONSENT_CHANGED_EVENT)
    assert (payload["data"]["purpose"], payload["data"]["status"]) == ("callback", "declined")


async def test_a_wildcard_is_the_events_of_today_unless_new_ones_were_asked_for() -> None:
    assert service.expand_events(
        ["*"], include_recording_url=False, auto_subscribe_new_events=False
    ) == [e for e in service.EVENT_TYPES if e != service.RECORDING_READY_EVENT]
    with pytest.raises(ProblemError) as refused:
        service.expand_events(
            ["lead.created"], include_recording_url=False, auto_subscribe_new_events=True
        )
    assert refused.value.code == "auto_subscribe_needs_all_events"

    # An endpoint saved with yesterday's list never hears a later event; one that asked
    # for new events does.
    tenant_id, _, _ = await _make_tenant()
    fixed = await _endpoint(tenant_id, ["lead.created"])
    auto = await _endpoint(tenant_id, ["lead.created"], auto=True)
    async with tenant_session(tenant_id) as session:
        await service.enqueue_event(
            session,
            tenant_id=tenant_id,
            event=events.DNC_ADDED_EVENT,
            data={"phone": PHONE, "lead_id": None, "source": "manual", "added_at": "x"},
        )
    (payload,) = await _outbox(tenant_id, events.DNC_ADDED_EVENT)
    assert payload["endpoint_id"] == str(auto) != str(fixed)
