"""Escalation after retry exhaustion (ROADMAP §3 bullet 1, FLOWS §4.5/§5).

A campaign contact that burns its dial ladder today simply stops: the contact row goes
`failed`, nobody is told, and a lead the client PAID to generate goes cold in silence.
This file pins the behaviour that closes that gap, as properties rather than as a
description of the code:

1. **Exhaustion escalates, and exactly once per contact.** A ladder that escalates on
   every exhausted attempt messages one person repeatedly about one enquiry — and the
   reaper (`_reap_stuck_dialing`) really does put an already-failed contact back on the
   ladder, so "once" cannot rest on the status transition alone.
2. **A contact still on the ladder does not escalate.** Attempt 1 of 3 is not a gap.
3. **A refusal is visible, never silent.** With no BSP configured — the state the
   decision log actually leaves us in — the escalation records a failed delivery on the
   lead timeline and tells a human. It does not vanish, and it does not report success.
4. **Consent and DNC bite here too.** The follow-up is a business-initiated message to a
   consumer who did not answer a phone call, so it goes through the same
   `check_dispatch` gate every dial does (DNC read live, calling hours, the big red
   switch) AND through a `messaging` opt-in of that consumer's own — recorded, sourced,
   evidenced and time-limited (`compliance/consent.py`). No bypass, no test-only
   branch, and nothing patched: every test that sends writes the opt-in the way the
   client-facing surface writes it, and every test that is refused is refused by the
   production read.
5. **Only `arq.Retry` produces a retry.** Measured on a REAL arq worker, because a test
   that injects `job_try` into `ctx` can only prove an `if` compares two numbers.
6. **Hard rule 6.** Neither the contact's number nor the lead's ever reaches a log line.

CONCURRENCY: every test builds its own run-unique tenant and asserts only on rows it
created, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service as campaigns
from apps.api.compliance.consent import (
    MESSAGING_CONSENT_VALIDITY_DAYS,
    record_messaging_consent,
)
from apps.api.compliance.service import add_to_dnc
from apps.api.core.logging import JsonFormatter
from apps.api.core.queue import WORKER_MAX_TRIES, redis_settings
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import campaign_dispatch, whatsapp
from apps.workers.whatsapp import (
    ESCALATION_JOB_NAME,
    Destination,
    SendResult,
    SendStatus,
    escalate_campaign_contact,
)
from arq import Retry
from sqlalchemy import text
from tests.national_dnd_test import record_test_scrub
from tests.platform_support import requires_posix_signals

# The contact we dial and then fail to reach. A documented test-range number: it exists
# so the hard-rule-6 assertions have something to search the log output FOR.
CONTACT_TEST_E164 = "+919000000042"

_TENANTS: list[UUID] = []


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside the platform window, so a refusal here is never the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(scope="module", autouse=True)
async def _settle_what_this_module_started() -> AsyncIterator[None]:
    """Leave the shared platform as quiet as we found it: our outbox rows would
    otherwise ride every later dispatcher tick, and a job name no worker registers
    would walk them to the DLQ on somebody else's watch."""
    yield
    async with untenanted_session() as session:
        for tenant_id in _TENANTS:
            await session.execute(
                text(
                    "DELETE FROM outbox_messages WHERE job = :job AND payload->>'tenant_id' = :tid"
                ),
                {"job": ESCALATION_JOB_NAME, "tid": str(tenant_id)},
            )


# --------------------------------------------------------------------------------
# Seeding — the real path, one row at a time
# --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fixture:
    tenant_id: UUID
    agent_id: UUID
    campaign_id: UUID
    contact_id: UUID
    lead_id: UUID
    call_id: UUID

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "campaign_id": str(self.campaign_id),
            "contact_id": str(self.contact_id),
        }


