"""D-980 (founder, 10 Nov 2026): only unexpired credit is refundable.

A payment's credit that has lapsed, whether or not the daily sweep has reached its lot yet,
is not money a refund may send back. A refund past what is refundable is refused with the
most that can be refunded; the admin wallet read publishes that figure for the refund
screen. Credit bought before the expiry terms carries no `expires_at` and never lapses
(D-900), so it stays refundable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing import credit_expiry
from apps.api.billing.credit_routes import read_credits
from apps.api.billing.payment_routes import RefundIn
from apps.api.billing.service import find_topup, remove_credit_from_lots
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.razorpay_events_test import (
    _admin,
    _configured,  # noqa: F401 - the autouse provider configuration those helpers need
    _fund,
    _install_refund,
    _payment_id,
    _refund_by_amount,
    _request,
    _tenant,
    issue_tenant_refund,
)


def _bought_with_expiry(monkeypatch: pytest.MonkeyPatch, *, lapsed: bool | None) -> None:
    """The next purchase's lot gets an expiry already past (lapsed, not yet swept), one a
    year out, or none at all (credit bought before the expiry terms). A lot's terms are
    frozen once opened, so the expiry is chosen as it opens."""
    now = datetime.now(UTC)
    expires = {True: now - timedelta(days=1), False: now + timedelta(days=365), None: None}

    async def months(_session: object, *, tenant_id: UUID) -> int | None:
        return None if lapsed is None else 12

    monkeypatch.setattr(credit_expiry, "credit_expiry_months_for", months)
    monkeypatch.setattr(credit_expiry, "expires_at_for", lambda *_a, **_k: expires[lapsed])


async def _lot_expiry(tenant_id: UUID, payment_id: str) -> datetime | None:
    async with tenant_session(tenant_id) as session:
        topup = await find_topup(session, tenant_id=tenant_id, ref=payment_id)
        assert topup is not None
        return (
            await session.execute(
                text("SELECT expires_at FROM credit_lots WHERE ledger_entry_id = :e"),
                {"e": topup.entry_id},
            )
        ).scalar_one()


async def _refundable(tenant_id: UUID, payment_id: str) -> Decimal:
    wallet = await read_credits(tenant_id, _admin(), _request())
    return next(p.refundable_inr for p in wallet.payments if p.payment_ref == payment_id)


async def test_credit_past_its_expiry_is_not_refunded_even_before_the_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("LAPSED")
    _bought_with_expiry(monkeypatch, lapsed=True)
    await _fund(tenant_id, payment_id=pid, amount_inr="1000.00")
    expiry = await _lot_expiry(tenant_id, pid)
    assert expiry is not None and expiry < datetime.now(UTC), "lapsed, not yet swept"
    seen = _install_refund(monkeypatch, _refund_by_amount("rfnd_LAPSED"))

    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("500.00"), reason="lapsed"),
            _request(),
            _admin(),
        )
    assert raised.value.code == "refund_exceeds_unspent"
    assert "lapsed is not refundable" in str(raised.value.detail)
    assert raised.value.remediation == "Nothing on this payment can be refunded."
    assert seen == [], "nothing may reach the provider"
    assert await _refundable(tenant_id, pid) == Decimal("0.00")


async def test_a_refund_past_the_unspent_unlapsed_credit_names_the_most_that_can_go_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("MOST")
    _bought_with_expiry(monkeypatch, lapsed=False)
    await _fund(tenant_id, payment_id=pid, amount_inr="2500.00")
    async with tenant_session(tenant_id) as session:
        await remove_credit_from_lots(
            session, tenant_id=tenant_id, corrected_entry_id=None, amount_inr=Decimal("1500.00")
        )
    seen = _install_refund(monkeypatch, _refund_by_amount("rfnd_MOST"))

    assert await _refundable(tenant_id, pid) == Decimal("1000.00")
    with pytest.raises(ProblemError) as raised:
        await issue_tenant_refund(
            tenant_id,
            RefundIn(payment_id=pid, amount_inr=Decimal("1000.01"), reason="too much"),
            _request(),
            _admin(),
        )
    assert raised.value.code == "refund_exceeds_unspent"
    assert raised.value.remediation == "Refund at most ₹1000.00."
    assert seen == []

    done = await issue_tenant_refund(
        tenant_id,
        RefundIn(payment_id=pid, amount_inr=Decimal("1000.00"), reason="the rest"),
        _request(),
        _admin(),
    )
    assert done.recorded is True
    assert await _refundable(tenant_id, pid) == Decimal("0.00")


async def test_credit_bought_before_the_expiry_terms_stays_refundable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    pid = _payment_id("NOTERM")
    _bought_with_expiry(monkeypatch, lapsed=None)
    await _fund(tenant_id, payment_id=pid, amount_inr="800.00")
    assert await _lot_expiry(tenant_id, pid) is None
    _install_refund(monkeypatch, _refund_by_amount("rfnd_NOTERM"))

    assert await _refundable(tenant_id, pid) == Decimal("800.00")
    done = await issue_tenant_refund(
        tenant_id, RefundIn(payment_id=pid, reason="never lapses"), _request(), _admin()
    )
    assert done.recorded is True


async def test_a_payment_with_no_top_up_row_has_nothing_refundable() -> None:
    """The refund route refunds against a payment's top-up row; a reference with none (a
    fee or a debit, never a purchase) publishes zero rather than a figure it cannot honour."""
    from apps.api.billing.credit_routes import _refundable_of

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await _refundable_of(
            session, tenant_id=tenant_id, payment_ref=_payment_id("none")
        ) == Decimal("0")
