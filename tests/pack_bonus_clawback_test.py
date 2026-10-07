"""A refunded credit pack takes its bonus back with it (founder decision, 4 Oct 2026).

In full for a full refund, pro rata for a partial one, as a compensating NEGATIVE `bonus`
entry keyed on the refund id, written by `credit_refund` in the refund's own transaction.

No catalogue pack carries a bonus since D-547, so the bonus-bearing cases drive a
synthetic legacy pack through the real crediting path (`pack_paid_for` patched on the
payments module's own binding, as `tests/razorpay_events_test.py` does). The no-bonus case
uses the live catalogue, because "a real pack today claws back nothing" is itself the claim.

Run: uv run pytest -q tests/pack_bonus_clawback_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.credit_packs import (
    PACK_BONUS_CLAWBACK_LABEL,
    PACK_BONUS_CLAWBACK_META_KIND,
    PACK_BONUS_LABEL,
    PACK_BONUS_META_KIND,
    CreditPack,
    pack_by_id,
)
from apps.api.billing.service import get_balance, record_entry
from apps.api.billing.wallet_routes import _entry_label
from apps.api.db.session import tenant_session
from sqlalchemy import text

#: ₹3,000 with a bonus of exactly ₹100 — a ratio of 1/30, which does NOT terminate, so a
#: partial refund's share of the bonus has to round and the sum of the parts is a real test.
LEGACY_PACK = CreditPack(
    pack_id="growth",
    amount_inr=Decimal("3000"),
    clear_inr_per_min=Decimal("5.00"),
    studio_inr_per_min=Decimal("7.00"),
    bonus_pct=Decimal("3.333333333"),
)
BONUS = Decimal("100.0000")


@pytest.fixture
def legacy_bonus(monkeypatch: pytest.MonkeyPatch) -> CreditPack:
    monkeypatch.setattr(
        payments,
        "pack_paid_for",
        lambda pack_id, amount_inr: (
            LEGACY_PACK
            if pack_id == LEGACY_PACK.pack_id and amount_inr == LEGACY_PACK.amount_inr
            else None
        ),
    )
    assert LEGACY_PACK.bonus_credits == BONUS
    return LEGACY_PACK


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Bonus Clawback Clinic",
        slug=f"pbc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _fund(tenant_id: UUID, *, amount_inr: Decimal, pack_id: str | None) -> str:
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(
            session,
            payment=payments.CapturedPayment(
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=amount_inr,
                currency="INR",
                pack_id=pack_id,
            ),
        )
    return payment_id


async def _refund(
    tenant_id: UUID, *, payment_id: str, amount_inr: str, refund_id: str | None = None
) -> payments.TopUpResult:
    async with tenant_session(tenant_id) as session:
        return await payments.credit_refund(
            session,
            refund=payments.RefundEvent(
                refund_id=refund_id or f"rfnd_{uuid.uuid4().hex[:12]}",
                payment_id=payment_id,
                tenant_id=tenant_id,
                amount_inr=Decimal(amount_inr),
                currency="INR",
            ),
        )


async def _balance(tenant_id: UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def _clawbacks(tenant_id: UUID) -> list[tuple[Decimal, str, dict]]:
    """Every clawback row on the wallet: (delta, ref, meta)."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT delta, ref, meta FROM credit_ledger WHERE tenant_id = :t "
                    "AND reason = 'bonus' AND meta->>'kind' = :k ORDER BY occurred_at, id"
                ),
                {"t": tenant_id, "k": PACK_BONUS_CLAWBACK_META_KIND},
            )
        ).all()
    return [(Decimal(str(row[0])), str(row[1]), dict(row[2])) for row in rows]


async def _bonus_rows(tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM credit_ledger WHERE tenant_id = :t "
                        "AND reason = 'bonus'"
                    ),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )


async def test_a_full_refund_takes_back_the_whole_bonus(legacy_bonus: CreditPack) -> None:
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=legacy_bonus.amount_inr, pack_id="growth")
    assert await _balance(tenant_id) == legacy_bonus.amount_inr + BONUS

    result = await _refund(tenant_id, payment_id=pid, amount_inr="3000.00", refund_id="rfnd_F1")

    assert result.recorded is True
    assert result.bonus_clawed_back_inr == BONUS
    assert await _balance(tenant_id) == Decimal("0")
    [(delta, ref, meta)] = await _clawbacks(tenant_id)
    assert delta == -BONUS
    # Its own idempotency key, derived from the refund — not the grant's payment id.
    assert ref == "rfnd_F1"
    assert meta["payment_ref"] == pid
    assert meta["refund_ref"] == "rfnd_F1"


