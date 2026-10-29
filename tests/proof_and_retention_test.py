"""D-944: weekly reply speed, rupees per result and the owner's daily summary.

Fixture instants are IST wall clock stored as the UTC instant, so a test that bucketed by
the UTC date would put a late-Sunday call in the wrong week.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.analytics import proof
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from apps.api.notifications import daily_summary
from apps.api.notifications.daily_summary import DailySummary, HotLead
from apps.workers import owner_digest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api_security_test import _make_tenant

_IST = timedelta(hours=5, minutes=30)


def _ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC) - _IST


def _today_ist() -> date:
    return (datetime.now(UTC) + _IST).date()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _speed(
    at: datetime,
    *,
    language: str = "te-IN",
    status: str = "completed",
    duration_s: int | None = 60,
    median: float | None = 1000.0,
    p90: float | None = 1500.0,
) -> proof.SpeedCall:
    return proof.SpeedCall(
        started_at=at,
        language=language,
        status=status,
        duration_s=duration_s,
        answer_median=median,
        answer_p90=p90,
    )


# --- the roll-up, pure ------------------------------------------------------------------


def test_weeks_are_ist_monday_to_sunday() -> None:
    monday = date(2026, 10, 26)
    late_sunday = _ist(monday - timedelta(days=1), 23, 50)  # 18:20 UTC Sunday
    early_monday = _ist(monday, 0, 10)  # 18:40 UTC Sunday: the UTC date says Sunday
    weeks = proof.week_starts(date(2026, 10, 30), 2)
    assert weeks == [date(2026, 10, 19), date(2026, 10, 26)]
    rows = proof.rollup([_speed(late_sunday), _speed(early_monday)], weeks)
    totals = {r.week_start: r for r in rows if r.language == proof.ALL_LANGUAGES}
    assert totals[date(2026, 10, 19)].calls == 1
    assert totals[date(2026, 10, 26)].calls == 1


def test_typical_is_the_median_of_call_medians_and_slow_needs_ten_calls() -> None:
    at = _ist(date(2026, 10, 27), 11)
    nine = [_speed(at, median=float(m), p90=float(m) * 2) for m in range(100, 1000, 100)]
    week = [date(2026, 10, 26)]
    row = proof.rollup(nine, week)[0]
    assert row.calls_measured == 9
    assert row.reply_typical_ms == 500.0
    assert row.reply_slow_ms is None
    ten = [*nine, _speed(at, median=1000.0, p90=2000.0)]
    row = proof.rollup(ten, week)[0]
    # p90 of 200..2000 step 200, linear interpolation: 1820.
    assert row.reply_slow_ms == pytest.approx(1820.0)


def test_an_unmeasured_call_is_not_a_zero_and_answered_share_uses_every_call() -> None:
    at = _ist(date(2026, 10, 27), 11)
    calls = [
        _speed(at, median=None, p90=None, duration_s=30),
        _speed(at, median=2000.0, p90=3000.0, duration_s=90),
        _speed(at, status="no_answer", duration_s=0, median=None, p90=None),
        _speed(at, status="busy", duration_s=None, median=None, p90=None, language="hi-IN"),
    ]
    rows = proof.rollup(calls, [date(2026, 10, 26)])
    total = rows[0]
    assert total.language == proof.ALL_LANGUAGES
    assert (total.calls, total.answered, total.calls_measured) == (4, 2, 1)
    assert total.answered_share == 0.5
    assert total.average_call_s == 60.0
    assert total.reply_typical_ms == 2000.0
    by_language = {r.language: r for r in rows[1:]}
    assert by_language["te-IN"].calls == 3
    assert by_language["hi-IN"].answered == 0


def test_an_empty_week_is_zero_filled_with_null_rates() -> None:
    row = proof.rollup([], [date(2026, 10, 26)])
    assert len(row) == 1
    assert row[0].calls == 0 and row[0].answered_share is None and row[0].reply_typical_ms is None


def test_language_keys_are_bcp47_or_unknown() -> None:
    assert proof.language_key("te-IN") == "te-IN"
    assert proof.language_key(None) == proof.UNKNOWN_LANGUAGE
    assert proof.language_key("xx-ZZ") == proof.UNKNOWN_LANGUAGE


# --- money, pure ------------------------------------------------------------------------


def test_rupees_per_result_are_decimal_paise_and_null_with_nothing_to_divide() -> None:
    value = proof.per_unit(Decimal("100.00"), 3)
    assert isinstance(value, Decimal)
    assert value == Decimal("33.33")
    assert proof.per_unit(Decimal("100.00"), 0) is None


def test_a_booking_is_a_hot_outcome_or_the_starting_buying_outcome() -> None:
    assert proof.is_booking(None, proof.BUYING_OUTCOME_KEY)
    assert not proof.is_booking(None, "asked_for_information")
    own = [{"key": "pickup_booked", "label": "Pickup booked", "meaning": "x", "lead_status": "hot"}]
    assert proof.is_booking(own, "pickup_booked")
    assert not proof.is_booking(own, None)


# --- the summary's content, pure ---------------------------------------------------------


def _summary(**overrides: Any) -> DailySummary:
    base: dict[str, Any] = {
        "day": date(2026, 10, 30),
        "business_name": "Ravi Dental",
        "slug": "ravi-dental",
        "answered": 12,
        "missed": 2,
        "leads": 4,
        "hot_leads": 2,
        "top_hot": (
            HotLead(name="Sita Rao", phone_masked="[phone ••21]"),
            HotLead(name=None, phone_masked="[phone ••09]"),
        ),
        "spent_inr": Decimal("123.40"),
        "per_lead_inr": Decimal("30.85"),
        "follow_ups_waiting": 3,
    }
    return DailySummary(**(base | overrides))


def test_the_email_names_hot_leads_with_masked_numbers_and_one_button() -> None:
    email = owner_digest.compose_email(_summary())
    assert "Sita Rao ([phone ••21])" in email.text
    assert "Name not captured ([phone ••09])" in email.text
    assert "https://app." in email.text and "/c/ravi-dental" in email.text
    assert email.html is not None and email.html.count("Open your dashboard") >= 1
    assert "₹123.4" in email.text


def test_the_whatsapp_template_carries_counts_and_rupees_only() -> None:
    variables = daily_summary.whatsapp_variables(_summary())
    assert variables == ("Ravi Dental", "12", "2", "4", "2", "₹123.4", "3")
    joined = " ".join(variables)
    assert "Sita" not in joined and "phone" not in joined


def test_a_hot_lead_number_is_masked_by_the_redactor() -> None:
    from apps.workers.redaction import redact

    assert redact("+919876543221").text == "[phone ••21]"


# --- against the database ----------------------------------------------------------------


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
    language: str | None = "te-IN",
    quality: dict[str, float] | None = None,
    outcome: str | None = None,
    direction: str = "inbound",
    trial: bool = False,
) -> None:
    await session.execute(
        text(
            "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
            "started_at, duration_s, summary_language, engine_quality, business_outcome, "
            "business_outcome_label, trial_call, created_at, updated_at) VALUES (:id, :tid, "
            ":aid, :ecid, :dir, :status, :at, :dur, :lang, CAST(:q AS jsonb), :outcome, "
            ":outcome, :trial, :at, now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "ecid": f"pr-{uuid.uuid4().hex}",
            "dir": direction,
            "status": status,
            "at": at,
            "dur": duration_s,
            "lang": language,
            "q": json.dumps(quality) if quality is not None else None,
            "outcome": outcome,
            "trial": trial,
        },
    )


async def _lead(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    at: datetime,
    status: str = "new",
    name: str | None = None,
    phone: str = "+919876543210",
) -> None:
    await session.execute(
        text(
            "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
            "status_set_at, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, :name, "
            "'inbound_call', :status, :at, :at, now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "aid": agent_id,
            "phone": phone,
            "name": name,
            "status": status,
            "at": at,
        },
    )


async def _debit(session: AsyncSession, tenant_id: uuid.UUID, amount: str, at: datetime) -> None:
    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, created_at) VALUES (gen_random_uuid(), :t, :d, 'usage', NULL, 0, "
            ":at, now())"
        ),
        {"t": tenant_id, "d": -Decimal(amount), "at": at},
    )


async def test_the_client_sees_its_own_weekly_reply_speed_without_test_calls() -> None:
    tenant_id, _slug, token = await _make_tenant()
    today = _today_ist()
    at = _ist(today, 0, 5)
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        q = {"answer_ms_median": 1200.0, "answer_ms_p90": 1800.0}
        await _call(session, tenant_id, agent_id, at=at, quality=q)
        await _call(session, tenant_id, agent_id, at=at, language="hi-IN", quality=q)
        await _call(session, tenant_id, agent_id, at=at, quality=q, trial=True)
    async with _client() as client:
        response = await client.get(
            "/v1/analytics/reply-speed?weeks=2", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    current = [w for w in body["weeks"] if w["week_start"] == proof.week_start(today).isoformat()]
    total = next(w for w in current if w["language"] == "all")
    assert total["calls"] == 2
    assert total["reply_typical_ms"] == 1200.0
    assert {w["language"] for w in current} == {"all", "te-IN", "hi-IN"}
    assert body["current_week_partial"] is (today.weekday() != 6)


async def test_cost_per_result_divides_wallet_spend_by_each_result() -> None:
    tenant_id, _slug, token = await _make_tenant()
    yesterday = _today_ist() - timedelta(days=1)
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(session, tenant_id, agent_id, at=_ist(yesterday, 10), outcome="wants_to_buy")
        await _call(session, tenant_id, agent_id, at=_ist(yesterday, 11), outcome="interested")
        await _call(
            session, tenant_id, agent_id, at=_ist(yesterday, 12), status="no_answer", duration_s=0
        )
        await _lead(session, tenant_id, agent_id, at=_ist(yesterday, 10))
        await _debit(session, tenant_id, "10.00", _ist(yesterday, 10, 30))
    async with _client() as client:
        response = await client.get(
            "/v1/analytics/cost-per-result", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["billing_step_seconds"] == 30
    week = next(w for w in body["windows"] if w["days"] == 7)
    # Two leads: the fixture's own (created now) and the one above.
    assert (week["answered_calls"], week["leads_captured"], week["booked_results"]) == (2, 2, 1)
    # Money crosses the wire as a decimal string, never a float.
    assert week["spent_inr"] == "10.00"
    assert week["per_answered_call_inr"] == "5.00"
    assert week["per_lead_inr"] == "5.00"
    assert week["per_booked_result_inr"] == "10.00"


async def test_the_fleet_view_groups_every_client_by_language() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(
            session,
            tenant_id,
            agent_id,
            at=_ist(today, 0, 1),
            language="en-IN",
            quality={"answer_ms_median": 900.0, "answer_ms_p90": 1100.0},
        )
    async with admin_session() as session:
        out = await proof.fleet_reply_speed(session, weeks=1)
    assert out.public_page_enabled is False
    assert out.clients >= 1
    assert any(w.language == "en-IN" and w.calls >= 1 for w in out.weeks)


async def test_the_daily_summary_is_off_until_the_owner_turns_it_on() -> None:
    tenant_id, _slug, token = await _make_tenant()
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as client:
        first = await client.get("/v1/notifications/daily-summary", headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["enabled"] is False
        turned = await client.put(
            "/v1/notifications/daily-summary", headers=headers, json={"enabled": True}
        )
    assert turned.status_code == 200, turned.text
    assert turned.json()["enabled"] is True
    async with tenant_session(tenant_id) as session:
        assert await daily_summary.read_switch(session) is True
        audited = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a"),
                {"a": "organization.daily_summary_set"},
            )
        ).scalar_one()
    assert audited >= 1


async def test_staff_cannot_turn_the_daily_summary_on() -> None:
    _tenant_id, _slug, token = await _make_tenant(role="staff")
    async with _client() as client:
        response = await client.put(
            "/v1/notifications/daily-summary",
            headers={"Authorization": f"Bearer {token}"},
            json={"enabled": True},
        )
    assert response.status_code == 403


class _Sent:
    def __init__(self) -> None:
        self.mails: list[dict[str, Any]] = []

    def send(self, **kwargs: Any) -> bool:
        self.mails.append(kwargs)
        return True


async def test_one_summary_per_ist_day_with_masked_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await session.execute(
            text("UPDATE organizations SET owner_digest_enabled = true, billing_email = :e"),
            {"e": f"{tenant_id.hex[:8]}@example.com"},
        )
        await _call(session, tenant_id, agent_id, at=_ist(today, 0, 2))
        await _lead(
            session,
            tenant_id,
            agent_id,
            at=_ist(today, 0, 3),
            status="hot",
            name="Sita Rao",
            phone="+919876543221",
        )
    sent = _Sent()
    monkeypatch.setattr(owner_digest, "get_transport", lambda _purpose: sent)
    assert await owner_digest.send_one(tenant_id, day=today) == "sent"
    first_run = len(sent.mails)  # the billing address and the owner
    assert first_run == 2
    assert await owner_digest.send_one(tenant_id, day=today) == "not_claimed"
    assert len(sent.mails) == first_run
    for mail in sent.mails:
        assert "Sita Rao ([phone ••21])" in mail["body"]
        assert "9876543221" not in mail["body"] and "9876543221" not in (mail["html"] or "")


async def test_a_quiet_day_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE organizations SET owner_digest_enabled = true"))
    sent = _Sent()
    monkeypatch.setattr(owner_digest, "get_transport", lambda _purpose: sent)
    # Two days ago: the fixture's own lead was created today.
    quiet_day = _today_ist() - timedelta(days=2)
    assert await owner_digest.send_one(tenant_id, day=quiet_day) == "quiet"
    assert sent.mails == []


async def test_an_account_that_did_not_opt_in_is_never_claimed() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    assert await owner_digest.send_one(tenant_id, day=_today_ist()) == "not_claimed"
    async with tenant_session(tenant_id) as session:
        stamped = (
            await session.execute(text("SELECT owner_digest_sent_on FROM organizations"))
        ).scalar()
    assert stamped is None


async def test_the_public_rate_card_names_the_number_fee_field() -> None:
    async with _client() as client:
        response = await client.get("/v1/public/rate-card")
    assert response.status_code == 200, response.text
    assert "number_inr_per_month" in response.json()
