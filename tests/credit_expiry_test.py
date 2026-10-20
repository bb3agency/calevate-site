"""Pack credit lapses some months after purchase, once the Terms say so (D-840)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.billing import credit_expiry
from apps.api.billing import lots as credit_lots
from apps.api.billing.credit_expiry import (
    assert_expiry_may_switch_on,
    credit_expiry_months,
    due_lots,
    expire_lot,
    expires_at_for,
)
from apps.api.billing.plans import IST
from apps.api.billing.service import (
    LotRates,
    apply_credit_to_lots,
    find_entry_by_ref,
    get_balance,
    record_entry,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers.credit_expiry import expire_credit_lots
from sqlalchemy import text
from tests.spend_attribution_test import _tenant


@pytest.fixture
def expiry_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Twelve months, with a Terms revision that exists standing in for the approved one."""
    monkeypatch.setattr(credit_expiry, "TERMS_REVISION_STATING_EXPIRY", "1")
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", 12)


async def _buy(tenant_id: uuid.UUID, amount: str) -> uuid.UUID:
    """A pack purchase: the ledger credit, then its lot, in one transaction."""
    ref = f"TEST-{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        balance = await record_entry(
            session, tenant_id=tenant_id, delta=Decimal(amount), reason="topup", ref=ref
        )
        entry = await find_entry_by_ref(session, tenant_id=tenant_id, reason="topup", ref=ref)
        assert entry is not None
        credited = await apply_credit_to_lots(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal(amount),
            balance_after=balance.amount_inr,
            rates=LotRates(clear_inr_per_min=Decimal("4.50"), studio_inr_per_min=Decimal("6.00")),
            source="topup",
            pack_id="starter",
            ledger_entry_id=entry.entry_id,
        )
    assert credited.lot_id is not None
    return credited.lot_id


def test_the_term_is_calendar_months_in_ist_clamped_to_the_month() -> None:
    bought = datetime(2026, 1, 31, 10, 0, tzinfo=IST)
    assert expires_at_for(bought, months=1) == datetime(2026, 2, 28, 10, 0, tzinfo=IST)
    assert expires_at_for(bought, months=12) == datetime(2027, 1, 31, 10, 0, tzinfo=IST)
    # 20:00 UTC on 31 Mar is 01:30 IST on 1 Apr: the IST date is what is counted from.
    late = datetime(2026, 3, 31, 20, 0, tzinfo=UTC)
    assert expires_at_for(late, months=1) == datetime(2026, 5, 1, 1, 30, tzinfo=IST)


def test_the_setting_is_refused_and_ignored_until_the_terms_state_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "credit_pack_expiry_months", 12)
    assert credit_expiry_months() is None
    with pytest.raises(ProblemError) as caught:
        assert_expiry_may_switch_on(12)
    assert caught.value.code == "credit_expiry_terms_not_published"
    assert_expiry_may_switch_on(None)


async def test_credit_bought_while_expiry_is_off_never_expires() -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "1000")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.expires_at is None


async def test_a_pack_bought_with_expiry_on_lapses_once_by_an_appended_row(
    expiry_on: None,
) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "1000")
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.expires_at is not None
    assert timedelta(days=364) < lot.expires_at - lot.opened_at < timedelta(days=367)

    later = lot.expires_at + timedelta(seconds=1)
    async with tenant_session(tenant_id) as session:
        assert await due_lots(session, now=lot.expires_at - timedelta(seconds=1)) == []
        assert await due_lots(session, now=later) == [lot_id]
        expired = await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=later)
    assert expired is not None and expired.credits_inr == Decimal("1000.0000")
    async with tenant_session(tenant_id) as session:
        again = await expire_lot(session, tenant_id=tenant_id, lot_id=lot_id, now=later)
        balance = await get_balance(session, tenant_id=tenant_id)
        rows = (
            await session.execute(
                text(
                    "SELECT delta, reason, meta->>'kind' FROM credit_ledger "
                    "WHERE tenant_id = :t AND ref = :r"
                ),
                {"t": tenant_id, "r": f"credit_expiry:{lot_id}"},
            )
        ).all()
        closed = await credit_lots.read_lot(session, lot_id=lot_id)
    assert again is None, "a second run expires nothing"
    assert balance.amount_inr == Decimal("0")
    assert [(Decimal(str(r[0])), r[1], r[2]) for r in rows] == [
        (Decimal("-1000.00"), "adjustment", "credit_expiry")
    ]
    assert closed is not None and closed.closed_at is not None
    assert closed.credits_remaining == 0


async def test_the_daily_job_expires_only_what_is_due(expiry_on: None) -> None:
    tenant_id, _agent = await _tenant(monthly_fee=None)
    lot_id = await _buy(tenant_id, "500")
    summary = await expire_credit_lots({})
    assert "'failed': 0" in summary
    async with tenant_session(tenant_id) as session:
        lot = await credit_lots.read_lot(session, lot_id=lot_id)
    assert lot is not None and lot.closed_at is None, "a lot not yet due was expired"
