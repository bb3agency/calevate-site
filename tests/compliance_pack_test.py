"""D-943 against the database: the application window, the 90-day re-ask lockout, the
rights desk and its clock, the short notice, and the campaign launch refusal.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.actions import whatsapp as wa
from apps.api.billing.plans import IST
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance import rights_desk
from apps.api.compliance.consent import (
    reask_locked_until,
    record_call_consent,
    record_messaging_consent,
    relationship_window,
)
from apps.api.compliance.export import subject_ref
from apps.api.compliance.privacy_notice import build_short_notice
from apps.api.compliance.promo_checks import SCRIPT_PROMOTIONAL_RULE, agent_check
from apps.api.core.errors import ProblemError
from apps.api.crm.attention import attention_queue
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.ingest.service import _record_dial_consent_granted
from sqlalchemy import text
from tests.outbound_consent_policy_test import _fresh_phone, _tenant

#: 11:00 IST, inside the calling window, so the hours rule can never be what refuses.
_PINNED_IST = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: _PINNED_IST)


# --- consent windows -------------------------------------------------------------------


def test_the_two_relationship_windows() -> None:
    assert relationship_window("inquiry") == (0, 7)
    assert relationship_window("application") == (3, 0)
    with pytest.raises(ValueError):
        relationship_window("purchase")


async def test_an_application_form_consent_lasts_three_calendar_months() -> None:
    tenant_id, _agent = await _tenant("d943-app")
    phone = _fresh_phone()
    async with tenant_session(tenant_id) as session:
        await _record_dial_consent_granted(
            session,
            tenant_id=tenant_id,
            phone_e164=phone,
            consent_field="apply",
            source="website",
            consent_basis="application",
        )
        await session.commit()
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT expires_at = captured_at + interval '3 months', evidence->>'basis' "
                    "FROM consent_ledger WHERE tenant_id = :t AND phone_e164 = :p"
                ),
                {"t": tenant_id, "p": phone},
            )
        ).one()
    assert row[0] is True
    assert row[1] == "application"


async def _ledger(
    tenant_id: UUID,
    phone: str,
    status: str,
    source: str,
    ago: timedelta,
    *,
    purpose: str = "messaging",
) -> None:
    """A row captured `ago` in the past. The ledger is append-only, so history is INSERTed
    with its own capture time rather than updated into the past."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "consent_source, evidence, captured_at, created_at) VALUES (:id, :t, :p, "
                "CAST(:purpose AS text), :s, :src, CAST(:ev AS jsonb), :at, now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "p": phone,
                "purpose": purpose,
                "s": status,
                "src": source,
                "ev": json.dumps({"message_id": "m-1"}) if status == "granted" else None,
                "at": datetime.now(UTC) - ago,
            },
        )
        await session.commit()


async def test_a_no_inside_ninety_days_locks_the_ask_and_a_later_yes_lifts_it() -> None:
    tenant_id, _agent = await _tenant("d943-lock")
    phone = _fresh_phone()
    await _ledger(tenant_id, phone, "declined", "in_call_agent_question", timedelta(days=10))
    async with tenant_session(tenant_id) as session:
        until = await reask_locked_until(
            session, tenant_id=tenant_id, phone_e164=phone, purpose="messaging"
        )
    assert until is not None
    assert timedelta(days=79) < until - datetime.now(UTC) < timedelta(days=81)

    # The person writes in themselves: that is not our ask, and it lifts the lock.
    await _ledger(tenant_id, phone, "granted", "whatsapp_inbound_message", timedelta(days=1))
    async with tenant_session(tenant_id) as session:
        assert (
            await reask_locked_until(
                session, tenant_id=tenant_id, phone_e164=phone, purpose="messaging"
            )
            is None
        )


async def test_a_no_older_than_ninety_days_does_not_lock() -> None:
    tenant_id, _agent = await _tenant("d943-old")
    phone = _fresh_phone()
    await _ledger(tenant_id, phone, "withdrawn", "whatsapp_inbound_message", timedelta(days=91))
    async with tenant_session(tenant_id) as session:
        assert (
            await reask_locked_until(
                session, tenant_id=tenant_id, phone_e164=phone, purpose="messaging"
            )
            is None
        )