async def _tenant(prefix: str) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Escalation Motors",
        slug=f"esc-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        # Live + outbound: `check_dispatch` refuses a draft or inbound-only agent, and
        # this suite is about the message gate, not the agent gate.
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _campaign(tenant_id: UUID, agent_id: UUID) -> UUID:
    number_id, template_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                # BOUND TO THE CAMPAIGN'S AGENT (D-424): the launch gate refuses a campaign
                # whose approved number is not the number its agent dials from.
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 10**8:08d}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Escalation offers",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=2,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await campaigns.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": CONTACT_TEST_E164, "name": "Ravi"}],
        )
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
        await session.execute(
            text("UPDATE campaigns SET status = 'running' WHERE id = :c"), {"c": campaign_id}
        )
    return UUID(str(campaign_id))


async def _dialled_contact(prefix: str, *, attempts: int = 3) -> Fixture:
    """A contact that has been dialled `attempts` times and whose last call went
    unanswered — the state the post-call pipeline hands to `resolve_campaign_contact`.

    The lead exists because the pipeline upserts one for every terminal call before it
    resolves the contact (pipeline steps 4 and 7), which is what gives the escalation a
    timeline to be recorded on.
    """
    tenant_id, agent_id = await _tenant(prefix)
    campaign_id = await _campaign(tenant_id, agent_id)
    call_id, lead_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        contact_id = (
            await session.execute(
                text("SELECT id FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :ecid, 'outbound', 'no_answer', "
                "'+911140000000', :to, now(), now(), 0, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"exec_{call_id.hex[:12]}",
                "to": CONTACT_TEST_E164,
            },
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, schema_version, first_call_id, last_call_id, call_count, "
                "is_repeat_caller, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                "'Ravi', 'campaign', 'new', '{}'::jsonb, 1, :cid, :cid, 1, false, now(), now())"
            ),
            {
                "id": lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "phone": CONTACT_TEST_E164,
                "cid": call_id,
            },
        )
        # `calls.lead_id` is set AFTER the lead exists — the two tables reference each
        # other, and this is the order the pipeline writes them in.
        await session.execute(
            text("UPDATE calls SET lead_id = :lid WHERE id = :cid"),
            {"lid": lead_id, "cid": call_id},
        )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'dialing', attempts = :n, "
                "last_call_id = :cid, last_attempt_at = now(), updated_at = now() WHERE id = :id"
            ),
            {"n": attempts, "cid": call_id, "id": contact_id},
        )
    return Fixture(
        tenant_id=tenant_id,
        agent_id=agent_id,
        campaign_id=campaign_id,
        contact_id=UUID(str(contact_id)),
        lead_id=lead_id,
        call_id=call_id,
    )


async def _exhausted_contact(prefix: str) -> Fixture:
    """...and then the ladder is spent, through the real closing step. This is the state
    the escalation job is handed."""
    fixture = await _dialled_contact(prefix)
    assert await _resolve(fixture) == "failed"
    return fixture


async def _resolve(fixture: Fixture) -> str | None:
    """The real closing step: an unanswered call decides its contact's fate."""
    async with tenant_session(fixture.tenant_id) as session:
        return await campaign_dispatch.resolve_campaign_contact(
            session,
            tenant_id=fixture.tenant_id,
            call_id=fixture.call_id,
            call_status="no_answer",
        )


async def _redial(fixture: Fixture) -> None:
    """What `_reap_stuck_dialing` does to a stranded contact: back on the ladder, past
    its budget, with the attempt counter still climbing."""
    async with tenant_session(fixture.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'dialing', attempts = attempts + 1, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": fixture.contact_id},
        )


async def _escalations_queued(fixture: Fixture) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'contact_id' = :cid"
                ),
                {"job": ESCALATION_JOB_NAME, "cid": str(fixture.contact_id)},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def _escalation_events(fixture: Fixture) -> list[dict[str, Any]]:
    async with tenant_session(fixture.tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid "
                    "AND type = 'notification' AND payload->>'kind' = 'campaign_escalation'"
                ),
                {"lid": fixture.lead_id},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def _contact_status(fixture: Fixture) -> str:
    async with tenant_session(fixture.tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM campaign_contacts WHERE id = :id"),
                    {"id": fixture.contact_id},
                )
            ).scalar()
        )


