"""The statement list, the daily spend series and the team roster (D-660).

What each group pins, in order of what a failure would cost:

1. tenancy (hard rule 1) — another account's statements, spend or colleagues are never in
   the answer;
2. the series sums EXACTLY to the wallet drawdown for the same window, and its days sum
   exactly to its own totals — the property a spend chart is worth nothing without;
3. RBAC matches the neighbouring billing and team routes;
4. money is a decimal string, never a float (hard rule 7).

Run: uv run pytest -q tests/billing_history_test.py
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.ai_quota import OVERAGE_META_KIND
from apps.api.billing.history import spend_series, statement_page, today_ist
from apps.api.billing.service import get_balance
from apps.api.billing.wallet import read_runway
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

SERIES = "/v1/billing/spend/daily"
STATEMENTS = "/v1/billing/statements"
TEAM = "/v1/team/members"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _org() -> dict[str, Any]:
    created = await admin_service.create_organization(
        name="History Clinic",
        slug=f"his-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.test",
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(UUID(str(created["id"]))) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": created["id"]},
        )
    return created


async def _member(org: dict[str, Any], role: str = "owner") -> tuple[dict[str, str], str]:
    user_id = uuid.uuid4()
    email = f"{user_id.hex[:10]}@example.test"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, name, created_at, updated_at) "
                "VALUES (:id, :email, :name, now(), now())"
            ),
            {"id": user_id, "email": email, "name": f"Person {user_id.hex[:4]}"},
        )
    async with tenant_session(UUID(str(org["id"]))) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": org["id"], "uid": user_id, "role": role},
        )
    headers = {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": str(org["slug"])}
    return headers, email


async def _entry(
    tenant_id: UUID,
    *,
    delta: str,
    reason: str,
    hours_ago: float,
    ref: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append a back-dated ledger row, carrying `balance_after` forward (the ledger is
    append-only, hard rule 4, so history is made by appending oldest-first)."""
    async with tenant_session(tenant_id) as session:
        current = (await get_balance(session, tenant_id=tenant_id)).amount_inr
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, meta, created_at) VALUES (gen_random_uuid(), :t, :d, :r, :ref, "
                ":bal, now() - make_interval(secs => :ago), CAST(:meta AS jsonb), now())"
            ),
            {
                "t": tenant_id,
                "d": Decimal(delta),
                "r": reason,
                "ref": ref,
                "bal": current + Decimal(delta),
                "ago": hours_ago * 3600,
                "meta": json.dumps(meta) if meta else None,
            },
        )


async def _call(tenant_id: UUID, agent_id: Any) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    return call_id


async def _history(org: dict[str, Any]) -> UUID:
    """A wallet with a top-up, call debits at sub-paisa precision on three days, a
    dashboard-AI block, a correction — and one debit OUTSIDE a 30-day window."""
    tenant_id = UUID(str(org["id"]))
    # Two calls: `(tenant_id, reason, ref)` is unique on the ledger, one debit per call.
    first_call = await _call(tenant_id, org["agent_id"])
    second_call = await _call(tenant_id, org["agent_id"])
    await _entry(tenant_id, delta="5000", reason="topup", hours_ago=24 * 50)
    await _entry(tenant_id, delta="-77.7700", reason="usage", hours_ago=24 * 45)
    await _entry(tenant_id, delta="-0.3333", reason="usage", hours_ago=24 * 3, ref=str(first_call))
    await _entry(tenant_id, delta="-0.3333", reason="usage", hours_ago=24 * 2, ref=str(second_call))
    await _entry(tenant_id, delta="-0.3333", reason="usage", hours_ago=24 * 1)
    await _entry(
        tenant_id,
        delta="-199",
        reason="usage",
        hours_ago=20,
        ref="ai_assist:2026-10",
        meta={"kind": OVERAGE_META_KIND},
    )
    await _entry(tenant_id, delta="-40", reason="adjustment", hours_ago=10)
    await _entry(tenant_id, delta="250", reason="bonus", hours_ago=5)
    return tenant_id


def _floats(value: Any) -> list[Any]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for v in value.values() for f in _floats(v)]
    if isinstance(value, list):
        return [f for v in value for f in _floats(v)]
    return []


# ----------------------------------------------------------------- the series adds up