async def test_the_in_call_whatsapp_action_tells_the_agent_not_to_ask() -> None:
    tenant_id, agent_id = await _tenant("d943-wa")
    phone = _fresh_phone()
    await _ledger(tenant_id, phone, "declined", "in_call_agent_question", timedelta(days=3))
    async with tenant_session(tenant_id) as session:
        with pytest.raises(wa.WhatsAppReaskLockedError) as refused:
            await wa.assert_recipient_may_be_messaged(
                session, tenant_id=tenant_id, agent_id=agent_id, recipient_e164=phone
            )
        assert refused.value.code == "whatsapp_consent_reask_locked"
        # And a yes the agent reports anyway is not filed as consent.
        spoken = wa.SpokenConsent(
            answer="yes",
            words="yes send it",
            call_id=uuid.uuid4(),
            call_ref=None,
            action_id=uuid7(),
        )
        with pytest.raises(wa.WhatsAppReaskLockedError):
            await wa.assert_recipient_may_be_messaged(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                recipient_e164=phone,
                spoken=spoken,
            )
        granted = (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger WHERE phone_e164 = :p "
                    "AND status = 'granted'"
                ),
                {"p": phone},
            )
        ).scalar_one()
    assert granted == 0


# --- the same lockout on CALL consent ----------------------------------------------------


