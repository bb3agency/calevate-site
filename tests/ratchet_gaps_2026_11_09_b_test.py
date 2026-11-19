"""Dial and dispatcher branches the coverage ratchet measured uncovered.

FAILS IF: a dial from another agent's number is not held and lent to the dialling agent; a
number that could not be lent leaves the call `queued` or raises anything but
`client_number_unavailable`; an unreachable Redis does not hold every candidate bulk job; or
a bulk job held for less than the alarm age raises an alert.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.campaigns import engine_numbers
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import dispatcher
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.callback_dispatch_test import _dialable_tenant

pytestmark = pytest.mark.rls

_TENANTS: list[UUID] = []


@pytest.fixture
async def _settle_rows() -> AsyncIterator[None]:
    """A placed dial's row stays `queued` and holds a platform-wide line; release it."""
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE calls SET status = 'completed', updated_at = now() "
                    "WHERE status = 'queued'"
                )
            )
    _TENANTS.clear()


@pytest.fixture
async def tenant(_settle_rows: None) -> tuple[UUID, UUID]:
    reset_engine_cache()
    tenant_id, agent_id = await _dialable_tenant()
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


@pytest.fixture
def borrowed_line(monkeypatch: pytest.MonkeyPatch) -> agents_service.CallerLine:
    """Another agent's number, on an engine that rings only from numbers lent to the caller."""
    line = agents_service.CallerLine(
        number_id=uuid7(),
        e164=f"+91160{uuid.uuid4().int % 10**6:06d}",
        own=False,
        engine_number_ref=f"num_{uuid.uuid4().hex[:10]}",
    )

    async def _choose(*_a: Any, **_k: Any) -> agents_service.CallerLine:
        return line

    monkeypatch.setattr(agents_service, "choose_caller_line", _choose)
    monkeypatch.setattr(agents_service, "outbound_number_provider", lambda: "thinnest")
    return line


def _phone() -> str:
    return f"+9198764{uuid.uuid4().int % 10**5:05d}"


async def _calls(tenant_id: UUID, phone: str) -> list[tuple[str, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT status, from_e164 FROM calls WHERE to_e164 = :p"), {"p": phone}
            )
        ).all()
    return [(str(row[0]), row[1]) for row in rows]


async def _dial(tenant_id: UUID, agent_id: UUID, phone: str) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.dispatch_call(
            session, tenant_id=tenant_id, agent_id=agent_id, lead_id=None, phone_e164=phone
        )


# --- dispatch_call from a borrowed number ------------------------------------------------


async def test_a_borrowed_number_is_held_and_lent_before_the_dial(
    tenant: tuple[UUID, UUID],
    borrowed_line: agents_service.CallerLine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = tenant
    held: list[UUID] = []
    lent: list[str] = []
    real_hold = agents_service._hold_client_number

    async def _hold(
        session: AsyncSession, *, number: agents_service.CallerLine, engine_agent_ref: str
    ) -> None:
        held.append(number.number_id)
        await real_hold(session, number=number, engine_agent_ref=engine_agent_ref)

    async def _lend(number_ref: str, agent_ref: str) -> bool:
        lent.append(number_ref)
        return True

    monkeypatch.setattr(agents_service, "_hold_client_number", _hold)
    monkeypatch.setattr(engine_numbers, "lend_client_number", _lend)
    phone = _phone()
    assert await _dial(tenant_id, agent_id, phone)
    assert held == [borrowed_line.number_id]
    assert lent == [borrowed_line.engine_number_ref]
    assert await _calls(tenant_id, phone) == [("queued", borrowed_line.e164)]


async def test_a_number_that_cannot_be_lent_closes_the_dial_unplaced(
    tenant: tuple[UUID, UUID],
    borrowed_line: agents_service.CallerLine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = tenant

    async def _refuse(number_ref: str, agent_ref: str) -> bool:
        return False

    monkeypatch.setattr(engine_numbers, "lend_client_number", _refuse)
    phone = _phone()
    with pytest.raises(ProblemError) as raised:
        await _dial(tenant_id, agent_id, phone)
    assert raised.value.code == agents_service.CLIENT_NUMBER_UNAVAILABLE_RULE
    # Every caller reads it as not placed: a lead's call-back is booked, the button's
    # idempotency claim is released, and the test-call cap does not count it.
    assert agents_service.dial_was_not_placed(raised.value)
    assert await _calls(tenant_id, phone) == [("failed", borrowed_line.e164)]
    async with tenant_session(tenant_id) as session:
        reason = (
            await session.execute(
                text("SELECT not_placed_reason FROM calls WHERE to_e164 = :p"), {"p": phone}
            )
        ).scalar_one()
    assert reason == "refused"


@pytest.mark.parametrize(
    "code",
    [
        agents_service.CLIENT_NUMBER_UNAVAILABLE_RULE,
        agents_service.TRIAL_LINE_UNAVAILABLE_RULE,
        agents_service.TRIAL_LINE_BUSY_RULE,
        agents_service.PAID_TEST_DAILY_CAP_RULE,
        agents_service.TRIAL_STUDIO_MINUTES_USED_RULE,
    ],
)
def test_a_refusal_raised_before_the_dial_reads_as_not_placed(code: str) -> None:
    refused = ProblemError.business_rule(code, "Not now.", remediation="Try again.")
    assert agents_service.dial_was_not_placed(refused)


# --- dispatcher._bulk_jobs_held ----------------------------------------------------------

_PROBE_BULK_JOB = f"ratchet_gaps_bulk_probe_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def probe_alerts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A bulk job no outbox row names, so the held count is this module's alone."""
    monkeypatch.setattr(dispatcher, "BULK_JOBS", frozenset({_PROBE_BULK_JOB}))
    raised: list[str] = []
    monkeypatch.setattr(dispatcher, "alert", lambda _stage, code, **_k: raised.append(code))
    return raised


async def test_an_unreachable_redis_holds_every_candidate_bulk_job(
    probe_alerts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _down(_queue: object) -> frozenset[str]:
        raise RedisError("connection refused")

    monkeypatch.setattr(dispatcher, "bulk_jobs_served", _down)
    async with untenanted_session() as session:
        held = await dispatcher._bulk_jobs_held(session, None)
    assert held == {_PROBE_BULK_JOB}
    assert probe_alerts == []


async def test_a_bulk_job_held_inside_the_alarm_age_raises_no_alert(
    probe_alerts: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _none_served(_queue: object) -> frozenset[str]:
        return frozenset()

    monkeypatch.setattr(dispatcher, "bulk_jobs_served", _none_served)
    async with untenanted_session() as session:
        held = await dispatcher._bulk_jobs_held(session, frozenset({_PROBE_BULK_JOB}))
    assert held == {_PROBE_BULK_JOB}
    assert probe_alerts == []