async def test_the_series_sums_exactly_to_the_wallet_drawdown_for_the_same_window() -> None:
    org = await _org()
    tenant_id = await _history(org)
    now = datetime.now(UTC)
    today = today_ist(now)

    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        _runway, drawdown = await read_runway(
            session, tenant_id=tenant_id, balance=balance, now=now
        )
        series = await spend_series(
            session, tenant_id=tenant_id, start=today - timedelta(days=29), end=today
        )

    # Every entry inside the trailing window is also inside the 30 IST days, and the 45-day
    # debit is outside both — so the two windows hold the same rows, and the totals are
    # the wallet screen's own, rounded the way it rounds them.
    assert series.spent_inr == Decimal(str(drawdown.spent_inr)).quantize(Decimal("0.01"))
    assert series.spent_inr == Decimal("240.00")  # 0.9999 + 199 + 40, quantized once
    assert series.calls_inr == Decimal("1.00")
    assert series.ai_assist_inr == Decimal("199.00")
    assert series.adjustments_inr == Decimal("40.00")

    # The days partition the totals EXACTLY, sub-paisa debits included.
    assert len(series.days) == 30
    assert sum(d.spent_inr for d in series.days) == series.spent_inr
    assert sum(d.calls_inr for d in series.days) == series.calls_inr
    assert sum(d.ai_assist_inr for d in series.days) == series.ai_assist_inr
    assert sum(d.adjustments_inr for d in series.days) == series.adjustments_inr
    # Empty days are explicit zeros, in calendar order.
    assert [d.day for d in series.days] == [today - timedelta(days=29 - i) for i in range(30)]
    assert sum(1 for d in series.days if d.spent_inr == 0) >= 26

    # The agent split partitions the call debits: two resolve to the agent's call, one
    # names no call.
    assert sum(a.calls_inr for a in series.by_agent) == series.calls_inr
    named = [a for a in series.by_agent if a.agent_id is not None]
    assert [str(a.agent_id) for a in named] == [str(org["agent_id"])]
    assert named[0].agent_name


async def test_the_series_route_answers_strings_and_refuses_a_bad_range() -> None:
    org = await _org()
    await _history(org)
    owner, _ = await _member(org)

    async with _client() as http:
        week = await http.get(SERIES, params={"days": 7}, headers=owner)
        default = await http.get(SERIES, headers=owner)
        mixed = await http.get(
            SERIES, params={"days": 7, "from": "2026-09-01", "to": "2026-09-02"}, headers=owner
        )
        too_long = await http.get(
            SERIES, params={"from": "2026-01-01", "to": "2026-06-30"}, headers=owner
        )
        backwards = await http.get(
            SERIES, params={"from": "2026-09-10", "to": "2026-09-01"}, headers=owner
        )
        odd_length = await http.get(SERIES, params={"days": 12}, headers=owner)
        today = today_ist()
        ranged = await http.get(
            SERIES,
            params={"from": (today - timedelta(days=2)).isoformat(), "to": today.isoformat()},
            headers=owner,
        )
        future = await http.get(
            SERIES,
            params={"from": today.isoformat(), "to": (today + timedelta(days=1)).isoformat()},
            headers=owner,
        )

    assert ranged.status_code == 200, ranged.text
    assert [d["date"] for d in ranged.json()["days"]] == [
        (today - timedelta(days=offset)).isoformat() for offset in (2, 1, 0)
    ]
    assert future.status_code == 422, future.text
    assert future.json()["type"].endswith("/invalid_spend_range")
    assert "future" in future.json()["detail"]
    assert week.status_code == 200, week.text
    body = week.json()
    assert body["basis"] == "wallet_debits"
    assert body["timezone"] == "Asia/Kolkata"
    assert len(body["days"]) == 7
    assert body["days"][-1]["date"] == today_ist().isoformat()
    assert not _floats(body), "money crosses the wire as decimal strings"
    assert Decimal(body["spent_inr"]) == sum(Decimal(d["spent_inr"]) for d in body["days"])
    assert len(default.json()["days"]) == 30
    for refused in (mixed, too_long, backwards, odd_length):
        assert refused.status_code == 422, refused.text


async def test_one_tenant_never_sees_another_tenants_spend() -> None:
    spender = await _org()
    await _history(spender)
    stranger = await _org()
    headers, _ = await _member(stranger)

    async with _client() as http:
        body = (await http.get(SERIES, params={"days": 30}, headers=headers)).json()

    assert body["spent_inr"] == "0.00"
    assert body["by_agent"] == []
    assert all(day["spent_inr"] == "0.00" for day in body["days"])


async def test_a_window_with_credit_but_no_calls_names_no_agent() -> None:
    # The per-agent grouping still yields a row for the top-up (agent NULL, calls zero);
    # an agent list that showed it would list a ₹0 "no agent" spender.
    org = await _org()
    tenant_id = UUID(str(org["id"]))
    await _entry(tenant_id, delta="1000", reason="topup", hours_ago=2)
    await _entry(tenant_id, delta="50", reason="bonus", hours_ago=1)

    today = today_ist()
    async with tenant_session(tenant_id) as session:
        series = await spend_series(
            session, tenant_id=tenant_id, start=today - timedelta(days=6), end=today
        )

    assert series.by_agent == ()
    assert series.spent_inr == Decimal("0")