async def _call_row(tenant_id: UUID, agent_id: UUID, phone: str) -> UUID:
    """A finished outbound call to `phone`, so a spoken grant has a call to name."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "to_e164) VALUES (:i, :t, :a, :e, 'outbound', 'completed', :p)"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"eng-{uuid7().hex}", "p": phone},
        )
        await session.commit()
    return call_id


async def _spoken_call_yes(tenant_id: UUID, phone: str, call_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await record_call_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=phone,
            status="granted",
            source="inbound_call_verbal",
            call_id=call_id,
            evidence={"transcript_turn": "4"},
        )
        await session.commit()


async def _granted(tenant_id: UUID, phone: str, purpose: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM consent_ledger WHERE phone_e164 = :p "
                        "AND purpose = CAST(:purpose AS text) AND status = 'granted'"
                    ),
                    {"p": phone, "purpose": purpose},
                )
            ).scalar_one()
        )


@pytest.mark.parametrize(
    ("purpose", "status", "source"),
    [
        ("callback", "declined", "web_form_optin"),
        ("callback", "withdrawn", "staff_recorded_request"),
        # "Stop calling me", heard on a call (`optout.record_call_optout`).
        ("marketing", "withdrawn", "inbound_call_verbal"),
    ],
)
async def test_a_call_consent_yes_inside_ninety_days_of_a_no_is_refused(
    purpose: str, status: str, source: str
) -> None:
    tenant_id, agent_id = await _tenant("d943-call")
    phone = _fresh_phone()
    await _ledger(tenant_id, phone, status, source, timedelta(days=10), purpose=purpose)
    call_id = await _call_row(tenant_id, agent_id, phone)
    with pytest.raises(ProblemError) as refused:
        await _spoken_call_yes(tenant_id, phone, call_id)
    assert refused.value.code == "consent_reask_locked"
    assert await _granted(tenant_id, phone, "callback") == 0


async def test_a_call_consent_yes_after_ninety_days_is_accepted() -> None:
    tenant_id, agent_id = await _tenant("d943-call-old")
    phone = _fresh_phone()
    await _ledger(
        tenant_id, phone, "declined", "web_form_optin", timedelta(days=91), purpose="callback"
    )
    call_id = await _call_row(tenant_id, agent_id, phone)
    await _spoken_call_yes(tenant_id, phone, call_id)
    assert await _granted(tenant_id, phone, "callback") == 1


async def test_the_call_lockout_leaves_the_whatsapp_rules_as_they_were() -> None:
    """A no to messages does not lock a call ask, a no to calls does not lock a WhatsApp ask,
    and a messaging yes the client records from a call is filed as before."""
    tenant_id, agent_id = await _tenant("d943-call-wa")
    phone = _fresh_phone()
    await _ledger(tenant_id, phone, "declined", "in_call_agent_question", timedelta(days=5))
    call_id = await _call_row(tenant_id, agent_id, phone)
    await _spoken_call_yes(tenant_id, phone, call_id)
    assert await _granted(tenant_id, phone, "callback") == 1

    other = _fresh_phone()
    await _ledger(
        tenant_id, other, "declined", "web_form_optin", timedelta(days=5), purpose="callback"
    )
    async with tenant_session(tenant_id) as session:
        assert (
            await reask_locked_until(
                session, tenant_id=tenant_id, phone_e164=other, purpose="messaging"
            )
            is None
        )
    locked = _fresh_phone()
    await _ledger(tenant_id, locked, "declined", "in_call_agent_question", timedelta(days=5))
    other_call = await _call_row(tenant_id, agent_id, locked)
    async with tenant_session(tenant_id) as session:
        await record_messaging_consent(
            session,
            tenant_id=tenant_id,
            raw_phone=locked,
            status="granted",
            source="inbound_call_verbal",
            call_id=other_call,
            evidence={"transcript_turn": "2"},
        )
        await session.commit()
    assert await _granted(tenant_id, locked, "messaging") == 1


async def test_the_agent_is_not_given_a_call_back_to_offer_inside_the_lockout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call-back tool is the in-call place a call-consent yes is collected: inside the
    window it books nothing, files nothing, and tells the agent not to offer one."""
    from apps.api.worker import in_call_tools as tools
    from calevate_shared.worker_api import CallbackBookIn

    async def _not_restricted(session: object, *, tenant_id: UUID) -> None:
        return None

    monkeypatch.setattr(tools, "restricting_trial", _not_restricted)
    tenant_id, agent_id = await _tenant("d943-call-cb")
    phone = _fresh_phone()
    await _ledger(
        tenant_id, phone, "withdrawn", "inbound_call_verbal", timedelta(days=3), purpose="marketing"
    )
    call_id = await _call_row(tenant_id, agent_id, phone)

    async def _locate(session: object) -> tools.ToolCall:
        return tools.ToolCall(
            id=call_id, agent_id=agent_id, direction="outbound", from_e164=None, to_e164=phone
        )

    tomorrow = (datetime.now(UTC) + timedelta(days=1)).astimezone(IST).date().isoformat()
    out = await tools.book_callback_for(
        tenant_id,
        f"exec-{uuid.uuid4().hex[:8]}",
        CallbackBookIn.model_validate(
            {"callback_date": tomorrow, "callback_time": "11:00", "confirmed": True}
        ),
        locate=_locate,
    )
    assert out.status == "not_booked" and out.reason == tools.CALLBACK_REASK_LOCKED_RULE
    assert "do NOT offer a call-back" in out.say
    assert await _granted(tenant_id, phone, "callback") == 0
    async with tenant_session(tenant_id) as session:
        booked = (
            await session.execute(
                text("SELECT count(*) FROM scheduled_callbacks WHERE phone_e164 = :p"),
                {"p": phone},
            )
        ).scalar_one()
    assert booked == 0


# --- the rights desk -------------------------------------------------------------------


async def test_the_desk_fixes_the_deadline_from_when_the_person_asked() -> None:
    tenant_id, _agent = await _tenant("d943-desk")
    phone = _fresh_phone()
    asked = datetime.now(UTC) - timedelta(days=80)
    async with tenant_session(tenant_id) as session:
        logged = await rights_desk.log_request(
            session,
            tenant_id=tenant_id,
            kind="access",
            channel="email",
            phone_e164=phone,
            received_at=asked,
            created_by=None,
        )
        overdue = await rights_desk.log_request(
            session,
            tenant_id=tenant_id,
            kind="erasure",
            channel="letter",
            phone_e164=_fresh_phone(),
            received_at=datetime.now(UTC) - timedelta(days=95),
            created_by=None,
        )
        counts = await rights_desk.counts(session)
        listed = await rights_desk.list_requests(session)
        queue = await attention_queue(session)
        await session.commit()
    assert logged.due_at - logged.received_at == timedelta(days=90)
    assert logged.subject_ref == subject_ref(phone)
    assert (counts.open, counts.due_soon, counts.overdue) == (2, 1, 1)
    # Open first, soonest deadline first.
    assert [r.id for r in listed] == [overdue.id, logged.id]
    assert queue["counts"]["rights_request_due"] == 2