class _Transport:
    """Counts attempts, so "did it try again?" is answerable."""

    name = "test"

    def __init__(self, result: SendResult) -> None:
        self.result = result
        self.attempts = 0
        self.last: whatsapp.WhatsAppMessage | None = None

    async def send(self, message: whatsapp.WhatsAppMessage) -> SendResult:
        self.attempts += 1
        self.last = message
        return self.result


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    fired: list[tuple[str, str, Any]] = []

    def _record(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs.get("detail")))

    monkeypatch.setattr(whatsapp, "alert", _record)
    return fired


async def _enable(
    monkeypatch: pytest.MonkeyPatch, fixture: Fixture, transport: _Transport | None = None
) -> _Transport:
    """Turn the channel on for one test, with a REAL recorded messaging opt-in.

    Nothing about the consent gate is patched. Until migration `c2f7a91b4e63` the
    `messaging` purpose was not a permitted member of the ledger's CHECK, so this suite
    stood in for it by monkeypatching `resolve_escalation_destination` — a stand-in that
    could not tell a working gate from a broken one. Now the opt-in is written the way
    the client-facing surface writes it, through
    `compliance.consent.record_messaging_consent`, and the worker's own resolver reads
    it back. A regression in the read, the write, the purpose, the validity window or
    the phone normalisation fails every test in this file rather than none of them.

    The setting is still flipped, because `whatsapp_enabled` is the operator's
    switch-on checklist, not a compliance gate — and the transport is still a sink,
    because there is no BSP.
    """
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = transport or _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)
    await _opt_in(fixture)
    return sink


async def _opt_in(fixture: Fixture, *, phone: str = CONTACT_TEST_E164) -> None:
    """The consumer says yes, on the call they DID take, exactly as the capture surface
    records it: a named source, a call id and a transcript span."""
    async with tenant_session(fixture.tenant_id) as session:
        await record_messaging_consent(
            session,
            tenant_id=fixture.tenant_id,
            raw_phone=phone,
            status="granted",
            source="inbound_call_verbal",
            call_id=fixture.call_id,
            evidence={"transcript_span": "turn 4", "asked": "shall I WhatsApp you the details?"},
        )


# --------------------------------------------------------------------------------
# 1. Exhaustion escalates — once, and only once
# --------------------------------------------------------------------------------


async def test_an_exhausted_contact_queues_an_escalation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gap ROADMAP §3 records: today this contact just stops."""
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    fixture = await _dialled_contact("queue")

    assert await _resolve(fixture) == "failed"
    assert await _contact_status(fixture) == "failed"

    queued = await _escalations_queued(fixture)
    assert len(queued) == 1, "an exhausted ladder must hand the lead to the follow-up channel"
    assert queued[0]["campaign_id"] == str(fixture.campaign_id)
    assert queued[0]["tenant_id"] == str(fixture.tenant_id)
    assert "phone" not in " ".join(queued[0]).lower()
    assert CONTACT_TEST_E164 not in str(queued[0]), "ids travel through the queue, not numbers"


async def test_a_contact_still_on_the_ladder_does_not_escalate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attempt 1 of 3 is a retry, not a dead end. Escalating here would message someone
    while we are still trying to phone them."""
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    fixture = await _dialled_contact("early", attempts=1)

    assert await _resolve(fixture) == "pending"
    assert await _escalations_queued(fixture) == []


