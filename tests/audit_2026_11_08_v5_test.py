"""Backend audit round 3, lane V5 (outbound integrations), 9 Nov 2026.

V5-01: a WhatsApp message sent to a lead (lead menu, Pip, a Follow-up step) was written
to the lead's timeline with `status`, but the projection read only the alert legs'
`delivered`, so every message that WAS sent read "Alert to you not sent by WhatsApp. We
could not deliver it."

V5-02: Meta answers 2xx when it ACCEPTS a message and reports a failed delivery later on
the webhook; that report reached an operator alert and never the lead's timeline, so the
owner kept reading "sent".

V5-04: the Meta lead read had no whole-request deadline (httpx's read timeout restarts on
every byte).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.crm import swipe
from apps.api.crm.service import _project_event
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.lead_assignment_test import _the_lead

FOLLOW_UP = {"channel": "whatsapp", "kind": "client_follow_up", "template": "order_ready"}


# --- V5-01: the projection -------------------------------------------------------


def test_a_sent_message_to_a_lead_reads_as_sent() -> None:
    title, detail, _ = _project_event("notification", {**FOLLOW_UP, "status": "sent"}, {})
    assert title == "Message sent by WhatsApp"
    assert detail is None


@pytest.mark.parametrize(
    ("rule", "words"),
    [
        ("whatsapp_unanswered", "Check the chat before sending it again."),
        ("whatsapp_not_delivered", "could not deliver it to this person"),
        ("whatsapp_http_400", "WhatsApp did not accept the message."),
        ("whatsapp_blocked_dnc_tenant", "This number may not be contacted right now."),
        ("whatsapp_recipient_not_opted_in", "has not agreed to WhatsApp messages"),
    ],
)
def test_a_message_not_sent_says_why_in_words(rule: str, words: str) -> None:
    title, detail, _ = _project_event(
        "notification", {**FOLLOW_UP, "status": "failed", "rule": rule}, {}
    )
    assert title == "Message not sent by WhatsApp"
    assert detail is not None and words in detail
    assert rule not in detail


def test_an_unknown_rule_shows_no_wire_name() -> None:
    title, detail, _ = _project_event(
        "notification", {**FOLLOW_UP, "status": "blocked", "rule": "something_new"}, {}
    )
    assert title == "Message not sent by WhatsApp"
    assert detail is None


def test_the_alert_legs_still_read_delivered() -> None:
    title, _, _ = _project_event(
        "notification", {"channel": "whatsapp", "kind": "hot_lead", "delivered": True}, {}
    )
    assert title == "Alert to you sent by WhatsApp"


# --- V5-02: Meta's message id and its failed-delivery report -----------------------


def _response(status: int, body: Any) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_the_message_id_is_read_from_an_accepted_send() -> None:
    body = {"messaging_product": "whatsapp", "messages": [{"id": "wamid.HBgLOTE5ODc2NTQz"}]}
    assert swipe._message_id(_response(200, body)) == "wamid.HBgLOTE5ODc2NTQz"
    assert swipe._message_id(_response(200, {"messages": []})) is None
    assert swipe._message_id(_response(200, {"messages": [{"id": 7}]})) is None
    assert swipe._message_id(httpx.Response(200, content=b"not json")) is None


async def test_send_hands_back_the_status_and_the_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.actions import execution

    async def _accepted(request: Any, *, client: httpx.AsyncClient) -> httpx.Response:
        return _response(200, {"messages": [{"id": "wamid.ok"}]})

    monkeypatch.setattr(execution, "send_prepared", _accepted)
    assert await swipe._send(object()) == (200, "wamid.ok")

    async def _refused(request: Any, *, client: httpx.AsyncClient) -> httpx.Response:
        return _response(400, {"messages": [{"id": "wamid.ignored"}]})

    monkeypatch.setattr(execution, "send_prepared", _refused)
    assert await swipe._send(object()) == (400, None)


async def _rows(tenant_id: uuid.UUID, lead_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid AND type = "
                    "'notification' ORDER BY created_at, id"
                ),
                {"lid": lead_id},
            )
        ).all()
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


async def test_a_failed_delivery_report_lands_on_the_leads_timeline_once() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await swipe.record_whatsapp_on_timeline(
            session,
            lead_id=lead_id,
            template="order_ready",
            out=swipe.WhatsAppSendOut(status="sent"),
            actor="system",
            message_id="wamid.v5test",
        )
    async with tenant_session(tenant_id) as session:
        assert await swipe.record_whatsapp_not_delivered(
            session, message_id="wamid.v5test", meta_code="131026"
        )
    async with tenant_session(tenant_id) as session:
        # Meta redelivers; the second report writes nothing.
        assert not await swipe.record_whatsapp_not_delivered(
            session, message_id="wamid.v5test", meta_code="131026"
        )
        # A message id no lead message carries (an alert, a send outside Calevate).
        assert not await swipe.record_whatsapp_not_delivered(
            session, message_id="wamid.someone_else", meta_code=None
        )
    rows = await _rows(tenant_id, lead_id)
    assert [r["status"] for r in rows] == ["sent", "failed"]
    assert rows[1]["rule"] == swipe.NOT_DELIVERED_RULE
    assert rows[1]["template"] == "order_ready"
    title, detail, _ = _project_event("notification", rows[1], {})
    assert title == "Message not sent by WhatsApp"
    assert detail is not None and "could not deliver" in detail


async def test_another_tenants_report_does_not_reach_this_lead() -> None:
    tenant_id, _s, _t = await _make_tenant()
    other_id, _s2, _t2 = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await swipe.record_whatsapp_on_timeline(
            session,
            lead_id=lead_id,
            template="order_ready",
            out=swipe.WhatsAppSendOut(status="sent"),
            actor="system",
            message_id="wamid.v5cross",
        )
    async with tenant_session(other_id) as session:
        assert not await swipe.record_whatsapp_not_delivered(
            session, message_id="wamid.v5cross", meta_code=None
        )
    assert [r["status"] for r in await _rows(tenant_id, lead_id)] == ["sent"]


# --- V5-04: the Meta lead read has a whole-request deadline -------------------------


async def test_a_trickling_lead_read_stops_at_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.ingest import graph
    from apps.api.ingest.meta import RetrievalStatus

    monkeypatch.setattr(graph, "REQUEST_TIMEOUT_S", 0.2)
    source_id = uuid.uuid4()

    async def _slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json={"field_data": []})

    retriever = graph.GraphLeadRetriever(
        json.dumps({str(source_id): "token"}),
        client=httpx.AsyncClient(transport=httpx.MockTransport(_slow)),
    )
    started = asyncio.get_running_loop().time()
    found = await retriever.fetch_answers(source_id=source_id, leadgen_id="900000000000123")
    assert asyncio.get_running_loop().time() - started < 2
    assert found.status is RetrievalStatus.TRANSIENT
    assert found.reason == graph.UNREACHABLE_REASON
