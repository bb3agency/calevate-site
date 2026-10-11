"""The "save our number" WhatsApp (D-746): off by default, once per caller per client ever,
never to a do-not-call number or a caller without a messaging opt-in, in the caller's
language, and metered as ours."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from apps.api.compliance import consent
from apps.api.compliance.service import DispatchDecision, add_to_dnc
from apps.api.db.session import tenant_session
from apps.api.forwarding import save_number
from apps.workers import forwarding as worker
from apps.workers.whatsapp import SendResult, SendStatus, WhatsAppMessage
from sqlalchemy import text
from tests.forwarding_fixtures import give_calevate_number, make_client

pytestmark = [pytest.mark.rls]

CALLER = "+919811100001"


@dataclass
class Transport:
    sent: list[WhatsAppMessage] = field(default_factory=list)
    result: SendResult = field(default_factory=lambda: SendResult(SendStatus.DELIVERED))

    async def send(self, message: WhatsAppMessage) -> SendResult:
        self.sent.append(message)
        return self.result


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> Transport:
    fake = Transport()
    monkeypatch.setattr(worker, "get_whatsapp_transport", lambda: fake)

    async def _gate(
        session: Any, *, tenant_id: UUID, phone_e164: str, **_: Any
    ) -> DispatchDecision:
        # The real do-not-call read, without the dial gate's agent and account checks.
        from apps.api.compliance.dnc import check_number

        suppressed = (await check_number(session, tenant_id=tenant_id, raw=phone_e164)).suppressed
        return DispatchDecision(allowed=not suppressed, rule="dnc" if suppressed else None)

    monkeypatch.setattr(worker, "check_dispatch", _gate)
    return fake


async def _booked_call(
    *,
    switched_on: bool = True,
    opted_in: bool = True,
    language: str | None = None,
    caller: str = CALLER,
) -> tuple[UUID, UUID]:
    tenant_id, agent_id, _ = await make_client("save")
    await give_calevate_number(tenant_id, agent_id)
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await save_number.write_switch(session, enabled=switched_on)
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "from_e164, to_e164, status, outcome_tag, summary_language, started_at, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', :f, '+918000000999', "
                "'completed', 'call_back_booked', :lang, now(), now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"in_{call_id}",
                "f": caller,
                "lang": language,
            },
        )
        if opted_in:
            await consent.record_messaging_consent(
                session,
                tenant_id=tenant_id,
                raw_phone=caller,
                status="granted",
                source="web_form_optin",
                evidence={"form": "booking-form-v1"},
            )
    return tenant_id, call_id


async def _send(tenant_id: UUID, call_id: UUID) -> str:
    return await worker.send_save_number_message(
        {}, {"tenant_id": str(tenant_id), "call_id": str(call_id)}
    )


async def test_switched_off_nothing_is_queued_or_sent(transport: Transport) -> None:
    tenant_id, call_id = await _booked_call(switched_on=False)
    async with tenant_session(tenant_id) as session:
        assert (
            await save_number.queue_if_booked(session, tenant_id=tenant_id, call_id=call_id)
            is False
        )
    assert await _send(tenant_id, call_id) == "switched_off"
    assert transport.sent == []


async def test_a_booking_queues_it_once_and_the_caller_gets_it_once(transport: Transport) -> None:
    tenant_id, call_id = await _booked_call()
    async with tenant_session(tenant_id) as session:
        assert await save_number.queue_if_booked(session, tenant_id=tenant_id, call_id=call_id)
        assert not await save_number.queue_if_booked(session, tenant_id=tenant_id, call_id=call_id)
    assert await _send(tenant_id, call_id) == "sent"
    assert await _send(tenant_id, call_id) == "already_sent"
    assert len(transport.sent) == 1
    message = transport.sent[0]
    assert message.template == save_number.TEMPLATE and message.to_e164 == CALLER
    assert message.variables == ("Forwarding Business", "+918000000999")
    async with tenant_session(tenant_id) as session:
        rows = (
            (await session.execute(text("SELECT status FROM save_number_messages"))).scalars().all()
        )
        metered = (
            (
                await session.execute(
                    text("SELECT unit_type FROM usage_events WHERE unit_type = 'whatsapp_msg'")
                )
            )
            .scalars()
            .all()
        )
        stored = (
            await session.execute(text("SELECT caller_ref FROM save_number_messages"))
        ).scalar()
    assert rows == ["sent"] and metered == ["whatsapp_msg"]
    assert CALLER not in str(stored), "the number itself is never stored"


async def test_a_do_not_call_number_is_refused(transport: Transport) -> None:
    tenant_id, call_id = await _booked_call()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=CALLER, source="manual")
    assert await _send(tenant_id, call_id) == "refused"
    assert transport.sent == []


async def test_a_caller_without_a_messaging_opt_in_is_refused(transport: Transport) -> None:
    tenant_id, call_id = await _booked_call(opted_in=False)
    assert await _send(tenant_id, call_id) == "not_opted_in"
    assert transport.sent == []


@pytest.mark.parametrize(("language", "locale"), [("te-IN", "te"), ("hi-IN", "hi"), (None, "en")])
async def test_the_language_follows_the_caller(
    transport: Transport, language: str | None, locale: str
) -> None:
    tenant_id, call_id = await _booked_call(language=language)
    await _send(tenant_id, call_id)
    assert transport.sent[0].locale == locale


async def test_a_transport_failure_that_may_pass_releases_the_caller(transport: Transport) -> None:
    transport.result = SendResult(SendStatus.TRANSPORT_FAILED, reason="cloud_api_timeout")
    tenant_id, call_id = await _booked_call()
    with pytest.raises(RuntimeError):
        await _send(tenant_id, call_id)
    transport.result = SendResult(SendStatus.DELIVERED)
    assert await _send(tenant_id, call_id) == "sent"
