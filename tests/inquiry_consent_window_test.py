"""The inquiry window: a lead-form consent authorises calls for seven days, then stops.

TCCCPR Third Amendment (18 Sep 2026) permits commercial calls based on a customer's written
or digital inquiry for seven days from it (REPORTED —
`docs/evidence/trai-tcccpr-third-amendment-2026-09-18.md` row 7). The form writer sets the
expiry on the row and the dial gate's `consent_expired` enforces it, so these tests drive
the real writer and the real gate rather than a constant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from uuid import UUID

import pytest
from apps.api.compliance.models import INQUIRY_CONSENT_WINDOW_DAYS
from apps.api.compliance.service import DispatchDecision, check_dispatch
from apps.api.db.session import tenant_session
from apps.api.ingest.service import _record_dial_consent_granted
from sqlalchemy import text
from tests.outbound_consent_policy_test import _fresh_phone, _tenant

pytestmark = pytest.mark.asyncio

#: 11:00 IST, the middle of the calling window, so the hours rule can never be what refuses.
_PINNED_IST = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)


async def _record_form_consent(tenant_id: UUID, phone: str) -> None:
    async with tenant_session(tenant_id) as session:
        await _record_dial_consent_granted(
            session,
            tenant_id=tenant_id,
            phone_e164=phone,
            consent_field="call_me",
            source="website",
        )
        await session.commit()


async def _gate_after(days: int, tenant_id: UUID, agent_id: UUID, phone: str) -> DispatchDecision:
    """The dial gate, `days` from now.

    `consent_ledger` is append-only, so a row cannot be backdated; the gate is taken forward
    instead. Only the gate module's `datetime.now` moves, and only the consent-expiry clause
    reads it; the calling hours are pinned so they can never be what refuses.
    """

    class _Later(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> _Later:
            moved = datetime.now(UTC) + timedelta(days=days)
            return cls.fromtimestamp(moved.timestamp(), tz=tz)

    monkey = pytest.MonkeyPatch()
    monkey.setattr("apps.api.compliance.service.datetime", _Later)
    monkey.setattr("apps.api.compliance.service.ist_now", lambda: _PINNED_IST)
    try:
        async with tenant_session(tenant_id) as session:
            return await check_dispatch(
                session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
            )
    finally:
        monkey.undo()


async def test_a_form_consent_carries_exactly_the_inquiry_window() -> None:
    tenant_id, _agent_id = await _tenant("inq-window")
    phone = _fresh_phone()
    await _record_form_consent(tenant_id, phone)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT consent_source, EXTRACT(EPOCH FROM expires_at - captured_at) "
                    "FROM consent_ledger WHERE tenant_id = :t AND phone_e164 = :p"
                ),
                {"t": tenant_id, "p": phone},
            )
        ).one()

    assert row[0] == "web_form_optin"
    assert row[1] == INQUIRY_CONSENT_WINDOW_DAYS * 86400
    assert INQUIRY_CONSENT_WINDOW_DAYS == 7


async def test_a_dial_inside_the_window_is_allowed() -> None:
    tenant_id, agent_id = await _tenant("inq-inside")
    phone = _fresh_phone()
    await _record_form_consent(tenant_id, phone)

    decision = await _gate_after(INQUIRY_CONSENT_WINDOW_DAYS - 1, tenant_id, agent_id, phone)

    assert decision.allowed is True, decision.rule


async def test_a_dial_after_the_window_is_refused_as_expired_consent() -> None:
    """Every dial path reaches this clause through `check_dispatch`, so one refusal here is
    the callback, the campaign retry, the recall and "call now" all at once."""
    tenant_id, agent_id = await _tenant("inq-after")
    phone = _fresh_phone()
    await _record_form_consent(tenant_id, phone)

    decision = await _gate_after(INQUIRY_CONSENT_WINDOW_DAYS + 1, tenant_id, agent_id, phone)

    assert decision.allowed is False
    assert decision.rule == "consent_expired"


async def test_a_fresh_inquiry_restarts_the_window() -> None:
    """The gate reads the latest row for the person, so a second submission is a new inquiry
    with its own seven days rather than a lapsed one."""
    tenant_id, agent_id = await _tenant("inq-fresh")
    phone = _fresh_phone()
    await _record_form_consent(tenant_id, phone)
    await _record_form_consent(tenant_id, phone)

    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM consent_ledger WHERE tenant_id = :t AND phone_e164 = :p"
                ),
                {"t": tenant_id, "p": phone},
            )
        ).scalar_one()
    assert count == 2
    assert (await _gate_after(1, tenant_id, agent_id, phone)).allowed is True


async def test_a_consent_a_client_records_from_elsewhere_carries_no_window() -> None:
    """Only the form writer sets the window. A consent a client records from a paper form
    has an inquiry date we never saw, so it keeps the gate's old behaviour and is gate 60's
    open question rather than this rule's."""
    tenant_id, agent_id = await _tenant("inq-verbal")
    phone = _fresh_phone()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO consent_ledger (id, tenant_id, phone_e164, purpose, status, "
                "consent_source, evidence, captured_at, created_at) VALUES "
                "(:id, :tid, :p, 'callback', 'granted', 'offline_form_optin', "
                "CAST(:ev AS jsonb), now(), now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "p": phone,
                "ev": '{"form": "walk-in register", "page": 12}',
            },
        )
        await session.commit()

    decision = await _gate_after(INQUIRY_CONSENT_WINDOW_DAYS + 30, tenant_id, agent_id, phone)

    assert decision.allowed is True, decision.rule
