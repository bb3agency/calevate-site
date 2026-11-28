"""Speed to lead (W8.1), the narrowed stats band (W8.2), agents today (W8.3) and the weekly
call-quality scorecard (W8.5): `/v1/analytics/*` reads added in release 0.6.0 wave B.

A lead is fixed here the way `ingest_lead` leaves it: a lead row, a Follow-up run whose
`trigger_ref` is `delivery:<source>:<received ms>`, and the calls, holds and deferral notes
that followed. Every instant is a real UTC instant; the IST windows are the reads' business.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.api.analytics import service, speed, today
from apps.api.db.base import uuid7
from apps.api.db.session import get_engine, tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api_security_test import _make_tenant


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _agent(session: AsyncSession) -> uuid.UUID:
    return uuid.UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))


async def _source(session: AsyncSession, tenant_id: uuid.UUID, kind: str) -> uuid.UUID:
    source_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, mapping, active, "
            "created_at, updated_at) VALUES (:i, :t, :k, 's', CAST('{}' AS jsonb), true, "
            "now(), now())"
        ),
        {"i": source_id, "t": tenant_id, "k": kind},
    )
    return source_id


async def _follow_up(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    follow_up_id, version_id = uuid7(), uuid7()
    await session.execute(
        text(
            "INSERT INTO follow_ups (id, tenant_id, name, status, trigger, settings) VALUES "
            "(:f, :t, 'New leads', 'draft', '{\"kind\": \"manual\"}'::jsonb, '{}'::jsonb)"
        ),
        {"f": follow_up_id, "t": tenant_id},
    )
    await session.execute(
        text(
            "INSERT INTO follow_up_versions (id, tenant_id, follow_up_id, number, steps, "
            "trigger, settings) VALUES (:v, :t, :f, 1, "
            '\'[{"id": "s1", "kind": "end", "goal": true}]\'::jsonb, '
            "'{\"kind\": \"manual\"}'::jsonb, '{}'::jsonb)"
        ),
        {"v": version_id, "t": tenant_id, "f": follow_up_id},
    )
    return follow_up_id, version_id


class _Account:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.agent_id: uuid.UUID
        self.follow_up: tuple[uuid.UUID, uuid.UUID]
        self.n = 0

    async def setup(self) -> _Account:
        self.agent_id = await _agent(self.session)
        self.follow_up = await _follow_up(self.session, self.tenant_id)
        return self

    async def lead(
        self,
        source_id: uuid.UUID,
        *,
        arrived: datetime,
        run_status: str = "done",
        interested: bool = False,
        trigger: str | None = None,
    ) -> uuid.UUID:
        self.n += 1
        lead_id = uuid7()
        await self.session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "status_set_at, created_at, updated_at) VALUES (:id, :t, :a, :p, 'webhook', "
                ":s, :set, :at, now())"
            ),
            {
                "id": lead_id,
                "t": self.tenant_id,
                "a": self.agent_id,
                "p": f"+9198{uuid.uuid4().int % 10**8:08d}",
                "s": "interested" if interested else "new",
                "set": arrived + timedelta(minutes=5) if interested else None,
                "at": arrived,
            },
        )
        ref = trigger or f"delivery:{source_id}:{int(arrived.timestamp() * 1000)}"
        await self.session.execute(
            text(
                "INSERT INTO follow_up_runs (id, tenant_id, follow_up_id, version_id, lead_id, "
                "phone_e164, status, step_id, trigger_ref, started_at, ended_at) VALUES "
                "(:r, :t, :f, :v, :l, '+919800000000', :st, 's1', :ref, :at, "
                ":ended)"
            ),
            {
                "r": uuid7(),
                "t": self.tenant_id,
                "f": self.follow_up[0],
                "v": self.follow_up[1],
                "l": lead_id,
                "st": run_status,
                "ref": ref,
                "at": arrived,
                "ended": datetime.now(UTC) if run_status in ("done", "stopped") else None,
            },
        )
        return lead_id

    async def call(
        self,
        lead_id: uuid.UUID | None,
        *,
        at: datetime,
        status: str = "completed",
        direction: str = "outbound",
        campaign_id: uuid.UUID | None = None,
        test: bool = False,
        summary_state: str = "pending",
        goal: str | None = None,
    ) -> uuid.UUID:
        call_id = uuid7()
        await self.session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, duration_s, lead_id, campaign_id, trial_call, summary_state, "
                "goal_reached, created_at, updated_at) VALUES (:id, :t, :a, :e, :d, :s, :at, "
                ":dur, :l, :c, :test, :ss, :g, :at, now())"
            ),
            {
                "id": call_id,
                "t": self.tenant_id,
                "a": self.agent_id,
                "e": f"sp-{uuid.uuid4().hex}",
                "d": direction,
                "s": status,
                "at": at,
                "dur": 40 if status == "completed" else None,
                "l": lead_id,
                "c": campaign_id,
                "test": test,
                "ss": summary_state,
                "g": goal,
            },
        )
        return call_id

    async def hold(self, lead_id: uuid.UUID, *, held: datetime, released: datetime) -> None:
        await self.session.execute(
            text(
                "INSERT INTO lead_call_holds (id, tenant_id, lead_id, agent_id, source, status, "
                "held_at, settled_at) VALUES (:id, :t, :l, :a, 'website_form', 'released', "
                ":h, :r)"
            ),
            {
                "id": uuid7(),
                "t": self.tenant_id,
                "l": lead_id,
                "a": self.agent_id,
                "h": held,
                "r": released,
            },
        )

    async def deferred(
        self, lead_id: uuid.UUID, *, at: datetime, rule: str, callback_at: datetime
    ) -> None:
        await self.session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:id, :t, :l, 'note', CAST(:p AS jsonb), "
                "'system', :at, now())"
            ),
            {
                "id": uuid7(),
                "t": self.tenant_id,
                "l": lead_id,
                "p": json.dumps(
                    {"kind": "call_deferred", "rule": rule, "callback_at": callback_at.isoformat()}
                ),
                "at": at,
            },
        )


def _base() -> datetime:
    """Two hours ago: inside the last 24 hours and inside today's or yesterday's IST day."""
    return datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)


async def test_each_delivery_is_timed_from_arrival_to_our_first_call_per_source() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    t0 = _base()
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        form = await _source(session, tenant_id, "website_form")
        meta = await _source(session, tenant_id, "meta_lead_ads")
        quick = await acct.lead(form, arrived=t0, interested=True)
        await acct.call(quick, at=t0 + timedelta(seconds=20))
        slow = await acct.lead(form, arrived=t0 + timedelta(minutes=1))
        await acct.call(slow, at=t0 + timedelta(minutes=6), status="no_answer")
        await acct.lead(form, arrived=t0 + timedelta(minutes=2), run_status="waiting")
        await acct.lead(form, arrived=t0 + timedelta(minutes=3), run_status="stopped")
        held = await acct.lead(meta, arrived=t0 - timedelta(minutes=30))
        released = t0 + timedelta(minutes=20)
        await acct.hold(held, held=t0 - timedelta(minutes=30), released=released)
        await acct.call(held, at=released + timedelta(seconds=30))
        # A date-triggered run is not an arrival.
        await acct.lead(form, arrived=t0, trigger="date:birthday")
        # A call before the lead arrived is not its first call.
        await acct.call(quick, at=t0 - timedelta(days=1))
        out = await speed.speed_to_lead(session, period="7d")

    total = out.total
    assert total.leads == 5
    assert total.called == 3
    # Waits of 20 s, 300 s and 30 s (the held lead from its release): the median is 30.
    assert total.median_s == 30
    assert total.within_60s == 2
    assert total.reached == 2
    assert total.waiting == 1
    # Rung and never answered, and stopped before any call.
    assert total.never_reached == 2
    assert total.interested == 1
    assert total.from_release == 1
    assert [(s.source, s.leads) for s in out.sources] == [("website_form", 4), ("meta_lead_ads", 1)]
    assert out.sources[1].median_s == 30
    assert out.compare is None
    assert out.compare_min_leads == speed.SPEED_COMPARE_MIN_LEADS


async def test_after_hours_starts_at_the_opening_and_a_chosen_wait_does_not() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    t0 = _base() - timedelta(hours=20)
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        form = await _source(session, tenant_id, "website_form")
        night = await acct.lead(form, arrived=t0)
        opening = t0 + timedelta(hours=10)
        await acct.deferred(
            night, at=t0 + timedelta(seconds=1), rule="plan_after_hours", callback_at=opening
        )
        await acct.call(night, at=opening + timedelta(seconds=15))
        waited = await acct.lead(form, arrived=t0 + timedelta(hours=1))
        await acct.deferred(
            waited,
            at=t0 + timedelta(hours=1, seconds=1),
            rule="plan_wait",
            callback_at=t0 + timedelta(hours=1, minutes=2),
        )
        await acct.call(waited, at=t0 + timedelta(hours=1, minutes=2, seconds=5))
        out = await speed.speed_to_lead(session, period="7d")

    assert out.total.called == 2
    assert out.total.from_release == 1
    assert out.total.within_60s == 1
    # 15 s from the opening; 125 s from arrival for the wait the owner chose.
    assert out.total.median_s == 15


async def test_the_minute_comparison_appears_only_from_the_floor_with_both_counts() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    t0 = _base()
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        form = await _source(session, tenant_id, "website_form")
        for i in range(speed.SPEED_COMPARE_MIN_LEADS):
            fast = i < 20
            lead = await acct.lead(
                form, arrived=t0 - timedelta(minutes=i), interested=fast and i % 2 == 0
            )
            await acct.call(
                lead, at=t0 - timedelta(minutes=i) + timedelta(seconds=10 if fast else 600)
            )
        out = await speed.speed_to_lead(session, period="24h")

    assert out.window.period == "24h"
    assert out.compare is not None
    assert (out.compare.fast_called, out.compare.fast_interested) == (20, 10)
    assert (out.compare.later_called, out.compare.later_interested) == (10, 0)


async def test_the_route_reads_only_the_callers_account() -> None:
    _tenant_id, slug, token = await _make_tenant()
    other_id, _other_slug, _other_token = await _make_tenant()
    t0 = _base()
    async with tenant_session(other_id) as session:
        acct = await _Account(session, other_id).setup()
        form = await _source(session, other_id, "website_form")
        lead = await acct.lead(form, arrived=t0)
        await acct.call(lead, at=t0 + timedelta(seconds=5))
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        ok = await http.get("/v1/analytics/speed-to-lead?period=30d", headers=headers)
        bad = await http.get("/v1/analytics/speed-to-lead?period=1y", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["total"]["leads"] == 0
    assert ok.json()["sources"] == []
    assert bad.status_code == 422


async def test_the_band_narrows_to_a_campaign_and_direction_and_withholds_spend() -> None:
    tenant_id, slug, token = await _make_tenant()
    t0 = _base()
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, classification, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'Diwali', 'draft', 'service', "
                "now(), now())"
            ),
            {"id": campaign_id, "t": tenant_id, "a": acct.agent_id},
        )
        form = await _source(session, tenant_id, "website_form")
        keen = await acct.lead(form, arrived=t0, interested=True)
        cold = await acct.lead(form, arrived=t0)
        await acct.call(keen, at=t0 + timedelta(minutes=1), campaign_id=campaign_id)
        await acct.call(cold, at=t0 + timedelta(minutes=2), campaign_id=campaign_id)
        await acct.call(None, at=t0 + timedelta(minutes=3), direction="inbound")
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        whole = (await http.get("/v1/analytics/stats?days=7", headers=headers)).json()
        narrowed = (
            await http.get(
                f"/v1/analytics/stats?days=7&campaign_id={campaign_id}&direction=outbound",
                headers=headers,
            )
        ).json()
        inbound = (
            await http.get("/v1/analytics/stats?days=7&direction=inbound", headers=headers)
        ).json()

    def figures(body: dict[str, Any]) -> dict[str, Any]:
        return {m["key"]: m["value"] for m in body["metrics"]}

    assert figures(whole)["calls"] == "3"
    assert "spent_inr" in figures(whole)
    assert whole["spend_withheld"] is None
    assert figures(narrowed)["calls"] == "2"
    # Of the two people the campaign reached, one became a lead.
    assert figures(narrowed)["interested_rate_pct"] == "50.0"
    assert "spent_inr" not in figures(narrowed)
    assert narrowed["spend_withheld"] == "narrowed"
    assert figures(inbound)["calls"] == "1"
    assert figures(inbound)["leads"] == "0"


async def test_agents_today_counts_only_todays_real_calls() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    now = datetime.now(UTC)
    start = service.Window(start=service.today_ist(now), end=service.today_ist(now)).start_at
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        form = await _source(session, tenant_id, "website_form")
        lead = await acct.lead(form, arrived=start + timedelta(seconds=1), interested=True)
        await acct.call(lead, at=start + timedelta(seconds=2))
        await acct.call(None, at=start + timedelta(seconds=3), status="no_answer")
        await acct.call(None, at=start + timedelta(seconds=4), test=True)
        await acct.call(None, at=start - timedelta(seconds=1))
        out = await today.agents_today(session, now=max(now, start + timedelta(seconds=5)))

    [row] = out.agents
    assert row.agent_id == acct.agent_id
    assert (row.calls, row.answered) == (2, 1)
    assert row.interested == 1


async def test_the_last_hour_slots_calls_and_counts_live_ones() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    now = datetime.now(UTC).replace(second=30, microsecond=0)
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        await acct.call(None, at=now - timedelta(minutes=2))
        await acct.call(None, at=now - timedelta(minutes=50))
        await acct.call(None, at=now - timedelta(minutes=90))
        await acct.call(None, at=now, status="in_progress")
        out = await today.last_hour(session, agent_id=None, now=now)

    assert len(out.slots) == today.LAST_HOUR_SLOTS
    assert out.calls == 3
    assert out.slots[-1].calls == 2
    assert out.live_now == 1


async def test_quality_weeks_count_verdicts_gaps_and_mistakes_per_ist_week() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    at = _base()
    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        yes = await acct.call(None, at=at, summary_state="ready", goal="yes")
        await acct.call(None, at=at, summary_state="ready", goal="unclear")
        gap = await acct.call(None, at=at, summary_state="ready", goal="no")
        await acct.call(None, at=at, summary_state="pending", goal="yes")
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, tenant_id, agent_id, topic_key, topic_label, "
                "status, occurrence_count, call_count, example_question_redacted, "
                "example_answer_redacted, top_signal, first_seen_at, last_seen_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, 'fees', 'Fees', 'open', 1, 1, 'Fees?', "
                "'not sure', 'dont_know', now(), now(), now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": acct.agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_gap_occurrences (id, tenant_id, agent_id, call_id, "
                "topic_key, topic_label, question_redacted, answer_redacted, signal, hit_count, "
                "created_at, updated_at) VALUES (:id, :t, :a, :c, 'fees', 'Fees', 'Fees?', "
                "'not sure', 'dont_know', 1, now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": acct.agent_id, "c": gap},
        )
        await session.execute(
            text(
                "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                "call_started_at) VALUES (:id, :t, :a, :c, 'said_again', 1, :s)"
            ),
            {"id": uuid7(), "t": tenant_id, "a": acct.agent_id, "c": yes, "s": at},
        )
        out = await today.quality_weeks(session, weeks=2)

    assert len(out.weeks) == 2
    week = next(w for w in out.weeks if w.from_date <= service.today_ist(at) <= w.to_date)
    assert week.calls_read == 3
    assert (week.judged, week.goal_reached) == (2, 1)
    assert week.calls_not_known == 1
    assert week.calls_with_mistakes == 1
    assert [(g.agent_id, g.open_questions) for g in out.gap_agents] == [(acct.agent_id, 1)]


async def test_the_speed_read_is_served_by_indexes() -> None:
    """With sequential scans priced out, no table the read walks per lead is scanned whole:
    the runs by tenant, and the calls, events and holds by lead."""
    tenant_id, _slug, _token = await _make_tenant()
    t0 = _base()
    captured: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, statement: str, params: Any, *_rest: Any) -> None:
        if "FROM follow_up_runs r" in statement:
            captured.append((statement, params))

    async with tenant_session(tenant_id) as session:
        acct = await _Account(session, tenant_id).setup()
        form = await _source(session, tenant_id, "website_form")
        lead = await acct.lead(form, arrived=t0)
        await acct.call(lead, at=t0 + timedelta(seconds=5))
    sync_engine = get_engine().sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        async with tenant_session(tenant_id) as session:
            await speed.speed_to_lead(session, period="90d")
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)

    [(statement, params)] = captured
    async with tenant_session(tenant_id) as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        connection = await session.connection()
        plan = (await connection.exec_driver_sql("EXPLAIN " + statement, params)).all()
    shown = "\n".join(str(row[0]) for row in plan)
    for table in ("follow_up_runs", "calls", "lead_events"):
        assert f"Seq Scan on {table}" not in shown, shown