async def test_a_request_is_closed_once_and_only_with_an_answer_that_fits() -> None:
    tenant_id, _agent = await _tenant("d943-close")
    async with tenant_session(tenant_id) as session:
        request = await rights_desk.log_request(
            session,
            tenant_id=tenant_id,
            kind="access",
            channel="phone",
            phone_e164=_fresh_phone(),
            received_at=None,
            created_by=None,
        )
        with pytest.raises(ProblemError) as wrong:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="erased",
                deletion_request_id=None,
                closed_by=None,
            )
        assert wrong.value.code == "rights_outcome_mismatch"
        closed = await rights_desk.close_request(
            session,
            request_id=request.id,
            status="answered",
            outcome="exported",
            deletion_request_id=None,
            closed_by=None,
        )
        assert closed.status == "answered"
        assert closed.closed_at is not None
        with pytest.raises(ProblemError) as again:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="explained",
                deletion_request_id=None,
                closed_by=None,
            )
        assert again.value.code == "rights_request_closed"
        await session.commit()


async def test_an_erasure_is_answered_only_by_an_erasure_of_the_same_person() -> None:
    tenant_id, _agent = await _tenant("d943-erase")
    phone, other = _fresh_phone(), _fresh_phone()
    async with tenant_session(tenant_id) as session:
        request = await rights_desk.log_request(
            session,
            tenant_id=tenant_id,
            kind="erasure",
            channel="whatsapp",
            phone_e164=phone,
            received_at=None,
            created_by=None,
        )
        deletion_ids = {}
        for number in (phone, other):
            deletion_ids[number] = uuid7()
            await session.execute(
                text(
                    "INSERT INTO deletion_requests (id, tenant_id, phone_e164, subject_ref, "
                    "requested_at, created_at) VALUES (:id, :t, :p, :ref, now(), now())"
                ),
                {
                    "id": deletion_ids[number],
                    "t": tenant_id,
                    "p": number,
                    "ref": subject_ref(number),
                },
            )
        with pytest.raises(ProblemError) as unlinked:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="erased",
                deletion_request_id=None,
                closed_by=None,
            )
        assert unlinked.value.code == "rights_erasure_not_linked"
        with pytest.raises(ProblemError) as stranger:
            await rights_desk.close_request(
                session,
                request_id=request.id,
                status="answered",
                outcome="erased",
                deletion_request_id=deletion_ids[other],
                closed_by=None,
            )
        assert stranger.value.code == "rights_erasure_other_person"
        closed = await rights_desk.close_request(
            session,
            request_id=request.id,
            status="answered",
            outcome="erased",
            deletion_request_id=deletion_ids[phone],
            closed_by=None,
        )
        await session.rollback()
    assert closed.deletion_request_id == deletion_ids[phone]


async def test_a_request_from_the_future_is_refused() -> None:
    tenant_id, _agent = await _tenant("d943-future")
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await rights_desk.log_request(
                session,
                tenant_id=tenant_id,
                kind="correction",
                channel="email",
                phone_e164=_fresh_phone(),
                received_at=datetime.now(UTC) + timedelta(days=2),
                created_by=None,
            )
    assert refused.value.code == "rights_received_in_future"


