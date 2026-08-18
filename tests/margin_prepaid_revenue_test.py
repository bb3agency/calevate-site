"""The margin panel knows what a PREPAID client pays us.

THE DEFECT. `billing.margin_for_tenant` computed

    revenue = usage["monthly_fee_inr"] + usage["overage_cost_inr"]

which is the whole bill for a MANAGED tenant (a retainer plus overage — it is literally
the invoice's subtotal) and is ZERO for a prepaid one. `self_serve` and `trial` are D-34's
other motion: no `plans` row, no monthly fee, no included allowance and no `overage_rate`
— every minute is charged at the published list price and taken out of the wallet by
`charge_for_call`. So the one screen whose entire purpose is "is this client making us
money" reported ₹0.00 revenue against the real supplier cost for every self-serve client:
a negative margin, and `margin_pct = None` because the branch that suppresses a percentage
reads `revenue > 0`.

This is P1.1's shape one layer up. `client_billed_inr` was written to end "what did we pay
for it" being used as "what does the client owe"; the margin panel was still deriving
revenue from the two plan columns a prepaid tenant does not have, while
`_spend_used`'s closed-month branch three functions away already priced the same minutes
at `self_serve_inr_per_min`. Two answers to "what did this client owe us this month", on
one module, and the money screen took the wrong one.

WHAT THIS FILE ASSERTS, and what it deliberately does not. It asserts that a prepaid
tenant's revenue is the wallet's own price for the month's minutes and that the margin is
therefore positive at the configured list price. It does NOT assert a particular
percentage: the list price and the supplier cost are both configuration, and a test that
pinned a ratio would be pinning the founder's pricing rather than the arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.api.billing.service import margin_for_tenant, to_paise
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _call_row, _snapshot, _tenant

#: One minute exactly, so the expected revenue is the list price itself.
_SIXTY_SECONDS = 60

#: What the engine charged US for it — deliberately far below the list price, so a
#: revenue side that fell back to the cost side would be visible rather than plausible.
_SUPPLIER_COST = "1.9000"


async def _set_tier(tenant_id: UUID, tier: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": tier, "i": tenant_id},
        )


async def _clean(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM spend_state WHERE tenant_id = :t"), {"t": tenant_id}
        )


async def test_a_prepaid_clients_margin_counts_the_wallet_debit_as_revenue() -> None:
    """One minute on a self-serve account: revenue is the list price, not zero.

    Before the fix `revenue_inr` came back `0.00`, `margin_inr` was the negative of our
    supplier cost, and `margin_pct` was `None` — the panel describing the motion D-34
    exists to grow as a pure loss.
    """
    tenant_id, agent_id, _ref = await _tenant(f"margin_prepaid_{uuid.uuid4().hex[:6]}")
    await _set_tier(tenant_id, "self_serve")
    ended = datetime.now(UTC)
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id, call_id, _snapshot(seconds=_SIXTY_SECONDS, spend=_SUPPLIER_COST, ended=ended)
    )

    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)

    list_price = get_settings().self_serve_inr_per_min
    assert margin["revenue_inr"] == to_paise(list_price), (
        "a prepaid minute's revenue is the list price the wallet was debited at"
    )
    assert margin["cost_inr"] > 0, "the supplier cost must still be on the panel"
    assert margin["margin_inr"] == to_paise(list_price - Decimal(margin["cost_inr"]))
    assert margin["margin_pct"] is not None, (
        "a percentage is suppressed only when nothing was billed"
    )
    await _clean(tenant_id)


async def test_a_managed_clients_margin_is_still_the_invoice() -> None:
    """The fix must not move the motion it was not about: a managed tenant's revenue is
    the retainer plus the overage, which is exactly the invoice's subtotal."""
    tenant_id, agent_id, _ref = await _tenant(f"margin_managed_{uuid.uuid4().hex[:6]}")
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(
        tenant_id,
        call_id,
        _snapshot(seconds=_SIXTY_SECONDS, spend=_SUPPLIER_COST, ended=datetime.now(UTC)),
    )

    async with tenant_session(tenant_id) as session:
        margin = await margin_for_tenant(session, tenant_id=tenant_id)
        from apps.api.billing.service import usage_summary

        usage = await usage_summary(session, tenant_id=tenant_id)

    expected = (usage["monthly_fee_inr"] or Decimal("0")) + usage["overage_cost_inr"]
    assert margin["revenue_inr"] == to_paise(expected)
    await _clean(tenant_id)