async def test_a_partial_refund_takes_back_that_share(legacy_bonus: CreditPack) -> None:
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=legacy_bonus.amount_inr, pack_id="growth")

    result = await _refund(tenant_id, payment_id=pid, amount_inr="1000.01")

    # 100 x 1000.01 / 3000 = 33.33366..., half-up to the ledger's 4 places.
    assert result.bonus_clawed_back_inr == Decimal("33.3337")
    assert await _balance(tenant_id) == Decimal("3100") - Decimal("1000.01") - Decimal("33.3337")


async def test_two_partials_that_sum_to_full_take_back_exactly_the_bonus(
    legacy_bonus: CreditPack,
) -> None:
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=legacy_bonus.amount_inr, pack_id="growth")

    first = await _refund(tenant_id, payment_id=pid, amount_inr="1000.01")
    second = await _refund(tenant_id, payment_id=pid, amount_inr="1999.99")

    assert first.bonus_clawed_back_inr + second.bonus_clawed_back_inr == BONUS
    assert sum(delta for delta, _, _ in await _clawbacks(tenant_id)) == -BONUS
    assert await _balance(tenant_id) == Decimal("0"), "no rounding residue either way"


async def test_a_repeated_refund_does_not_claw_back_twice(legacy_bonus: CreditPack) -> None:
    """The API response and the `refund.processed` webhook both reach `credit_refund` with
    one refund id; the second is a replay and must move nothing."""
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=legacy_bonus.amount_inr, pack_id="growth")

    first = await _refund(tenant_id, payment_id=pid, amount_inr="1500.00", refund_id="rfnd_R1")
    after_first = await _balance(tenant_id)
    again = await _refund(tenant_id, payment_id=pid, amount_inr="1500.00", refund_id="rfnd_R1")

    assert again.recorded is False
    # The replay still REPORTS the clawback the first call wrote, read off the ledger.
    assert again.bonus_clawed_back_inr == first.bonus_clawed_back_inr == Decimal("50.0000")
    assert await _balance(tenant_id) == after_first
    assert len(await _clawbacks(tenant_id)) == 1


async def test_a_catalogue_pack_with_no_bonus_claws_back_nothing() -> None:
    tenant_id = await _tenant()
    pack = pack_by_id("starter")
    assert pack is not None and pack.bonus_credits == 0
    pid = await _fund(tenant_id, amount_inr=pack.amount_inr, pack_id="starter")

    result = await _refund(tenant_id, payment_id=pid, amount_inr=str(pack.amount_inr))

    assert result.bonus_clawed_back_inr == Decimal("0")
    assert await _bonus_rows(tenant_id) == 0
    assert await _balance(tenant_id) == Decimal("0")


async def test_a_plain_top_up_claws_back_nothing(legacy_bonus: CreditPack) -> None:
    """No pack id on the payment, so no bonus was granted — even with a bonus pack on offer."""
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=Decimal("3000"), pack_id=None)

    result = await _refund(tenant_id, payment_id=pid, amount_inr="3000.00")

    assert result.bonus_clawed_back_inr == Decimal("0")
    assert await _bonus_rows(tenant_id) == 0
    assert await _balance(tenant_id) == Decimal("0")


async def test_a_spent_bonus_is_still_clawed_back_into_overdraft(legacy_bonus: CreditPack) -> None:
    """The refund path's own rule: the money has already moved at the provider, so the
    compensating entries land even if the wallet goes below zero, and the pre-dispatch gate
    then stops dialling. Refusing would hide a real movement."""
    tenant_id = await _tenant()
    pid = await _fund(tenant_id, amount_inr=legacy_bonus.amount_inr, pack_id="growth")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-3050.00"),
            reason="usage",
            ref=f"call-{uuid.uuid4().hex[:8]}",
        )
    assert await _balance(tenant_id) == Decimal("50")

    result = await _refund(tenant_id, payment_id=pid, amount_inr="3000.00")

    assert result.bonus_clawed_back_inr == BONUS
    assert await _balance(tenant_id) == Decimal("50") - Decimal("3000") - BONUS
    [(delta, _, _)] = await _clawbacks(tenant_id)
    assert delta == -BONUS


def test_the_client_reads_the_clawback_in_plain_words() -> None:
    """Both rows are `reason = 'bonus'`; without a label the clawback reads as a bonus with
    a minus sign."""
    assert _entry_label(reason="bonus", kind=PACK_BONUS_CLAWBACK_META_KIND) == (
        PACK_BONUS_CLAWBACK_LABEL
    )
    assert _entry_label(reason="bonus", kind=PACK_BONUS_META_KIND) == PACK_BONUS_LABEL
    assert _entry_label(reason="topup", kind=PACK_BONUS_CLAWBACK_META_KIND) is None