async def test_another_account_sees_none_of_the_desk() -> None:
    """Hard rule 1: the table is FORCE-RLS'd; another tenant reads zero rows."""
    owner, _a = await _tenant("d943-rls-a")
    stranger, _b = await _tenant("d943-rls-b")
    async with tenant_session(owner) as session:
        await rights_desk.log_request(
            session,
            tenant_id=owner,
            kind="grievance",
            channel="in_person",
            phone_e164=_fresh_phone(),
            received_at=None,
            created_by=None,
        )
        await session.commit()
    async with tenant_session(stranger) as session:
        seen = (
            await session.execute(text("SELECT count(*) FROM data_rights_requests"))
        ).scalar_one()
        assert seen == 0
        with pytest.raises(Exception):  # noqa: B017 — the policy's WITH CHECK refuses it
            await session.execute(
                text(
                    "INSERT INTO data_rights_requests (id, tenant_id, kind, channel, "
                    "subject_ref, received_at, due_at) VALUES (:id, :t, 'access', 'email', "
                    ":ref, now(), now() + interval '90 days')"
                ),
                {"id": uuid7(), "t": owner, "ref": "0" * 32},
            )


# --- the short notice ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("language", "marker"), [("en", "Your rights"), ("te", "మీ హక్కులు"), ("hi", "आपके अधिकार")]
)
async def test_the_short_notice_in_each_language(language: str, marker: str) -> None:
    tenant_id, _agent = await _tenant(f"d943-notice-{language}")
    async with tenant_session(tenant_id) as session:
        body = await build_short_notice(session, tenant_id=tenant_id, language=language)  # type: ignore[arg-type]
    assert marker in body
    assert "{{YOUR REGISTERED BUSINESS NAME}}" in body
    assert "{{YOUR CONTACT FOR DATA QUESTIONS" in body
    assert "90" in body
    assert "Calevate" in body


# --- the campaign launch refusal ---------------------------------------------------------


async def _put_live(tenant_id: UUID, agent_id: UUID, script: dict[str, object]) -> None:
    async with tenant_session(tenant_id) as session:
        version = (
            await session.execute(
                text(
                    "SELECT coalesce(max(version), 0) + 1 FROM prompt_versions WHERE agent_id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        version_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "structured_script, created_at, updated_at) VALUES (:id, :t, :a, :v, 'body', "
                "CAST(:s AS jsonb), now(), now())"
            ),
            {
                "id": version_id,
                "t": tenant_id,
                "a": agent_id,
                "v": version,
                "s": json.dumps(script),
            },
        )
        await session.execute(
            text("UPDATE agents SET live_prompt_id = :v, system_prompt_id = :v WHERE id = :a"),
            {"v": version_id, "a": agent_id},
        )
        await session.commit()


async def test_a_service_campaign_with_an_offer_in_its_live_script_cannot_launch() -> None:
    from tests.campaigns_test import _ready_campaign

    tenant_id, agent_id, campaign_id = await _ready_campaign(classification="service", series="160")
    async with tenant_session(tenant_id) as session:
        before = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert SCRIPT_PROMOTIONAL_RULE not in {b.rule for b in before}

    await _put_live(
        tenant_id,
        agent_id,
        {"opening_line": "Hello! We have a special Diwali offer, 20% off, today only."},
    )
    async with tenant_session(tenant_id) as session:
        after = await campaigns_service.launch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        check = await agent_check(session, agent_id)
    assert SCRIPT_PROMOTIONAL_RULE in {b.rule for b in after}
    assert check.report.verdict == "promotional"


async def test_an_offer_put_live_after_launch_stops_the_running_campaign() -> None:
    """The launch gate is a photograph: a script edited mid-campaign is read every tick."""
    from tests.campaigns_test import _ready_campaign

    tenant_id, agent_id, campaign_id = await _ready_campaign(classification="service", series="160")
    async with tenant_session(tenant_id) as session:
        before = await campaigns_service.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert SCRIPT_PROMOTIONAL_RULE not in {b.rule for b in before}

    await _put_live(
        tenant_id,
        agent_id,
        {"opening_line": "Hello! We have a special Diwali offer, 20% off, today only."},
    )
    async with tenant_session(tenant_id) as session:
        after = await campaigns_service.dispatch_blockers(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert SCRIPT_PROMOTIONAL_RULE in {b.rule for b in after}
