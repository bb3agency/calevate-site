"""The admin Voice response time report (D-770): the voice platform's per-call reply times,
read across every client through `call_reply_scan` and aggregated per call.

Fixtures carry spread on purpose: identical samples make every statistic the same number,
so broken arithmetic would still pass.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.ops.reply_times import (
    MAX_WORST_CALLS,
    P90_MIN_CALLS,
    ClientReplyTimes,
    ReplyTimeReport,
    _Call,
    build_report,
    reply_time_report,
)
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import CallQuality
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant


def _quality(median: int, p90: int, *, first: int = 300, errors: int = 0) -> CallQuality:
    return CallQuality(
        turns=4,
        reply_ms_median=median,
        reply_ms_p90=p90,
        reply_ms_max=p90 + 100,
        first_token_ms_median=first,
        first_token_ms_p90=first + 80,
        first_token_ms_max=first + 120,
        long_silences=1,
        longest_silence_s=11.0,
        interruptions=2,
        model_errors=errors,
        backup_answers=1,
    )


async def _call(
    tenant: Tenant,
    quality: CallQuality | None,
    *,
    tier: str | None = None,
    slow_reply: bool = False,
    started: datetime | None = None,
) -> uuid.UUID:
    """One completed call written by the production upsert, with its signals and metering."""
    from apps.workers.pipeline import _upsert_call_row

    engine_call_id = f"rt-{uuid.uuid4().hex}"
    snapshot = ExecutionSnapshot(
        engine_call_id=engine_call_id,
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        engine="fake",
        started_at=started or datetime.now(UTC) - timedelta(minutes=5),
        ended_at=datetime.now(UTC),
        quality=quality,
    )
    call_id = await _upsert_call_row(tenant.tenant_id, tenant.agent_id, snapshot, None)
    async with tenant_session(tenant.tenant_id) as session:
        if slow_reply:
            await session.execute(
                text(
                    "INSERT INTO call_engine_signals (id, tenant_id, agent_id, engine_call_id, "
                    "kind, occurred_at) VALUES (:id, :tid, :aid, :ecid, 'slow_reply', now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant.tenant_id,
                    "aid": tenant.agent_id,
                    "ecid": engine_call_id,
                },
            )
        if tier is not None:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, meta, occurred_at, created_at) VALUES (:id, :tid, :cid, "
                    "'platform_min', 1, :cost, CAST(:meta AS jsonb), now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant.tenant_id,
                    "cid": call_id,
                    "cost": Decimal("2.5000"),
                    "meta": json.dumps({"voice_tier": tier}),
                },
            )
    return call_id


async def _report(days: int = 1) -> ReplyTimeReport:
    async with admin_session() as session:
        return await reply_time_report(session, days=days)


def _client(report: ReplyTimeReport, tenant: Tenant) -> ClientReplyTimes:
    return next(row for row in report.by_client if row.tenant_id == tenant.tenant_id)


async def test_every_client_is_read_under_its_own_policy_and_figures_are_per_call() -> None:
    """Two clients, each reported with only its own calls — the scan enters every tenant."""
    a, b = await _tenant(), await _tenant()
    medians = [600, 700, 800, 900, 1000]
    for m in medians:
        await _call(a, _quality(m, m + 400, first=m // 2), tier="clear")
    await _call(b, _quality(2000, 3000), tier="studio", slow_reply=True)

    report = await _report()
    ra, rb = _client(report, a), _client(report, b)

    assert (ra.calls, ra.calls_measured, rb.calls) == (5, 5, 1)
    # Median of per-call medians; the p90 of per-call p90s is withheld below ten calls.
    assert ra.reply_typical_ms == 800.0
    assert ra.reply_slow_ms is None
    assert ra.reply_worst_ms == 1500.0
    assert ra.first_token_typical_ms == 400.0
    assert ra.turns == 20 and ra.model_errors == 0 and ra.rescues == 5
    assert ra.interruptions == 10 and ra.long_silences == 5
    assert rb.slow_reply_problems == 1 and ra.slow_reply_problems == 0
    assert ra.client_slug == a.slug


async def test_a_call_is_over_target_when_its_p90_reply_exceeds_the_slow_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await _tenant()
    await _call(tenant, _quality(400, 450))
    await _call(tenant, _quality(400, 900))
    monkeypatch.setattr(get_settings(), "reply_time_typical_target_ms", 300)
    monkeypatch.setattr(get_settings(), "reply_time_slow_target_ms", 500)

    report = await _report()

    assert (report.typical_target_ms, report.slow_target_ms) == (300, 500)
    assert _client(report, tenant).calls_over_target == 1


def test_the_targets_default_to_the_founders_typical_and_slow_figures() -> None:
    """D-896: 1.6 s typical, 2.2 s slow, replacing the unreachable 500 ms."""
    from calevate_shared.config import Settings

    fields = Settings.model_fields
    assert fields["reply_time_typical_target_ms"].default == 1600
    assert fields["reply_time_slow_target_ms"].default == 2200
    assert "reply_time_target_ms" not in fields


async def test_each_call_is_split_by_the_settings_its_agent_was_published_with() -> None:
    """The agent's stamp is copied onto the call when its row is first written and is never
    overwritten; the report splits by it, and an unstamped call reads `not_recorded`."""
    tenant = await _tenant()
    await _call(tenant, _quality(900, 1200))  # before any stamp
    stamp = {
        "turn_detection": "ear",
        "turn_silence_ms": 250,
        "early_answers": True,
        "filler_delay_ms": 2000,
        "known_facts": True,
        "known_facts_chars": 2500,
    }
    async with tenant_session(tenant.tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET voice_settings = CAST(:s AS jsonb) WHERE id = :aid"),
            {"s": json.dumps(stamp), "aid": tenant.agent_id},
        )
    stamped = await _call(tenant, _quality(1500, 1800))
    async with tenant_session(tenant.tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET voice_settings = NULL WHERE id = :aid"),
            {"aid": tenant.agent_id},
        )
        held = (
            await session.execute(
                text("SELECT voice_settings FROM calls WHERE id = :cid"), {"cid": stamped}
            )
        ).scalar_one()
    assert held == stamp

    report = await _report()
    rows = {(r.setting, r.value): r for r in report.by_setting}
    assert rows[("turn_detection", "ear")].calls >= 1
    assert rows[("known_facts", "on")].reply_typical_ms is not None
    assert ("known_facts_size", "2000_to_4000") in rows
    assert ("filler_delay_ms", "2000") in rows
    assert rows[("turn_detection", "not_recorded")].calls >= 1


def test_setting_values_are_closed_set_strings() -> None:
    from apps.api.ops.reply_times import setting_value

    call = _fake(1, reply_p90=900.0)
    assert setting_value(call, "turn_detection") == "not_recorded"
    stamped = replace(call, voice_settings={"known_facts": False, "known_facts_chars": 0})
    assert setting_value(stamped, "known_facts") == "off"
    assert setting_value(stamped, "known_facts_size") == "none"
    assert setting_value(stamped, "early_answers") == "not_recorded"
    big = replace(call, voice_settings={"known_facts_chars": 5000})
    assert setting_value(big, "known_facts_size") == "4000_plus"


async def test_tier_agent_and_worst_calls_carry_the_client_and_the_call() -> None:
    tenant = await _tenant()
    slow = await _call(tenant, _quality(5000, 9000, errors=2), tier="studio")
    await _call(tenant, _quality(500, 700), tier="clear")
    await _call(tenant, None)

    report = await _report()

    agent = next(row for row in report.by_agent if row.agent_id == tenant.agent_id)
    assert (agent.calls, agent.calls_measured, agent.agent_name) == (3, 2, "Sales")
    assert {row.tier for row in report.by_tier} >= {"clear", "studio", "not_metered"}
    worst = next(row for row in report.worst_calls if row.call_id == slow)
    assert worst.tenant_id == tenant.tenant_id and worst.client_slug == tenant.slug
    assert worst.voice_tier == "studio" and worst.model_errors == 2
    assert worst.reply_p90_ms == 9000.0


async def test_calls_outside_the_window_are_not_read() -> None:
    tenant = await _tenant()
    await _call(tenant, _quality(500, 700), started=datetime.now(UTC) - timedelta(days=3))

    report = await _report(days=1)

    assert all(row.tenant_id != tenant.tenant_id for row in report.by_client)


async def test_the_scan_is_bounded_by_rls_outside_an_admin_session() -> None:
    """Called from a tenant's own session the loop cannot enumerate other clients."""
    a, b = await _tenant(), await _tenant()
    await _call(a, _quality(500, 700))
    await _call(b, _quality(500, 700))

    async with tenant_session(a.tenant_id) as session:
        tenants = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT DISTINCT scanned_tenant_id FROM call_reply_scan(:since)"),
                    {"since": datetime.now(UTC) - timedelta(days=1)},
                )
            ).all()
        }
    assert tenants == {a.tenant_id}


