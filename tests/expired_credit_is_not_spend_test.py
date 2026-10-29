"""Credit that lapses unused left the balance but was not spent.

`credit_expiry.expire_lot` writes a negative `adjustment` stamped `meta.kind =
credit_expiry`. Every spend reader goes through `wallet.DRAWDOWN_BUCKETS_SQL`, so each
surface below must leave that row out of what was spent and show it as credit expired.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from apps.api.analytics import proof
from apps.api.billing import history, tier_routes, wallet, wallet_routes
from apps.api.billing.credit_expiry import CREDIT_EXPIRY_LABEL, CREDIT_EXPIRY_META_KIND
from apps.api.billing.plans import IST, ist_billing_month
from apps.api.billing.service import get_balance
from apps.api.db.session import tenant_session
from apps.api.notifications import daily_summary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.api_security_test import _make_tenant


async def _entry(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    delta: str,
    reason: str,
    at: datetime,
    meta: dict[str, str] | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, created_at, meta) VALUES (gen_random_uuid(), :t, :d, :r, :ref, 0, "
            ":at, now(), CAST(:meta AS jsonb))"
        ),
        {
            "t": tenant_id,
            "d": Decimal(delta),
            "r": reason,
            "ref": f"t-{uuid.uuid4().hex}",
            "at": at,
            "meta": json.dumps(meta) if meta is not None else None,
        },
    )


async def _account() -> tuple[uuid.UUID, datetime]:
    """A wallet that spent ₹40 on a call and lost ₹500 to expiry an hour later, today IST."""
    tenant_id, _slug, _token = await _make_tenant()
    today = datetime.now(UTC).astimezone(IST).date()
    at = datetime.combine(today, time(0, 30), tzinfo=IST)
    async with tenant_session(tenant_id) as session:
        await _entry(session, tenant_id, delta="-40.00", reason="usage", at=at)
        await _entry(
            session,
            tenant_id,
            delta="-500.00",
            reason="adjustment",
            at=at + timedelta(hours=1),
            meta={"kind": CREDIT_EXPIRY_META_KIND, "lot_id": str(uuid.uuid4())},
        )
        # A genuine operator correction is still spend.
        await _entry(session, tenant_id, delta="-5.00", reason="adjustment", at=at)
    return tenant_id, at


async def test_the_wallet_drawdown_shows_expiry_apart_from_spend() -> None:
    tenant_id, at = await _account()
    async with tenant_session(tenant_id) as session:
        balance = await get_balance(session, tenant_id=tenant_id)
        _runway, drawdown = await wallet.read_runway(
            session, tenant_id=tenant_id, balance=balance, now=at + timedelta(hours=2)
        )
    assert drawdown.spent_inr == Decimal("45.00")
    assert drawdown.adjustments_inr == Decimal("5.00")
    assert drawdown.expired_inr == Decimal("500.00")
    out = wallet_routes._drawdown_out(drawdown)
    assert (out.spent_inr, out.expired_inr) == (Decimal("45.00"), Decimal("500.00"))


async def test_the_spend_series_cost_per_result_and_daily_summary_leave_expiry_out() -> None:
    tenant_id, at = await _account()
    day = at.date()
    async with tenant_session(tenant_id) as session:
        series = await history.spend_series(session, tenant_id=tenant_id, start=day, end=day)
        cost = await proof.cost_window(session, tenant_id=tenant_id, days=7, today=day)
        summary = await daily_summary.build_summary(session, tenant_id=tenant_id, day=day)
    assert series.spent_inr == Decimal("45.00")
    assert series.days[-1].spent_inr == Decimal("45.00")
    assert series.expired_inr == Decimal("500.00")
    assert cost.spent_inr == Decimal("45.00")
    assert summary.spent_inr == Decimal("45.00")


async def test_the_statement_list_and_credit_usage_show_credit_expired() -> None:
    tenant_id, at = await _account()
    month = ist_billing_month(at)
    async with tenant_session(tenant_id) as session:
        page = await history.statement_page(
            session, tenant_id=tenant_id, limit=1, before=None, now=at + timedelta(hours=2)
        )
        usage = await tier_routes._period(
            session, tenant_id=tenant_id, period="this_month", start=None, end=None
        )
    row = page.statements[0]
    assert row.month == month
    assert (row.wallet_spent_inr, row.credit_expired_inr) == (Decimal("45.00"), Decimal("500.00"))
    assert (usage.spent_inr, usage.expired_inr) == (Decimal("45.00"), Decimal("500.00"))


def test_an_expiry_row_is_labelled_credit_expired_in_the_ledger() -> None:
    label = wallet_routes._entry_label(reason="adjustment", kind=CREDIT_EXPIRY_META_KIND)
    assert label == CREDIT_EXPIRY_LABEL == "Credit expired"
    assert wallet_routes._entry_label(reason="adjustment", kind=None) is None
