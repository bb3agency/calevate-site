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

EACH CASE NAMES ITS SIDE OF THE D-681 CUTOVER. From `CLIENT_PULSE_EFFECTIVE_FROM` a call
bills `ceil(seconds / 30) x 0.5` minutes; before it, the exact seconds. These tests used
to bill at `datetime.now()` and assert by-the-second figures, so they changed meaning on
the cutover date. A post-cutover case bills at the current instant (asserted to be after
the cutover — the gate reads the open month, so it cannot be a fixed date); a pre-cutover
case bills at a fixed instant in September 2026 and reads that month.

Run: uv run pytest -q tests/counter_minutes_match_the_panel_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.rates import CLIENT_PULSE_EFFECTIVE_FROM
from apps.api.billing.service import usage_summary
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_caps_test import _bill, _plan, _spend_state, _tenant

#: Durations that do NOT divide by 60 or by 30. A fixture of whole minutes cannot show
#: this defect, which is why the suite had not — the same trap `tests/money_walk_test.py`
#: names about round rates.
_AWKWARD_SECONDS = (3847, 2913, 611, 137, 89, 1451)

#: Noon IST on 15 Sep 2026: before the cutover, in a month of its own.
_BEFORE_CUTOVER = datetime(2026, 9, 15, 6, 30, tzinfo=UTC)
_BEFORE_MONTH = "2026-09"


def _after_cutover() -> datetime:
    """Now, which must be on the 30-second side of D-681."""
    now = datetime.now(UTC)
    assert now >= CLIENT_PULSE_EFFECTIVE_FROM, "a post-cutover case needs a post-cutover clock"
    return now


async def _voice(tenant_id: UUID, agent_id: UUID) -> None:
    """Set the one voice quality (the single-tier voice decision). The minute counter this
    test checks is rung-independent, so a single voice exercises it fully."""
    from tests.voice_fixture import TEST_VOICE_ID

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :i"),
            {"v": TEST_VOICE_ID, "i": agent_id},
        )


#: Post-cutover, per call: ceil(s/30) steps of 0.5 min —
#:   3847 -> 129 -> 64.5   2913 -> 98 -> 49.0   611 -> 21 -> 10.5
#:    137 ->   5 ->  2.5     89 ->  3 ->  1.5  1451 -> 49 -> 24.5   total 152.50
#: Pre-cutover: 3847+2913+611+137+89+1451 = 9048 s / 60 = 150.80.
_SIDES = pytest.mark.parametrize(
    ("side", "expected"),
    [("after", Decimal("152.50")), ("before", Decimal("150.80"))],
)


@_SIDES
@pytest.mark.parametrize("tier", ["managed", "self_serve"])
async def test_the_counter_and_the_panel_report_the_same_minutes(
    tier: str, side: str, expected: Decimal
) -> None:
    """Both motions, because the minute counter is the ceiling's for BOTH of them and
    the two took different branches through the meter."""
    tenant_id, agent_id, _ref = await _tenant(f"cm{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )
    ended, month = (_after_cutover(), None) if side == "after" else (_BEFORE_CUTOVER, _BEFORE_MONTH)
    await _voice(tenant_id, agent_id)
    for seconds in _AWKWARD_SECONDS:
        await _bill(tenant_id, agent_id, seconds=seconds, spend="1.0000", ended=ended)

    counter_month, counter_minutes, _spend, _capped, _billed = await _spend_state(tenant_id)
    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id, month=month)
    assert counter_month == summary["month"]
    panel_minutes = summary["minutes_used"]

    assert counter_minutes == panel_minutes, (
        f"the ceiling is judged against {counter_minutes} while the client is shown {panel_minutes}"
    )
    # And it is the billed figure, not merely a matching one.
    assert panel_minutes == expected


@pytest.mark.parametrize(
    ("side", "expected"),
    [
        # ceil(137/30) = 5 steps x 0.5 = 2.50 min.
        ("after", Decimal("2.50")),
        # 137/60 = 2.2833 min, published as 2.28 — the case that needs the paise increment.
        ("before", Decimal("2.28")),
    ],
)
async def test_the_counters_minutes_are_stored_without_rounding(
    side: str, expected: Decimal
) -> None:
    """The increment is a paise figure, so NUMERIC(14,4) holds it exactly. A counter that
    only matched after quantization would drift again the moment a reader compared the
    raw column, which is what `over_cap_sql` does."""
    tenant_id, agent_id, _ref = await _tenant(f"cq{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    ended = _after_cutover() if side == "after" else _BEFORE_CUTOVER
    await _bill(tenant_id, agent_id, seconds=137, spend="1.0000", ended=ended)

    _month, counter_minutes, _spend, _capped, _billed = await _spend_state(tenant_id)
    assert counter_minutes == expected
    assert counter_minutes.as_tuple().exponent >= -4, "the column must not have rounded it"


async def test_the_gate_and_the_panel_agree_at_the_ceiling() -> None:
    """The consequence the arithmetic exists for: `minutes_left` reaching zero and the
    dial gate refusing are the same event, not two events a rounding apart.

    Post-cutover only: the gate judges the open month, and every open month from here on
    is on the 30-second side. Two 61 s calls bill ceil(61/30) = 3 steps = 1.5 min each,
    3.00 min — the ceiling exactly — where by-the-second they would be 122 s = 2.03 min and
    the gate would still dial. So the gate is shown to count the billed minutes."""
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
    # A ceiling of 3 minutes, approached by calls that divide by neither 60 nor 30.
    await _plan(tenant_id, cap_min=3, included_min=0)
    now = _after_cutover()
    for seconds in (61, 61):
        await _bill(tenant_id, agent_id, seconds=seconds, spend="0.5000", ended=now)

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
    allowed = await gate(tenant_id, agent_id)

    assert summary["minutes_used"] == Decimal("3.00")
    assert summary["minutes_left"] == 0
    assert not allowed, "the panel says no minutes are left and the gate must agree"