# ------------------------------------------------------------- pure aggregation rules


def _fake(n: int, *, reply_p90: float | None, day_offset: int = 0) -> _Call:
    tenant = uuid.UUID(int=1)
    return _Call(
        tenant_id=tenant,
        client_name="Client",
        client_slug="client",
        call_id=uuid.UUID(int=1000 + n),
        agent_id=uuid.UUID(int=2),
        agent_name="Agent",
        started_at=datetime(2026, 10, 14, 20, 0, tzinfo=UTC) - timedelta(days=day_offset),
        slow_reply=False,
        voice_tier="clear",
        turns=3,
        reply_median=None if reply_p90 is None else reply_p90 / 2,
        reply_p90=reply_p90,
        reply_max=None if reply_p90 is None else reply_p90 + 1,
        first_median=None,
        first_p90=None,
        long_silences=None,
        interruptions=None,
        model_errors=None,
        rescues=None,
    )


def test_the_slow_figure_appears_at_ten_measured_calls_and_interpolates() -> None:
    nine = [_fake(i, reply_p90=float(100 * (i + 1))) for i in range(P90_MIN_CALLS - 1)]
    assert (
        build_report(
            nine, days=1, typical_target_ms=400, slow_target_ms=500, complete=True
        ).overall.reply_slow_ms
        is None
    )

    ten = [*nine, _fake(99, reply_p90=1000.0)]
    report = build_report(ten, days=1, typical_target_ms=400, slow_target_ms=500, complete=True)
    # p90 over 100..1000 by percentile_cont: position 8.1 -> 900 + 0.1 * 100.
    assert report.overall.reply_slow_ms == pytest.approx(910.0)
    assert report.overall.calls_over_target == 5


def test_an_empty_window_says_whether_there_were_calls() -> None:
    none = build_report([], days=7, typical_target_ms=400, slow_target_ms=500, complete=True)
    assert none.empty_reason == "no_calls"

    unmeasured = build_report(
        [_fake(1, reply_p90=None)], days=7, typical_target_ms=400, slow_target_ms=500, complete=True
    )
    assert unmeasured.empty_reason == "not_reported"
    assert unmeasured.overall.calls == 1 and unmeasured.overall.calls_measured == 0
    assert unmeasured.worst_calls == []


def test_days_are_ist_calendar_days_and_worst_calls_are_capped() -> None:
    # 20:00 UTC on 14 Oct is 01:30 IST on 15 Oct (D-709).
    calls = [_fake(i, reply_p90=float(i + 1)) for i in range(MAX_WORST_CALLS + 5)]
    report = build_report(calls, days=1, typical_target_ms=400, slow_target_ms=500, complete=True)

    assert [row.day.isoformat() for row in report.by_day] == ["2026-10-15"]
    assert len(report.worst_calls) == MAX_WORST_CALLS
    assert report.worst_calls[0].reply_p90_ms == float(MAX_WORST_CALLS + 5)
