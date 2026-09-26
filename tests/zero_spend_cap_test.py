"""A cap of ZERO stops outbound calling at once, even before anything was metered.

`PUT /v1/billing/caps` accepts zero ("as low as they like, including zero") and promises
the limit "takes effect immediately: outbound calling stops". The gate reads only
`spend_state.capped` for the CURRENT month, and `recompute_capped` rewrote the flag only
on a row already stamped with this month — so on a tenant with no row yet (nothing metered
since the 1st, or a new account) the stop button wrote nothing, `capped_now` came back
false, and every dial was allowed until some call completed and the meter armed the flag.
For a running campaign that is every dispatch tick until the first call ends.

Zero is the one ceiling zero counters have already reached (`>=`, the rule `over_cap_sql`
states), so it is the only case that changes: the stale or absent row is rolled to this
month with zero counters and the flag armed. A non-zero ceiling on an unmetered month is
still not reached and still writes nothing.

Run: uv run pytest -q tests/zero_spend_cap_test.py
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.caps import apply_client_caps
from apps.api.billing.service import current_billing_month
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.spend_caps_test import LAST_MONTH, _bill, _gate, _plan, _tenant


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tests/spend_caps_test.py`'s two pins: calling hours sits after the cap check and
    the big red switch is shared state. The refusal cases assert `rule == "spend_cap"`,
    which no stub here can manufacture."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


async def _row(tenant_id: UUID) -> tuple[str, Decimal, Decimal, Decimal, bool] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT month, minutes_used, spend_used, billed_inr, capped "
                    "FROM spend_state WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    return None if row is None else (str(row[0]), row[1], row[2], row[3], bool(row[4]))


async def _set_client_caps(
    tenant_id: UUID, *, cap_min: int | None = None, cap_spend: Decimal | None = None
) -> bool:
    async with tenant_session(tenant_id) as session:
        result = await apply_client_caps(
            session, tenant_id=tenant_id, cap_min=cap_min, cap_spend=cap_spend
        )
    return result.capped_now


async def test_a_zero_spend_cap_stops_the_next_dial_before_anything_is_metered() -> None:
    tenant_id, agent_id, _ = await _tenant("zerocapnew")
    await _plan(tenant_id)
    assert await _row(tenant_id) is None
    assert (await _gate(tenant_id, agent_id)).allowed

    assert await _set_client_caps(tenant_id, cap_spend=Decimal("0")) is True

    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"
    zero = Decimal("0")
    assert await _row(tenant_id) == (current_billing_month(), zero, zero, zero, True)


async def test_a_zero_minute_cap_rolls_a_closed_month_row_and_stops_the_next_dial() -> None:
    """The row still carries LAST month's counters. They are not this month's spend, so
    they are replaced by zeros — which the meter's own rollover would have done — and the
    flag is judged against those zeros, not against last month."""
    tenant_id, agent_id, _ = await _tenant("zerocapstale")
    await _plan(tenant_id)
    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=LAST_MONTH)
    stale = await _row(tenant_id)
    assert stale is not None and stale[0] != current_billing_month()

    assert await _set_client_caps(tenant_id, cap_min=0) is True

    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"
    zero = Decimal("0")
    assert await _row(tenant_id) == (current_billing_month(), zero, zero, zero, True)


async def test_a_non_zero_cap_on_an_unmetered_month_writes_nothing() -> None:
    """Zero counters are inside any positive ceiling, so there is nothing to arm and the
    absent row stays absent — the pre-existing answer, pinned beside the new one."""
    tenant_id, agent_id, _ = await _tenant("posunmetered")
    await _plan(tenant_id)

    assert await _set_client_caps(tenant_id, cap_spend=Decimal("1.00")) is False

    assert await _row(tenant_id) is None
    assert (await _gate(tenant_id, agent_id)).allowed
