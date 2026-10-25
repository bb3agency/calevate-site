"""A free trial is an acquisition cost, not a calling loss, and it spends nothing of the
client's — on the admin Spend page, the fleet board, the cap counter and the cap route.

Also: a cost priced at an operator-attested INR rate is not "scaled by an assumption".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import spend_routes
from apps.api.billing.attribution import month_trial_cost_inr, period_attribution
from apps.api.billing.service import current_billing_month
from apps.api.billing.trials import start_trial
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_attribution_test import (
    _client,
    _make_admin,
    _make_member,
    _metered_call,
)
from tests.spend_attribution_test import _tenant as _spend_tenant
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state
from tests.spend_caps_test import _tenant as _cap_tenant


async def _open_trial(tenant_id: UUID, *, started: datetime) -> None:
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None, at=started)


async def _admin_spend(tenant_id: UUID) -> dict[str, object]:
    token = await _make_admin()
    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/spend", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


# ------------------------------------------------------------------ the admin Spend page


async def test_a_trial_month_is_trial_cost_not_a_negative_margin() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    await _open_trial(tenant_id, started=datetime.now(UTC) - timedelta(minutes=1))
    await _metered_call(tenant_id, agent_id, seconds=600, unit_cost="0.0230")

    body = await _admin_spend(tenant_id)

    assert body["revenue_inr"] == "0.00"
    assert body["cost_inr"] == "13.80"
    assert body["trial_cost_inr"] == "13.80"
    assert body["trial_calls"] == 1
    assert body["trial_in_month"] is True
    assert body["paid_cost_inr"] == "0.00"
    assert body["paid_margin_inr"] == "0.00", "a free trial must not read as losing money"
    assert body["paid_margin_pct"] is None
    # D-12's all-in margin is unchanged; the screen leads with the paid one.
    assert body["margin_inr"] == "-13.80"
    calls = body["top_calls"]
    assert isinstance(calls, list) and calls[0]["trial_covered"] is True
    agents = body["by_agent"]
    assert isinstance(agents, list)
    assert agents[0]["trial_cost_inr"] == "13.80"
    assert agents[0]["paid_margin_inr"] == "0.00"


async def test_a_month_mixing_trial_and_paid_calls_splits_the_cost() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    now = datetime.now(UTC)
    paid_call = await _metered_call(
        tenant_id, agent_id, seconds=60, unit_cost="0.1000", at=now - timedelta(minutes=3)
    )
    await _open_trial(tenant_id, started=now - timedelta(minutes=2))
    trial_call = await _metered_call(tenant_id, agent_id, seconds=120, unit_cost="0.1000")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)
        fleet_figure = await month_trial_cost_inr(session, tenant_id=tenant_id, month=period.month)

    assert period.cost_inr == Decimal("18.00")
    assert period.trial_cost_inr == Decimal("12.00")
    assert period.trial_calls == 1 and period.trial_minutes == Decimal("2.00")
    assert fleet_figure == period.trial_cost_inr, "the board and the page must agree"
    covered = {c.call_id: c.trial_covered for c in period.by_call}
    assert covered == {paid_call: False, trial_call: True}


async def test_a_month_with_no_trial_has_paid_figures_equal_to_the_margin() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee="9999.00", included_min=100)
    await _metered_call(tenant_id, agent_id, seconds=600, unit_cost="0.5000")

    body = await _admin_spend(tenant_id)

    assert body["trial_in_month"] is False
    assert body["trial_cost_inr"] == "0.00"
    assert body["paid_cost_inr"] == body["cost_inr"]
    assert body["paid_margin_inr"] == body["margin_inr"]
    assert body["paid_margin_pct"] == body["margin_pct"]


async def test_the_fleet_board_sets_trial_cost_beside_the_margin() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    await _open_trial(tenant_id, started=datetime.now(UTC) - timedelta(minutes=1))
    await _metered_call(tenant_id, agent_id, seconds=600, unit_cost="0.0230")
    token = await _make_admin()

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        async with _client() as http:
            response = await http.get(
                "/v1/admin/spend", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 200, response.text
    body = response.json()

    mine = next(row for row in body["tenants"] if row["tenant_id"] == str(tenant_id))
    assert mine["trial_cost_inr"] == "13.80"
    assert mine["trial_in_month"] is True
    assert mine["paid_cost_inr"] == "0.00"
    assert mine["paid_margin_inr"] == "0.00"
    assert mine["margin_inr"] == "-13.80"
    assert Decimal(body["trial_cost_inr"]) >= Decimal("13.80")
    assert Decimal(body["paid_cost_inr"]) == Decimal(body["cost_inr"]) - Decimal(
        body["trial_cost_inr"]
    )
    assert Decimal(body["paid_margin_inr"]) == Decimal(body["revenue_inr"]) - Decimal(
        body["paid_cost_inr"]
    )


# --------------------------------------------------------------------- cost currency


async def test_an_attested_inr_minute_is_not_a_currency_assumption() -> None:
    """The row shape the ThinnestAI minute meter wrote before it stated its currency."""
    attested_only, agent_only = await _spend_tenant(monthly_fee=None)
    async with tenant_session(attested_only) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', now(), now())"
            ),
            {"i": (cid := uuid7()), "t": attested_only, "a": agent_only, "e": f"e_{cid}"},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'platform_min', 1, 2.5, now(), CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": attested_only,
                "c": cid,
                "m": json.dumps(
                    {
                        "source_currency": "INR",
                        "currency_stated": False,
                        "engine_rate_key": "platform",
                    }
                ),
            },
        )
        attested = await period_attribution(session, tenant_id=attested_only)

    assert attested.cost_currency_stated is True
    assert attested.by_call[0].cost_currency_assumed is False


async def test_a_converted_vendor_figure_still_carries_the_warning() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0.5000")

    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.cost_currency_stated is False


async def test_the_minute_meter_states_its_currency() -> None:
    from apps.api.billing.engine_minutes import engine_minute_cost

    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    call_id = await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0")
    async with tenant_session(tenant_id) as session:
        cost = await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=Decimal(60),
            at=datetime.now(UTC),
        )
    assert cost.cost.source_currency == "INR"
    assert cost.cost.currency_stated is True


# ------------------------------------------------------------------------ the cap


async def test_a_trial_call_draws_no_rupees_from_the_spend_cap() -> None:
    tenant_id, agent_id, _ = await _cap_tenant("trialcap")
    await _plan(tenant_id, included_min=0)
    await _open_trial(tenant_id, started=datetime.now(UTC) - timedelta(minutes=1))

    call_id = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_id, _snapshot(seconds=60, spend="1.9000", ended=datetime.now(UTC)))

    _month, minutes, spend, _capped, billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.0000"), "a minute ceiling still limits trial calling"
    assert spend == Decimal("1.9000"), "our cost is still metered"
    assert billed == Decimal("0"), "a free minute must not draw down the client's ceiling"


async def test_the_cap_route_shows_nothing_spent_during_a_trial() -> None:
    tenant_id, _agent_id, _ = await _cap_tenant("trialcaproute")
    await _open_trial(tenant_id, started=datetime.now(UTC) - timedelta(minutes=1))
    # What the earlier meter left behind: four trial minutes priced at the list rate.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped) VALUES (:t, :m, 4, 13.80, 18.00, false) "
                "ON CONFLICT (tenant_id) DO UPDATE SET billed_inr = 18.00, minutes_used = 4, "
                "month = EXCLUDED.month"
            ),
            {"t": tenant_id, "m": current_billing_month()},
        )
    token = await _make_member(tenant_id)

    async with _client() as http:
        response = await http.get("/v1/billing/caps", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trial_active"] is True
    assert body["spend_used_inr"] == "0.00"
    assert body["minutes_used"] == "4.00"


async def test_the_cap_route_reports_spend_without_a_trial() -> None:
    tenant_id, agent_id, _ = await _cap_tenant("nontrialcap")
    await _plan(tenant_id, included_min=0)
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_id, _snapshot(seconds=60, spend="1.9000", ended=datetime.now(UTC)))
    token = await _make_member(tenant_id)

    async with _client() as http:
        response = await http.get("/v1/billing/caps", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert body["trial_active"] is False
    assert body["spend_used_inr"] == "8.00"


async def test_the_overview_margin_card_sets_trial_cost_beside_the_margin() -> None:
    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    await _open_trial(tenant_id, started=datetime.now(UTC) - timedelta(minutes=1))
    await _metered_call(tenant_id, agent_id, seconds=600, unit_cost="0.0230")
    token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/margin", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["margin_inr"] == "-13.80"
    assert body["trial_cost_inr"] == "13.80"
    assert body["trial_in_month"] is True
    assert body["paid_cost_inr"] == "0.00"
    assert body["paid_margin_inr"] == "0.00"
    assert body["paid_margin_pct"] is None


async def test_the_margin_counts_a_converted_trials_calls_like_its_cost() -> None:
    """The margin card and the fleet row print "N minutes across M calls" beside a cost that
    includes the trial's calls, so the counts are the whole month too — not the client's
    usage panel, which restarts at the trial's end."""
    from apps.api.billing.service import margin_for_tenant
    from apps.api.billing.trials import TRIAL_CONVERTED, end_trial

    tenant_id, agent_id = await _spend_tenant(monthly_fee=None)
    now = datetime.now(UTC)
    await _open_trial(tenant_id, started=now - timedelta(minutes=10))
    await _metered_call(
        tenant_id, agent_id, seconds=120, unit_cost="0.1000", at=now - timedelta(minutes=8)
    )
    async with tenant_session(tenant_id) as session:
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_CONVERTED,
            reason="paid",
            at=now - timedelta(minutes=5),
        )
    await _metered_call(tenant_id, agent_id, seconds=60, unit_cost="0.1000")

    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
        period = await period_attribution(session, tenant_id=tenant_id)

    assert period.calls == 2 and period.minutes == Decimal("3.00")
    assert margin["calls"] == period.calls
    assert margin["minutes_used"] == period.minutes