async def test_escalation_fires_once_even_when_the_reaper_re_ladders_the_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_reap_stuck_dialing` returns a stranded contact to `pending` with its attempt
    count intact and no ceiling on it, so a contact can reach "exhausted" more than
    once. One enquiry, one follow-up: the outbox row already written is what says so."""
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    fixture = await _dialled_contact("twice")

    assert await _resolve(fixture) == "failed"
    await _redial(fixture)
    assert await _resolve(fixture) == "failed"

    assert len(await _escalations_queued(fixture)) == 1, (
        "a second exhaustion of the same contact must not message them again"
    )


async def test_the_escalation_is_queued_in_the_callers_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transactional outbox: a contact that never finished failing has nobody to
    follow up. Both writes share a fate or neither happens."""
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    fixture = await _dialled_contact("atomic")

    class _RollbackError(Exception):
        pass

    with pytest.raises(_RollbackError):
        async with tenant_session(fixture.tenant_id) as session:
            await campaign_dispatch.resolve_campaign_contact(
                session,
                tenant_id=fixture.tenant_id,
                call_id=fixture.call_id,
                call_status="no_answer",
            )
            raise _RollbackError

    assert await _contact_status(fixture) == "dialing", "the rollback took the status back"
    assert await _escalations_queued(fixture) == [], "...and the escalation with it"


# --------------------------------------------------------------------------------
# 2. A refusal is visible, never silent
# --------------------------------------------------------------------------------


async def test_with_no_provider_the_escalation_records_a_failed_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state the decision log actually leaves us in: no BSP is chosen, so there is
    no adapter. That must read as an undelivered follow-up on the lead's timeline and
    reach a human — not as success, and not as nothing at all."""
    fixture = await _exhausted_contact("noprovider")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_provider", None)
    monkeypatch.setattr(settings, "app_env", "prod")

    async def _opted_in(session: Any, *, tenant_id: UUID, phone_e164: str) -> Destination:
        return Destination(to_e164=phone_e164, opt_in_at=datetime.now(UTC))

    monkeypatch.setattr(whatsapp, "resolve_escalation_destination", _opted_in)
    fired = _capture_alerts(monkeypatch)

    result = await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    assert result == "rejected no_provider_configured"
    events = await _escalation_events(fixture)
    assert len(events) == 1
    assert events[0]["delivered"] is False
    assert events[0]["reason"] == "no_provider_configured"
    assert events[0]["contact_id"] == str(fixture.contact_id)
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_TERMINAL", "campaign_escalation_rejected")
    ]


async def test_the_channel_being_off_is_recorded_rather_than_vanishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`whatsapp_enabled` is off until a human finishes the switch-on checklist. Unlike
    the hot-lead alert, this escalation has NO other channel — email is not sent to a
    consumer — so "we did not follow up" is a fact the timeline has to carry. It is not
    an incident, though: nobody is paged per contact for a feature that is switched off.
    """
    fixture = await _exhausted_contact("off")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", False)
    fired = _capture_alerts(monkeypatch)

    result = await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    assert result == "rejected whatsapp_disabled"
    events = await _escalation_events(fixture)
    assert len(events) == 1 and events[0]["delivered"] is False
    assert events[0]["reason"] == "whatsapp_disabled"
    assert fired == [], "a switched-off channel is not an incident"


# --------------------------------------------------------------------------------
# 3. Consent and DNC bite on the message too
# --------------------------------------------------------------------------------


async def test_a_number_on_the_dnc_list_is_never_messaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 5 does not stop at dialling. A person who asked not to be contacted
    and then did not answer the phone is the LAST person a follow-up may reach, and the
    list is read live at send time — not trusted from the launch scrub."""
    fixture = await _exhausted_contact("dnc")
    sink = await _enable(monkeypatch, fixture)
    fired = _capture_alerts(monkeypatch)
    async with tenant_session(fixture.tenant_id) as session:
        await add_to_dnc(
            session, tenant_id=fixture.tenant_id, phone_e164=CONTACT_TEST_E164, source="test"
        )

    result = await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    assert result == "rejected blocked_dnc"
    assert sink.attempts == 0, "the number is never handed to a processor to find out"
    events = await _escalation_events(fixture)
    assert events[0]["delivered"] is False and events[0]["reason"] == "blocked_dnc"
    assert fired == [], "honouring an opt-out is the system working, not an incident"


async def test_a_recipient_with_no_recorded_opt_in_is_refused_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A business-initiated WhatsApp message needs the RECIPIENT's opt-in to the WABA.
    Consent to be CALLED (the campaign's list provenance) is not that, and the caller
    consent ledger records what a caller agreed to during a call this person never
    took. Nothing we hold today can evidence it — so the honest answer is a refusal,
    recorded, and never a retry: the same row is just as un-opted-in in two minutes."""
    fixture = await _exhausted_contact("noptin")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)
    fired = _capture_alerts(monkeypatch)

    result = await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    assert result == "rejected recipient_not_opted_in"
    assert sink.attempts == 0
    events = await _escalation_events(fixture)
    assert events[0]["delivered"] is False
    assert fired == [], "an un-opted-in consumer is the default state, not an alert per contact"


async def test_a_recorded_opt_in_is_what_turns_the_escalation_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the slice. Same contact, same job, same transport — the ONLY thing
    that differs from the test above is one `consent_ledger` row, and it is the
    difference between a follow-up that is refused and one that is sent.

    Written as a before/after in one test on purpose: two separate tests could both pass
    with a gate that is stuck open or stuck shut.
    """
    fixture = await _exhausted_contact("optin")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)
    _capture_alerts(monkeypatch)

    before = await escalate_campaign_contact({"job_try": 1}, fixture.payload)
    assert before == "rejected recipient_not_opted_in"
    assert sink.attempts == 0

    await _opt_in(fixture)

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == "sent"
    assert sink.attempts == 1, "a recorded opt-in must actually reach the transport"
    assert sink.last is not None and sink.last.to_e164 == CONTACT_TEST_E164
    events = await _escalation_events(fixture)
    assert len(events) == 1, "one record per contact, updated as the outcome changes"
    assert events[0]["delivered"] is True


async def test_a_withdrawal_supersedes_the_opt_in_without_editing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule 4: the ledger is INSERT-only, so "I have changed my mind" is a new row
    and the read takes the latest. The grant must still be there afterwards — it is the
    proof that we were once allowed, which is exactly what a complaint asks for."""
    fixture = await _exhausted_contact("withdrawn")
    sink = await _enable(monkeypatch, fixture)
    _capture_alerts(monkeypatch)
    async with tenant_session(fixture.tenant_id) as session:
        await record_messaging_consent(
            session,
            tenant_id=fixture.tenant_id,
            raw_phone=CONTACT_TEST_E164,
            status="withdrawn",
            # No evidence, no call: a refusal is never obstructed.
            source="staff_recorded_request",
        )

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == (
        "rejected recipient_not_opted_in"
    )
    assert sink.attempts == 0

    async with tenant_session(fixture.tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status FROM consent_ledger WHERE tenant_id = :t AND purpose = "
                    "'messaging' ORDER BY captured_at"
                ),
                {"t": fixture.tenant_id},
            )
        ).all()
    assert [str(row[0]) for row in rows] == ["granted", "withdrawn"], (
        "the withdrawal is an APPEND; the grant it supersedes is never edited away"
    )


async def test_an_opt_in_older_than_the_validity_window_is_not_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta publishes no expiry, but TRAI's 2025 amendment refuses indefinite consent
    and DPDP binds consent to the purpose it was given for — so a stale opt-in is a
    record of something that WAS true. The row survives; the permission does not."""
    fixture = await _exhausted_contact("stale")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)
    _capture_alerts(monkeypatch)
    stale = datetime.now(UTC) - timedelta(days=MESSAGING_CONSENT_VALIDITY_DAYS + 1)
    async with tenant_session(fixture.tenant_id) as session:
        # Appended directly rather than through the service, because the service stamps
        # `captured_at = now()` — the only way to have an old opt-in is to have had one.
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                "status, consent_source, captured_at, evidence, created_at) VALUES (:id, :t, "
                ":c, :p, 'messaging', 'granted', 'web_form_optin', :at, "
                "CAST(:ev AS jsonb), :at)"
            ),
            {
                "id": uuid7(),
                "t": fixture.tenant_id,
                "c": fixture.call_id,
                "p": CONTACT_TEST_E164,
                "at": stale,
                "ev": '{"form": "enquiry-v1", "notice_version": "2024-01"}',
            },
        )

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == (
        "rejected recipient_not_opted_in"
    )
    assert sink.attempts == 0, "a year-old opt-in does not authorise today's message"


async def test_consent_to_be_called_back_is_not_consent_to_be_messaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The purpose column is load-bearing, not decorative. A caller who agreed to a
    callback and to being recorded has said nothing about a WhatsApp message from a
    WABA they have never heard of — Meta requires an opt-in that names the business and
    the channel, and DPDP §6 forbids reusing consent given for another purpose."""
    fixture = await _exhausted_contact("purpose")
    monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
    sink = _Transport(SendResult(SendStatus.DELIVERED))
    monkeypatch.setattr(whatsapp, "get_whatsapp_transport", lambda: sink)
    _capture_alerts(monkeypatch)
    async with tenant_session(fixture.tenant_id) as session:
        for purpose in ("callback", "recording", "marketing"):
            await session.execute(
                text(
                    "INSERT INTO consent_ledger (id, tenant_id, call_id, phone_e164, purpose, "
                    "status, captured_at, created_at) VALUES (:id, :t, :c, :p, :purpose, "
                    "'granted', now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": fixture.tenant_id,
                    "c": fixture.call_id,
                    "p": CONTACT_TEST_E164,
                    "purpose": purpose,
                },
            )

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == (
        "rejected recipient_not_opted_in"
    )
    assert sink.attempts == 0


async def test_the_template_carries_no_consumer_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """What crosses to a foreign processor is the CLIENT's business name — so the
    recipient knows who is contacting them, which Meta requires — and nothing else. No
    lead name, no call summary, no extracted field, and the message type has no body
    field to smuggle them into."""
    fixture = await _exhausted_contact("template")
    sink = await _enable(monkeypatch, fixture)

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == "sent"

    assert sink.last is not None
    assert sink.last.template == whatsapp.TEMPLATE_MISSED_CALL
    assert sink.last.variables == ("Escalation Motors",)
    assert "Ravi" not in str(sink.last.variables)
    assert not hasattr(sink.last, "body")


# --------------------------------------------------------------------------------
# 4. The delivery record — and it is not sent twice
# --------------------------------------------------------------------------------


async def test_a_delivered_escalation_is_recorded_and_never_repeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = await _exhausted_contact("delivered")
    sink = await _enable(monkeypatch, fixture)

    first = await escalate_campaign_contact({"job_try": 1}, fixture.payload)
    second = await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    assert (first, second) == ("sent", "duplicate")
    assert sink.attempts == 1, "a replayed outbox row must not message the person twice"
    events = await _escalation_events(fixture)
    assert len(events) == 1
    assert events[0]["delivered"] is True
    assert events[0]["campaign_id"] == str(fixture.campaign_id)


async def test_a_retry_re_sends_instead_of_being_deduped_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap in the idempotence check: a recorded ATTEMPT must not satisfy it, or
    every retry returns `duplicate` and the ladder is decorative."""
    fixture = await _exhausted_contact("second-try")
    await _enable(
        monkeypatch, fixture, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502"))
    )
    _capture_alerts(monkeypatch)
    with pytest.raises(Retry):
        await escalate_campaign_contact({"job_try": 1}, fixture.payload)

    succeeding = await _enable(monkeypatch, fixture)
    assert await escalate_campaign_contact({"job_try": 2}, fixture.payload) == "sent"

    assert succeeding.attempts == 1, "the retry must reach the transport again"
    events = await _escalation_events(fixture)
    assert len(events) == 1, "one record per contact, whatever it took to deliver"
    assert events[0]["delivered"] is True


async def test_the_hot_lead_alert_and_the_escalation_cannot_answer_for_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both write `lead_events.type = 'notification'` with `channel = 'whatsapp'` — the
    type column is a fixed CHECK enum and this milestone ships no migration — so `kind`
    is the discriminator, and a delivered hot-lead alert must not make an un-sent
    follow-up look done."""
    fixture = await _exhausted_contact("crosstalk")
    async with tenant_session(fixture.tenant_id) as session:
        await whatsapp._record_attempt(
            session,
            tenant_id=fixture.tenant_id,
            lead_id=fixture.lead_id,
            call_id=fixture.call_id,
            result=SendResult(SendStatus.DELIVERED),
            attempts=1,
            triggers=["urgency"],
            template="calevate_hot_lead_v1",
        )
    sink = await _enable(monkeypatch, fixture)

    assert await escalate_campaign_contact({"job_try": 1}, fixture.payload) == "sent"
    assert sink.attempts == 1, "the hot-lead alert's success must not mark the follow-up done"

    events = await _escalation_events(fixture)
    assert len(events) == 1
    async with tenant_session(fixture.tenant_id) as session:
        hot = (
            await session.execute(
                text(
                    "SELECT payload FROM lead_events WHERE lead_id = :lid "
                    "AND payload->>'call_id' = :cid AND payload->>'kind' IS NULL"
                ),
                {"lid": fixture.lead_id, "cid": str(fixture.call_id)},
            )
        ).all()
    assert len(hot) == 1 and dict(hot[0][0])["delivered"] is True, "the alert row survives"


# --------------------------------------------------------------------------------
# 5. The ladder, measured on a real arq worker
# --------------------------------------------------------------------------------


async def _run_one_job_to_exhaustion(func: Any, payload: Any, *, max_tries: int) -> int:
    """Run ONE job on a REAL arq worker until it stops being retried; return the number
    of attempts the worker actually made.

    Nothing is simulated: `ctx["job_try"]` is written by arq, the retry decision is
    arq's, and the count comes back from the worker. Copied in shape from
    `tests/reliability_audit_test.py`, which is where this harness was proven.
    """
    from arq import create_pool
    from arq.worker import Worker

    run_id = uuid7().hex
    queue_name = f"escalation:{run_id}"
    attempts = 0
    real = func

    async def counting(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        return await real(ctx, *args, **kwargs)

    # arq registers a function under its __qualname__; a closure's own qualname would
    # never match what we enqueue.
    counting.__name__ = func.__name__
    counting.__qualname__ = func.__name__
    worker = Worker(
        functions=[counting],
        redis_settings=redis_settings(),
        queue_name=queue_name,
        max_tries=max_tries,
        burst=True,
        poll_delay=0.02,
        keep_result=1,
        retry_jobs=True,
        handle_signals=False,
    )
    pool = await create_pool(redis_settings(), default_queue_name=queue_name)
    enqueued = await pool.enqueue_job(func.__name__, payload, _job_id=run_id)
    assert enqueued is not None, "the harness must actually enqueue the job it measures"
    try:
        stagnant, seen = 0, 0
        for _ in range(max_tries * 4):
            await worker.main()
            if attempts >= max_tries:
                break
            if attempts == seen:
                stagnant += 1
                if attempts and stagnant >= 2:
                    break
            else:
                stagnant, seen = 0, attempts
            await asyncio.sleep(0.05)
    finally:
        await worker.close()
        await pool.aclose()
    return attempts


@requires_posix_signals
async def test_a_transport_blip_really_is_retried_by_a_real_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq 0.28 retries for `Retry`, `RetryJob` and `CancelledError` and NOTHING else,
    so a plain raise would make `max_tries` decorative and this ladder imaginary."""
    fixture = await _exhausted_contact("ladder")
    await _enable(
        monkeypatch, fixture, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "connect_timeout"))
    )
    _capture_alerts(monkeypatch)
    # The real ladder is measured in tens of seconds; its SHAPE is what is under test.
    monkeypatch.setattr(whatsapp, "RETRY_BACKOFF_S", (0.02, 0.02))

    attempts = await _run_one_job_to_exhaustion(
        escalate_campaign_contact, fixture.payload, max_tries=WORKER_MAX_TRIES
    )

    assert attempts == WORKER_MAX_TRIES, (
        f"a transport blip must climb the whole budget; the worker ran it {attempts} time(s)"
    )
    events = await _escalation_events(fixture)
    assert len(events) == 1, "one record per contact, updated as the ladder walks"
    assert events[0]["delivered"] is False
    assert events[0]["attempts"] == WORKER_MAX_TRIES


@requires_posix_signals
async def test_a_rejection_stops_on_the_first_attempt_on_a_real_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unapproved template is a verdict, not a blip: three retries reach the same
    answer a minute later and burn a person's follow-up window doing it."""
    fixture = await _exhausted_contact("verdict")
    sink = await _enable(
        monkeypatch, fixture, _Transport(SendResult(SendStatus.REJECTED, "template_not_approved"))
    )
    _capture_alerts(monkeypatch)

    attempts = await _run_one_job_to_exhaustion(
        escalate_campaign_contact, fixture.payload, max_tries=WORKER_MAX_TRIES
    )

    assert attempts == 1, f"a verdict must not be retried; the worker ran it {attempts} time(s)"
    assert sink.attempts == 1


async def test_the_last_attempt_tells_a_human(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhaustion is the end of the ladder, not the end of the story: the lead is still
    cold and only a person can do anything about it."""
    fixture = await _exhausted_contact("exhausted")
    await _enable(
        monkeypatch, fixture, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502"))
    )
    fired = _capture_alerts(monkeypatch)

    result = await escalate_campaign_contact({"job_try": WORKER_MAX_TRIES}, fixture.payload)

    assert "exhausted" in result
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_DELIVERY", "campaign_escalation_exhausted")
    ]


# --------------------------------------------------------------------------------
# 6. Hard rule 6 — no number in any log line
# --------------------------------------------------------------------------------


async def test_no_phone_number_reaches_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Asserted through the real `JsonFormatter`, because that is what production
    writes: a record whose extras look clean can still stringify a number into `msg`.

    Every branch that could be tempted to "just log which number we skipped" is walked:
    delivered, refused for consent, and exhausted.
    """
    formatter = JsonFormatter()
    with caplog.at_level(logging.DEBUG):
        delivered = await _exhausted_contact("nolog-ok")
        await _enable(monkeypatch, delivered)
        assert await escalate_campaign_contact({"job_try": 1}, delivered.payload) == "sent"

        refused = await _exhausted_contact("nolog-consent")
        monkeypatch.setattr(get_settings(), "whatsapp_enabled", True)
        monkeypatch.setattr(
            whatsapp, "get_whatsapp_transport", lambda: _Transport(SendResult(SendStatus.DELIVERED))
        )
        _capture_alerts(monkeypatch)
        await escalate_campaign_contact({"job_try": 1}, refused.payload)

        failing = await _exhausted_contact("nolog-fail")
        await _enable(
            monkeypatch, failing, _Transport(SendResult(SendStatus.TRANSPORT_FAILED, "http_502"))
        )
        _capture_alerts(monkeypatch)
        await escalate_campaign_contact({"job_try": WORKER_MAX_TRIES}, failing.payload)

        # ...and the enqueue side, which is the one holding the contact row.
        queued = await _dialled_contact("nolog-queue")
        await _resolve(queued)

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert CONTACT_TEST_E164 not in rendered
    assert CONTACT_TEST_E164.lstrip("+") not in rendered
