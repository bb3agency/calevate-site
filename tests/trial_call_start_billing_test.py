"""A trial test call is free or paid by the trial's state when the call STARTS (lead decision
17 Nov 2026, rememory 05574e5d). A top-up during the call converts the trial, and that call
stays free: no wallet debit, nothing on the spending limit, and it is neither a paid call on
the usage panel and the statement nor a paid cost on the admin Spend split.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.billing.attribution import period_attribution
from apps.api.billing.caps import read_spend_counters
from apps.api.billing.plans import ist_billing_month
from apps.api.billing.trials import read_trial, start_trial
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.journey_audit_2026_11_10_e4_test import (  # noqa: F401 (autouse fixtures)
    _after_top_up,
    _call,
    _configured,
    _stub_storage,
    _screens,
    _wallet_agrees,
    _webhook_top_up,
)
from tests.spend_caps_test import _call_row, _snapshot
from tests.spend_caps_test import _tenant as _armed_tenant

pytestmark = [pytest.mark.rls]

_ZERO = Decimal("0.00")


async def _prepaid_trial_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(UTC)
    tenant_id, agent_id, _ref = await _armed_tenant(f"tcs_{uuid.uuid4().hex[:6]}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'prepaid', created_at = :c WHERE id = :t"),
            {"t": tenant_id, "c": now - timedelta(days=40)},
        )
        await session.execute(text("DELETE FROM plans WHERE tenant_id = :t"), {"t": tenant_id})
        await start_trial(
            session,
            tenant_id=tenant_id,
            days=14,
            actor_user_id=None,
            free_minutes=30,
            at=now - timedelta(hours=1),
        )
    return tenant_id, agent_id


async def test_a_trial_call_that_spans_the_first_top_up_stays_free() -> None:
    tenant_id, agent_id = await _prepaid_trial_tenant()
    month = ist_billing_month(datetime.now(UTC))
    call_id = await _call_row(tenant_id, agent_id)
    started = datetime.now(UTC) - timedelta(seconds=30)

    await _webhook_top_up(tenant_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        trial = await read_trial(session, tenant_id=tenant_id)
    assert trial is not None and trial.status == "converted"

    ended = datetime.now(UTC) + timedelta(seconds=90)
    snapshot = _snapshot(seconds=120, spend="0.5000", ended=ended).model_copy(
        update={"started_at": started}
    )
    await _meter(tenant_id, call_id, snapshot)

    assert await _wallet_agrees(tenant_id) == Decimal("1000.00"), "the call was free at its start"
    s = await _screens(tenant_id, month)
    assert s["counters"].billed_inr == _ZERO
    assert s["usage"]["minutes_used"] == _ZERO, "a free call is not a paid-period minute"
    assert s["usage"]["calls"] == 0
    assert s["statement"].calls == 0
    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id, month=month)
    covered = {c.call_id: c.trial_covered for c in period.by_call}
    assert covered == {call_id: True}
    assert period.trial_calls == 1


async def test_a_call_that_starts_after_the_top_up_is_charged() -> None:
    tenant_id, agent_id = await _prepaid_trial_tenant()
    month = ist_billing_month(datetime.now(UTC))
    await _webhook_top_up(tenant_id, "1000.00")

    paid_call = await _call(tenant_id, agent_id, seconds=60, ended=_after_top_up(60))

    balance = await _wallet_agrees(tenant_id)
    assert balance < Decimal("1000.00")
    s = await _screens(tenant_id, month)
    assert s["counters"].billed_inr == Decimal("1000.00") - balance
    assert s["usage"]["calls"] == 1
    async with tenant_session(tenant_id) as session:
        period = await period_attribution(session, tenant_id=tenant_id, month=month)
        counters = await read_spend_counters(session, tenant_id=tenant_id)
    assert {c.call_id: c.trial_covered for c in period.by_call} == {paid_call: False}
    assert counters.billed_inr > 0
