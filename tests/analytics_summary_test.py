"""`/v1/analytics/summary` and `/v1/analytics/call-groups` (D-893 L7), and Pip's
`business_snapshot` answers built on them.

Fixture instants are IST wall clock stored as UTC, as in `analytics_test.py`, so a bucket
taken by the UTC date would land a late-evening call on the wrong day.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.api.analytics import service
from apps.api.copilot import tools
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.analytics_test import _agent, _call, _client, _ist, _today_ist
from tests.api_security_test import _make_tenant


def test_buckets_are_monday_weeks_and_calendar_months_cut_to_the_range() -> None:
    window = service.Window(start=date(2026, 9, 24), end=date(2026, 10, 7))
    weeks = service.summary_buckets(window, "week")
    assert weeks == [
        (date(2026, 9, 24), date(2026, 9, 27)),
        (date(2026, 9, 28), date(2026, 10, 4)),
        (date(2026, 10, 5), date(2026, 10, 7)),
    ]
    assert service.summary_buckets(window, "month") == [
        (date(2026, 9, 24), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 10, 7)),
    ]
    assert len(service.summary_buckets(window, "day")) == 14


async def _debit(
    session: AsyncSession, tenant_id: uuid.UUID, amount: str, at: datetime, balance: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, created_at) VALUES (gen_random_uuid(), :t, :d, 'usage', NULL, :b, "
            ":at, now())"
        ),
        {"t": tenant_id, "d": -Decimal(amount), "b": Decimal(balance), "at": at},
    )


async def test_summary_sums_days_into_weeks_with_exact_spend() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(session, tenant_id, agent_id, at=_ist(today, 23, 30))
        await _call(session, tenant_id, agent_id, at=_ist(today, 9), status="failed", duration_s=0)
        await _debit(session, tenant_id, "10.25", _ist(today, 23, 40), "89.75")
        await _debit(session, tenant_id, "0.50", _ist(today, 10), "89.25")
        window = service.resolve_window(days=14, to=None)
        out = await service.summary(
            session,
            tenant_id=tenant_id,
            window=window,
            bucket="week",
            agent_id=None,
            test_calls=True,
            may_see_spend=True,
        )
        hidden = await service.summary(
            session,
            tenant_id=tenant_id,
            window=window,
            bucket="day",
            agent_id=None,
            test_calls=True,
            may_see_spend=False,
        )
        one_agent = await service.summary(
            session,
            tenant_id=tenant_id,
            window=window,
            bucket="month",
            agent_id=agent_id,
            test_calls=True,
            may_see_spend=True,
        )

    assert out.calls == 2 and out.answered == 1
    assert out.spent_inr == "10.75"
    assert sum(Decimal(row.spent_inr or "0") for row in out.rows) == Decimal("10.75")
    last = out.rows[-1]
    assert last.to_date == today and last.calls == 2 and last.spent_inr == "10.75"
    assert out.rows[0].from_date == window.start
    assert out.spend_withheld is None
    assert hidden.spend_withheld == "no_billing_access" and hidden.spent_inr is None
    assert len(hidden.rows) == 14 and all(row.spent_inr is None for row in hidden.rows)
    assert one_agent.spend_withheld == "one_agent" and one_agent.calls == 2


async def _lead(
    session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, name: str
) -> uuid.UUID:
    lead_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, :phone, :name, 'inbound_call', "
            "'new', now(), now())"
        ),
        {
            "id": lead_id,
            "tid": tenant_id,
            "aid": agent_id,
            "phone": f"+9198{uuid.uuid4().int % 100000000:08d}",
            "name": name,
        },
    )
    return lead_id


async def _caller_call(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    at: datetime,
    lead_id: uuid.UUID | None = None,
    number: str | None = None,
    outcome: str | None = None,
    test: bool = False,
) -> None:
    call_id = await _call(session, tenant_id, agent_id, at=at, outcome=outcome)
    await session.execute(
        text(
            "UPDATE calls SET lead_id = :lead, from_e164 = :num, paid_test_call = :test "
            "WHERE id = :id"
        ),
        {"lead": lead_id, "num": number, "test": test, "id": call_id},
    )


async def _seed_callers(tenant_id: uuid.UUID) -> uuid.UUID:
    today = _today_ist()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        ravi = await _lead(session, tenant_id, agent_id, "Ravi")
        once = await _lead(session, tenant_id, agent_id, "Sita")
        for hour, outcome in ((9, "needs_you"), (11, "call_back_booked"), (15, "call_back_booked")):
            await _caller_call(
                session, tenant_id, agent_id, at=_ist(today, hour), lead_id=ravi, outcome=outcome
            )
        await _caller_call(session, tenant_id, agent_id, at=_ist(today, 10), lead_id=once)
        for hour in (12, 13):
            await _caller_call(
                session, tenant_id, agent_id, at=_ist(today, hour), number="+919811122233"
            )
        # The owner ringing their own agent twice is not a repeat caller.
        for hour in (16, 17):
            await _caller_call(
                session,
                tenant_id,
                agent_id,
                at=_ist(today, hour),
                number="+919800000001",
                test=True,
            )
    return agent_id


async def test_repeat_callers_are_counted_over_every_call_without_numbers() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed_callers(tenant_id)
    window = service.resolve_window(days=7, to=None)
    async with tenant_session(tenant_id) as session:
        out = await service.call_groups(
            session, window=window, by="caller", agent_id=None, test_calls=False, min_calls=2
        )
        outcomes = await service.call_groups(
            session, window=window, by="outcome", agent_id=None, test_calls=False
        )
        with_tests = await service.call_groups(
            session, window=window, by="caller", agent_id=None, test_calls=True, min_calls=2
        )

    assert out.calls == 6
    assert out.repeat_groups == 2 and out.groups_total == 2
    first, second = out.groups
    assert (first.label, first.calls, first.latest_outcome) == ("Ravi", 3, "call_back_booked")
    assert second.label is None and second.key == "number" and second.number_tail == "33"
    assert "+919811122233" not in out.model_dump_json()
    assert {g.key: g.calls for g in outcomes.groups} == {
        "call_back_booked": 2,
        "needs_you": 1,
        "": 3,
    }
    assert with_tests.repeat_groups == 3


async def test_a_limit_pages_the_rows_but_never_the_counts() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed_callers(tenant_id)
    async with tenant_session(tenant_id) as session:
        out = await service.call_groups(
            session,
            window=service.resolve_window(days=7, to=None),
            by="caller",
            agent_id=None,
            test_calls=False,
            limit=1,
        )
    assert len(out.groups) == 1
    assert out.groups_total == 3 and out.repeat_groups == 2 and out.calls == 6


async def test_pip_answers_repeat_callers_from_the_aggregate() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    await _seed_callers(tenant_id)
    context = tools.ToolContext(tenant_id=tenant_id, role="owner")
    grouped = await tools.run_read_tool(
        "business_snapshot", json.dumps({"days": 7, "by": "caller"}), context=context
    )
    weekly = await tools.run_read_tool(
        "business_snapshot", json.dumps({"days": 14, "by": "week"}), context=context
    )
    staff = await tools.run_read_tool(
        "business_snapshot",
        json.dumps({"days": 14, "by": "week"}),
        context=tools.ToolContext(tenant_id=tenant_id, role="staff"),
    )

    assert "6 calls; 2 caller(s) called 2 or more times" in grouped
    assert "Ravi: 3 calls" in grouped and "number ending 33" in grouped
    assert "9811122233" not in grouped
    assert "by week, test calls left out: 6 calls" in weekly and "spent" in weekly
    assert "may not see billing" in staff and "spent" not in staff.split("\n")[1]


async def test_nobody_called_twice_is_said_in_words() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = await _agent(session)
        await _call(session, tenant_id, agent_id, at=_ist(_today_ist(), 10))
    answer = await tools.run_read_tool(
        "business_snapshot",
        json.dumps({"days": 7, "by": "caller"}),
        context=tools.ToolContext(tenant_id=tenant_id, role="owner"),
    )
    assert "1 calls; 0 caller(s) called 2 or more times. Nobody called twice." in answer


async def test_the_routes_withhold_spend_from_a_role_without_billing() -> None:
    tenant_id, slug, owner_token = await _make_tenant(role="owner")
    _staff_tenant, staff_slug, staff_token = await _make_tenant(role="staff")
    await _seed_callers(tenant_id)
    async with _client() as http:
        owner = await http.get(
            "/v1/analytics/summary?days=7&bucket=day",
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        staff = await http.get(
            "/v1/analytics/summary?days=7",
            headers={"Authorization": f"Bearer {staff_token}", "X-Org-Slug": staff_slug},
        )
        groups = await http.get(
            "/v1/analytics/call-groups?by=caller&min_calls=2&days=7",
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        bad = await http.get(
            "/v1/analytics/summary?bucket=year",
            headers={"Authorization": f"Bearer {owner_token}", "X-Org-Slug": slug},
        )
        anonymous = await http.get("/v1/analytics/call-groups")

    assert owner.status_code == 200, owner.text
    assert owner.json()["spend_withheld"] is None and len(owner.json()["rows"]) == 7
    assert staff.status_code == 200, staff.text
    assert staff.json()["spend_withheld"] == "no_billing_access"
    assert staff.json()["calls"] == 0  # another tenant's calls never reach it
    assert groups.json()["repeat_groups"] == 2
    assert bad.status_code == 422
    assert anonymous.status_code == 401


def test_window_days_are_ist_dates() -> None:
    today = _today_ist()
    window = service.resolve_window(days=7, to=None)
    assert window.end == today and window.start == today - timedelta(days=6)
