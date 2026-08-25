"""The minutes the CEILING is judged against are the minutes the CLIENT is shown.

There were two spellings of "how many minutes has this tenant used this month".

* `spend_state.minutes_used` accumulated the meter's own `duration_s / 60`, one call at a
  time, at the column's NUMERIC(14,4) scale. `over_cap_sql` compares that against
  `cap_min`, so it is the number that decides whether a dial happens.
* `usage_summary.minutes_used` is the month's total SECONDS divided once and allocated to
  paise (`_tier_totals` / `allocate_paise`). It is the number on the client's own panel,
  and `minutes_left` is derived from it.

Measured on this tree before the fix, four calls of 3847 / 2913 / 611 / 137 seconds:

    spend_state.minutes_used   125.1333
    usage_summary              125.13

The drift is the sum of the per-call rounding errors and it only ever grows within a
month, so on a busy tenant the two land either side of an integer ceiling: the panel says
there are minutes left while the gate has already stopped the dialling, or the reverse.

THE FIX is that the meter no longer computes a minute figure of its own.
`billing.service.month_increment` returns the difference this call makes to the LEDGER's
paise-exact month total, exactly as it already returned the difference the call makes to
the month's overage bill, and the counter accumulates that. Because `rung_minutes`
guarantees its parts sum to `to_paise(total_seconds / 60)`, the increments telescope to
precisely the figure the panel prints — and every increment is a two-decimal value the
column stores without rounding at all.

Run: uv run pytest -q tests/counter_minutes_match_the_panel_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.service import usage_summary
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_caps_test import _bill, _plan, _spend_state, _tenant

#: Durations that do NOT divide by 60. A fixture of whole minutes cannot show this
#: defect, which is why the suite had not — the same trap `tests/money_walk_test.py`
#: names about round rates.
_AWKWARD_SECONDS = (3847, 2913, 611, 137, 89, 1451)


async def _voice(tenant_id: UUID, agent_id: UUID) -> None:
    """Set the one voice quality (the single-tier voice decision). The minute counter this
    test checks is rung-independent, so a single voice exercises it fully."""
    from apps.api.agents.voices import default_voice

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :i"),
            {"v": default_voice().id, "i": agent_id},
        )


@pytest.mark.parametrize("tier", ["managed", "self_serve"])
async def test_the_counter_and_the_panel_report_the_same_minutes(tier: str) -> None:
    """Both motions, because the minute counter is the ceiling's for BOTH of them and
    the two took different branches through the meter."""
    tenant_id, agent_id, _ref = await _tenant(f"cm{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )
    now = datetime.now(UTC)
    await _voice(tenant_id, agent_id)
    for seconds in _AWKWARD_SECONDS:
        await _bill(tenant_id, agent_id, seconds=seconds, spend="1.0000", ended=now)

    _month, counter_minutes, _spend, _capped, _billed = await _spend_state(tenant_id)
    async with tenant_session(tenant_id) as session:
        panel_minutes = (await usage_summary(session, tenant_id=tenant_id))["minutes_used"]

    assert counter_minutes == panel_minutes, (
        f"the ceiling is judged against {counter_minutes} while the client is shown {panel_minutes}"
    )
    # And it is the honest figure, not merely a matching one: 9048 seconds is 150.80 min.
    assert panel_minutes == Decimal("150.80")


async def test_the_counters_minutes_are_stored_without_rounding() -> None:
    """The increment is a paise figure, so NUMERIC(14,4) holds it exactly. A counter that
    only matched after quantization would drift again the moment a reader compared the
    raw column, which is what `over_cap_sql` does."""
    tenant_id, agent_id, _ref = await _tenant(f"cq{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _bill(tenant_id, agent_id, seconds=137, spend="1.0000", ended=datetime.now(UTC))

    _month, counter_minutes, _spend, _capped, _billed = await _spend_state(tenant_id)
    assert counter_minutes == Decimal("2.28"), "137s is 2.2833 min, published as 2.28"
    assert counter_minutes.as_tuple().exponent >= -4, "the column must not have rounded it"


async def test_the_gate_and_the_panel_agree_at_the_ceiling() -> None:
    """The consequence the arithmetic exists for: `minutes_left` reaching zero and the
    dial gate refusing are the same event, not two events a rounding apart."""
    from apps.api.compliance.service import check_dispatch

    async def gate(tenant_id: UUID, agent_id: UUID) -> bool:
        phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
        async with tenant_session(tenant_id) as session:
            return (
                await check_dispatch(
                    session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
                )
            ).allowed

    tenant_id, agent_id, _ref = await _tenant(f"cg{uuid.uuid4().hex[:6]}")
    # A ceiling of 3 minutes, approached by calls that do not divide by 60.
    await _plan(tenant_id, cap_min=3, included_min=0)
    now = datetime.now(UTC)
    for seconds in (61, 61, 61):
        await _bill(tenant_id, agent_id, seconds=seconds, spend="0.5000", ended=now)

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
    allowed = await gate(tenant_id, agent_id)

    assert summary["minutes_used"] == Decimal("3.05")
    assert summary["minutes_left"] == 0
    assert not allowed, "the panel says no minutes are left and the gate must agree"
