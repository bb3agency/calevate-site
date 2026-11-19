"""A managed client whose trial ended mid-month: the live spend counter charges the overage
the invoice prints, not overage on allowance the free trial minutes used up.

`usage_summary` (and so the invoice) prices overage from the trial boundary over paid calls
only; `month_increment` prices the counter's rupees over the same window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.api.billing.service import usage_summary
from apps.api.billing.trials import TRIAL_CONVERTED, end_trial, start_trial
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from tests.spend_caps_test import _call_row, _plan, _snapshot, _spend_state
from tests.spend_caps_test import _tenant as _cap_tenant


async def test_the_counter_charges_the_invoiced_overage_after_a_trial_ends() -> None:
    tenant_id, agent_id, _ = await _cap_tenant("trialendcounter")
    await _plan(tenant_id, included_min=2)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session, tenant_id=tenant_id, days=7, actor_user_id=None, at=now - timedelta(minutes=20)
        )
    trial_call = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        trial_call,
        _snapshot(seconds=120, spend="0.5000", ended=now - timedelta(minutes=15)),
    )
    async with tenant_session(tenant_id) as session:
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome=TRIAL_CONVERTED,
            reason="paid",
            at=now - timedelta(minutes=10),
        )
    paid_call = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, paid_call, _snapshot(seconds=180, spend="0.7500", ended=now))

    _month, _minutes, _spend, _capped, billed = await _spend_state(tenant_id)
    async with tenant_session(tenant_id) as session:
        usage = await usage_summary(session, tenant_id=tenant_id)

    # Three paid minutes against two included: one minute of overage at ₹8.00.
    assert usage["overage_cost_inr"] == Decimal("8.00")
    assert billed == usage["overage_cost_inr"] + usage["llm_surcharge_inr"]