async def test_staff_cannot_read_the_series_or_the_statements() -> None:
    org = await _org()
    staff, _ = await _member(org, role="staff")
    async with _client() as http:
        assert (await http.get(SERIES, headers=staff)).status_code == 403
        assert (await http.get(STATEMENTS, headers=staff)).status_code == 403


# ----------------------------------------------------------------- the statement list


async def test_each_listed_month_carries_its_own_statements_total() -> None:
    org = await _org()
    await _history(org)
    owner, _ = await _member(org)

    async with _client() as http:
        listed = await http.get(STATEMENTS, headers=owner)
        assert listed.status_code == 200, listed.text
        rows = listed.json()["statements"]
        first = rows[0]
        statement = (
            await http.get("/v1/billing/invoice", params={"month": first["month"]}, headers=owner)
        ).json()

    assert not _floats(listed.json())
    assert first["closed"] is False
    assert first["total_inr"] == statement["total_inr"]
    assert first["invoice_number"] == statement["invoice_number"]
    assert first["document_type"] == "bill_of_supply"
    # The account opened this month, so this month is the only one with a statement.
    assert [row["month"] for row in rows] == [first["month"]]
    assert listed.json()["next_before"] is None


async def test_the_list_pages_back_to_the_month_the_account_opened() -> None:
    org = await _org()
    tenant_id = UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET created_at = now() - interval '100 days' WHERE id = :i"),
            {"i": tenant_id},
        )
    owner, _ = await _member(org)

    async with _client() as http:
        page1 = (await http.get(STATEMENTS, params={"limit": 2}, headers=owner)).json()
        page2 = (
            await http.get(
                STATEMENTS, params={"limit": 12, "before": page1["next_before"]}, headers=owner
            )
        ).json()
        too_many = await http.get(STATEMENTS, params={"limit": 13}, headers=owner)
        bad = await http.get(STATEMENTS, params={"before": "july"}, headers=owner)

    months = [row["month"] for row in page1["statements"] + page2["statements"]]
    assert len(page1["statements"]) == 2
    assert months == sorted(months, reverse=True), "newest first, no month twice"
    assert len(set(months)) == len(months)
    assert page2["next_before"] is None
    assert 4 <= len(months) <= 5  # 100 days spans four or five IST months
    assert too_many.status_code == 422
    assert bad.status_code == 422


async def test_a_page_before_the_opening_month_is_empty_not_an_error() -> None:
    org = await _org()
    owner, _ = await _member(org)

    async with _client() as http:
        opening = (await http.get(STATEMENTS, headers=owner)).json()["statements"][-1]["month"]
        earlier = await http.get(STATEMENTS, params={"before": opening}, headers=owner)

    assert earlier.status_code == 200, earlier.text
    assert earlier.json() == {"statements": [], "next_before": None}


async def test_a_statement_list_for_an_unknown_organization_is_not_found() -> None:
    missing = uuid.uuid4()
    async with tenant_session(missing) as session:
        with pytest.raises(ProblemError) as refused:
            await statement_page(session, tenant_id=missing, limit=6, before=None)
    assert refused.value.kind == "not_found"


async def test_the_list_counts_credit_and_spend_in_the_month_they_landed() -> None:
    org = await _org()
    tenant_id = UUID(str(org["id"]))
    owner, _ = await _member(org)
    await _entry(tenant_id, delta="1000", reason="topup", hours_ago=0.1)
    await _entry(tenant_id, delta="-12.3456", reason="usage", hours_ago=0.05)
    stranger = await _org()
    await _entry(UUID(str(stranger["id"])), delta="9999", reason="topup", hours_ago=0.1)

    async with _client() as http:
        row = (await http.get(STATEMENTS, headers=owner)).json()["statements"][0]

    assert row["credit_added_inr"] == "1000.00"
    assert row["wallet_spent_inr"] == "12.35"


# ----------------------------------------------------------------- the team roster


async def test_owners_see_their_colleagues_addresses_and_nobody_else_s() -> None:
    org = await _org()
    owner, owner_email = await _member(org)
    staff, staff_email = await _member(org, role="staff")
    other = await _org()
    _, outsider_email = await _member(other)

    async with _client() as http:
        roster = await http.get(TEAM, headers=owner)
        as_staff = await http.get(TEAM, headers=staff)

    assert roster.status_code == 200, roster.text
    emails = {member["email"] for member in roster.json()}
    assert {owner_email, staff_email} <= emails
    assert outsider_email not in emails, "hard rule 1: another account's team is invisible"
    assert all(set(m) == {"id", "name", "email", "role", "joined_at"} for m in roster.json())
    # `org:manage`: the people who manage the team, not everyone on it.
    assert as_staff.status_code == 403
