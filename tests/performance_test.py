"""Performance analytics (teardown §5 floor).

The tests pin the DEFINITIONS, because the definitions are where an analytics tab
quietly lies: voicemail counted as "connected" inflates a connect rate, a call-level
"qualified" count rewards activity over conversion, and a UTC busiest-hours histogram
of an Indian business day is off by five and a half hours.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.crm.performance import performance
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Perf Clinic",
        slug=f"perf-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    status: str,
    duration_s: int | None = None,
    outcome: str | None = None,
    direction: str = "outbound",
    started_ist_hour: int | None = 11,
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, duration_s, outcome_tag, started_at, created_at, updated_at) "
                "VALUES (:i, :t, :a, :e, :dir, '+919876500001', :st, :dur, :out, "
                # started_at is stored UTC; the IST hour the test asks for is 5:30 ahead.
                "  CASE WHEN :h IS NULL THEN NULL ELSE "
                "    date_trunc('day', now()) + make_interval(hours => :h) "
                "      - interval '5 hours 30 minutes' END, "
                "now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": f"perf_{uuid.uuid4().hex[:12]}",
                "dir": direction,
                "st": status,
                "dur": duration_s,
                "out": outcome,
                "h": started_ist_hour,
            },
        )


async def test_voicemail_and_no_answer_are_dials_not_conversations() -> None:
    tenant_id, agent_id = await _tenant()
    await _call(tenant_id, agent_id, status="completed", duration_s=120, outcome="resolved")
    await _call(tenant_id, agent_id, status="no_answer")
    await _call(tenant_id, agent_id, status="voicemail")
    await _call(tenant_id, agent_id, status="busy")

    async with tenant_session(tenant_id) as session:
        result = await performance(session)

    assert result["funnel"]["calls"] == 4
    assert result["funnel"]["connected"] == 1, "voicemail/no-answer/busy do not inflate this"
    assert result["connect_rate_pct"] == 25
    assert result["outcomes"]["resolved"] == 1
    assert result["outcomes"]["no_answer"] == 1, "un-tagged calls report their status honestly"


async def test_qualified_counts_leads_not_calls() -> None:
    """Three calls that move one lead to `interested` are ONE qualified outcome."""
    tenant_id, agent_id = await _tenant()
    for _ in range(3):
        await _call(tenant_id, agent_id, status="completed", duration_s=60)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, '+919876500001', 'inbound_call', "
                "'interested', now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id},
        )
        result = await performance(session)

    assert result["funnel"] == {"calls": 3, "connected": 3, "qualified": 1}
    assert result["qualify_rate_pct"] == 33, "1 of 3 connected conversations converted"


async def test_rates_are_none_not_zero_before_any_calls() -> None:
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        result = await performance(session)
    assert result["connect_rate_pct"] is None
    assert result["qualify_rate_pct"] is None
    assert result["busiest_hours_ist"] == [0] * 24, "all 24 buckets, even when silent"


async def test_busiest_hours_bucket_in_ist_not_utc() -> None:
    """A call at 11:00 IST is 05:30 UTC. Bucketing by UTC hour would file it under 5,
    and the owner would staff the counter for a rush that happens at eleven."""
    tenant_id, agent_id = await _tenant()
    await _call(tenant_id, agent_id, status="completed", duration_s=30, started_ist_hour=11)
    await _call(tenant_id, agent_id, status="completed", duration_s=30, started_ist_hour=11)
    await _call(tenant_id, agent_id, status="completed", duration_s=30, started_ist_hour=19)

    async with tenant_session(tenant_id) as session:
        result = await performance(session)

    hours = result["busiest_hours_ist"]
    assert hours[11] == 2
    assert hours[19] == 1
    assert hours[5] == 0, "the UTC shadow of the 11:00 IST calls must be empty"
    assert sum(hours) == 3
