"""`/v1/analytics/*` (D-869): the heatmap, the ridgeline, the timelines and the stats band.

Every fixture instant is written as IST wall clock and stored as the UTC instant, because
the defect these charts are most exposed to — bucketing by the UTC date or hour — is
invisible to a test that builds its rows in UTC. 20:00 IST on a Monday is 14:30 UTC the
same day, and 02:00 IST on a Tuesday is 20:30 UTC on the Monday.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.analytics import service
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api_security_test import _make_tenant

_IST = timedelta(hours=5, minutes=30)


def _today_ist() -> date:
    return (datetime.now(UTC) + _IST).date()


def _ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - _IST


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _agent(session: AsyncSession) -> uuid.UUID:
    return uuid.UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))


async def _call(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    at: datetime,
    status: str = "completed",
    duration_s: int | None = 60,
    outcome: str | None = None,
    campaign_id: uuid.UUID | None = None,
) -> uuid.UUID:
    call_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
            "started_at, duration_s, outcome_tag, campaign_id, created_at, updated_at) VALUES "
            "(:id, :tid, :aid, :ecid, 'inbound', :status, :at, :dur, :outcome, :cid, :at, now())"
        ),
        {
            "id": call_id,
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": f"an-{uuid.uuid4().hex}",
            "status": status,
            "at": at,
            "dur": duration_s,
            "outcome": outcome,
            "cid": campaign_id,
        },
    )
    return call_id


def _monday_before(day: date) -> date:
    return day - timedelta(days=day.weekday() + 7)


async def test_heatmap_buckets_by_ist_weekday_and_hour_and_always_has_168_cells() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    monday = _monday_before(_today_ist())
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        # 20:00 IST Monday (14:30 UTC Monday) and 02:00 IST Tuesday (20:30 UTC Monday).
        await _call(session, tenant_id, agent_id, at=_ist(monday, 20))
        await _call(session, tenant_id, agent_id, at=_ist(monday, 20, 30))
        await _call(session, tenant_id, agent_id, at=_ist(monday + timedelta(days=1), 2))
        window = service.resolve_window(days=30, to=None)
        out = await service.heatmap(
            session, window=window, metric="calls", agent_id=None, test_calls=True
        )

    assert len(out.cells) == 7 * 24
    cells = {(c.weekday, c.hour): c.count for c in out.cells}
    assert cells[(1, 20)] == 2
    assert cells[(2, 2)] == 1
    # The UTC reading would have put all three on Monday at 14 and 20.
    assert cells[(1, 14)] == 0
    assert out.total == 3
    assert out.max_count == 2


async def test_durations_bin_completed_calls_per_outcome_and_keep_long_calls() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    day = _today_ist() - timedelta(days=1)
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        for seconds in (10, 45, 50, 5000):
            await _call(
                session,
                tenant_id,
                agent_id,
                at=_ist(day, 11),
                duration_s=seconds,
                outcome="answered",
            )
        # A failed dial has no conversation length and is not counted.
        await _call(session, tenant_id, agent_id, at=_ist(day, 12), status="failed", duration_s=0)
        out = await service.durations(
            session,
            window=service.resolve_window(days=7, to=None),
            group_by="outcome",
            bin_s=30,
            limit=8,
            agent_id=None,
            test_calls=True,
        )

    assert out.bin_edges_s[:3] == [0, 30, 60]
    [group] = out.groups
    assert group.key == "answered"
    assert group.calls == 4
    assert group.counts[0] == 1  # 10 s
    assert group.counts[1] == 2  # 45 s, 50 s
    assert group.counts[-1] == 1  # 5000 s lands in the open-ended last bin
    assert sum(group.counts) == group.calls
    assert out.other_calls == 0


async def test_timeline_is_zero_filled_oldest_first_and_counts_answered_and_leads() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(session, tenant_id, agent_id, at=_ist(today - timedelta(days=2), 10))
        await _call(
            session,
            tenant_id,
            agent_id,
            at=_ist(today - timedelta(days=2), 11),
            status="no_answer",
            duration_s=None,
        )
        out = await service.timeline(
            session,
            window=service.resolve_window(days=5, to=None),
            agent_id=None,
            test_calls=True,
        )

    assert [d.ist_date for d in out.days] == [today - timedelta(days=i) for i in range(4, -1, -1)]
    by_day = {d.ist_date: d for d in out.days}
    assert by_day[today - timedelta(days=2)].calls == 2
    assert by_day[today - timedelta(days=2)].answered == 1
    assert by_day[today - timedelta(days=3)].calls == 0
    # `_make_tenant` inserted one lead, created now.
    assert by_day[today].leads == 1
    assert (out.calls, out.answered, out.leads) == (2, 1, 1)


async def test_campaign_timeline_counts_dials_connected_and_the_leads_it_created() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    day = _today_ist() - timedelta(days=1)
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 'Diwali offer', 'service', "
                "'running', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent_id},
        )
        first = await _call(session, tenant_id, agent_id, at=_ist(day, 10), campaign_id=campaign_id)
        await _call(
            session,
            tenant_id,
            agent_id,
            at=_ist(day, 11),
            status="no_answer",
            duration_s=None,
            campaign_id=campaign_id,
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "first_call_id, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, "
                "'campaign', 'new', :fc, :at, now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "phone": f"+9197{uuid.uuid4().int % 100000000:08d}",
                "fc": first,
                "at": _ist(day, 10, 5),
            },
        )
        out = await service.campaign_timelines(
            session, window=service.resolve_window(days=7, to=None), campaign_id=None, limit=5
        )

    [series] = out.campaigns
    assert series.campaign_id == campaign_id
    assert (series.dials, series.connected, series.leads) == (2, 1, 1)
    assert len(series.days) == 7
    assert {d.ist_date: d.dials for d in series.days}[day] == 2


async def test_stats_compare_with_the_same_length_of_time_before() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        for _ in range(4):
            await _call(session, tenant_id, agent_id, at=_ist(today - timedelta(days=1), 10))
        for _ in range(2):
            await _call(session, tenant_id, agent_id, at=_ist(today - timedelta(days=8), 10))
        out = await service.stats(
            session,
            window=service.resolve_window(days=7, to=None),
            agent_id=None,
            test_calls=True,
        )

    assert out.previous_window.to_date == out.window.from_date - timedelta(days=1)
    metrics = {m.key: m for m in out.metrics}
    assert metrics["calls"].value == Decimal(4)
    assert metrics["calls"].previous == Decimal(2)
    assert metrics["calls"].change_pct == Decimal("100.0")
    assert metrics["answer_rate_pct"].value == Decimal("100.0")
    assert metrics["talk_minutes"].value == Decimal("4.0")


def test_change_pct_has_no_percentage_from_nothing() -> None:
    assert service.change_pct(Decimal(5), Decimal(0)) is None
    assert service.change_pct(None, Decimal(3)) is None
    assert service.change_pct(Decimal(3), Decimal(4)) == Decimal("-25.0")


def test_a_range_ending_in_the_future_is_refused() -> None:
    with pytest.raises(ProblemError) as refused:
        service.resolve_window(days=7, to=_today_ist() + timedelta(days=1))
    assert refused.value.code == "analytics_range_in_future"
    with pytest.raises(ProblemError):
        service.resolve_window(days=service.MAX_RANGE_DAYS + 1, to=None)


async def test_the_routes_answer_for_the_session_tenant_only() -> None:
    """Hard rule 1 through the router: tenant B's calls never reach tenant A's charts."""
    _tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    async with tenant_session(tenant_b) as session:
        agent_b = await _agent(session)
        for _ in range(3):
            await _call(session, tenant_b, agent_b, at=_ist(_today_ist(), 10))

    headers = {"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_a}
    async with _client() as http:
        heat = await http.get("/v1/analytics/heatmap?days=7", headers=headers)
        timeline = await http.get("/v1/analytics/timeline?days=7", headers=headers)
        stats = await http.get("/v1/analytics/stats?days=7", headers=headers)
        durations = await http.get("/v1/analytics/durations?days=7&bin_s=30", headers=headers)
        campaigns = await http.get("/v1/analytics/campaigns?days=7", headers=headers)
        bad_bin = await http.get("/v1/analytics/durations?bin_s=7", headers=headers)
        too_long = await http.get("/v1/analytics/heatmap?days=400", headers=headers)
        anonymous = await http.get("/v1/analytics/heatmap")

    assert heat.status_code == 200, heat.text
    assert heat.json()["total"] == 0
    assert timeline.json()["calls"] == 0
    assert {m["key"]: m["value"] for m in stats.json()["metrics"]}["calls"] == "0"
    assert durations.json()["groups"] == []
    assert campaigns.json()["campaigns"] == []
    assert bad_bin.status_code == 422
    assert too_long.status_code == 422
    assert anonymous.status_code == 401
