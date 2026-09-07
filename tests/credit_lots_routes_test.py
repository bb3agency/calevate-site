"""Every credit ROUTE opens, restates or draws down the lot its ledger row is about.

`credit_lots_wiring_test.py` proves the seam's arithmetic against the functions. This
proves the four admin credit routes and the Razorpay capture actually CALL it — the class
of defect where the money is right on the ledger and the terms it was sold under are
missing, which no screen shows and no balance check catches.

Mounted the way `credit_adjustment_test.py` mounts it: a bare app with the real error
handlers, so the RBAC boot assertion is exercised against this router too.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from apps.api.admin import service as admin_service
from apps.api.billing import payments
from apps.api.billing.credit_routes import (
    credit_adjustment_confirmation,
    credit_grant_confirmation,
    topup_restatement_confirmation,
)
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.lots import CallDemand
from apps.api.billing.service import charge_for_call
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.credit_lots_helpers import lot_rows


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Lot Routes Clinic",
        slug=f"lotr-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = 'self_serve' WHERE id = :i"),
            {"i": tenant_id},
        )
    return tenant_id


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def test_a_manual_topup_opens_a_lot_at_the_free_amount_rates() -> None:
    """An operator recording a bank transfer names no pack, so plan §0 Q3 decides: ₹6,000
    is more than the ₹5,000 rung, so it is sold at that rung's rates. How the money
    arrived must not change what it buys."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "6000.00", "payment_ref": "UTR-LOT-1"},
        )
    assert posted.status_code == 200, posted.text
    (lot,) = await lot_rows(tenant_id)
    assert lot["source"] == "topup"
    assert lot["pack_id"] is None
    assert lot["credits_total"] == lot["credits_remaining"] == Decimal("6000.0000")
    assert (lot["sarvam_inr_per_min"], lot["cartesia_inr_per_min"]) == (
        Decimal("5.0000"),
        Decimal("7.0000"),
    )


async def test_a_grant_opens_a_lot_at_the_list_rates() -> None:
    """Plan §0 Q4 — a gift is spent at the standard price, and it is `source='grant'` so a
    statement can still report bought and given credit apart."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        granted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/grants",
            headers=_headers(token, credit_grant_confirmation(Decimal("2500.00"))),
            json={
                "amount_inr": "2500.00",
                "grant_ref": "GRANT-LOT-1",
                "reason": "two days of downtime on their line",
            },
        )
    assert granted.status_code == 201, granted.text
    (lot,) = await lot_rows(tenant_id)
    assert lot["source"] == "grant"
    assert (lot["sarvam_inr_per_min"], lot["cartesia_inr_per_min"]) == (
        Decimal("5.0000"),
        Decimal("8.0000"),
    )


async def test_a_restatement_grows_the_purchases_own_lot_rather_than_opening_a_second() -> None:
    """A restatement is one bank transfer stated correctly, so it was sold at the rates
    that transfer was sold at. A second lot behind it would price one payment at two cards
    and put the difference behind the client's own earlier purchases in the queue."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "5000.00", "payment_ref": "UTR-LOT-2"},
        )
        restated = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_headers(
                token, topup_restatement_confirmation("UTR-LOT-2", Decimal("8000.00"))
            ),
            json={
                "payment_ref": "UTR-LOT-2",
                "corrected_amount_inr": "8000.00",
                "reason": "the statement shows the larger figure",
            },
        )
    assert restated.status_code == 200, restated.text
    lots = await lot_rows(tenant_id)
    assert len(lots) == 1, "one payment, one lot"
    assert lots[0]["credits_total"] == lots[0]["credits_remaining"] == Decimal("8000.0000")
    # The rates are the ORIGINAL purchase's and did not move with the correction.
    assert lots[0]["sarvam_inr_per_min"] == Decimal("5.0000")
    assert lots[0]["cartesia_inr_per_min"] == Decimal("7.0000")


async def test_an_adjustment_that_takes_credit_back_restates_the_lot_it_corrects() -> None:
    """The route's own headline case, one layer down: the wallet falls by ₹1,000 and so
    does the purchase's lot, so the balance and the lots stay one statement."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "5000.00", "payment_ref": "UTR-LOT-3"},
        )
        entry_id = posted.json()["entry_id"]
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(entry_id))),
            json={
                "corrects_entry_id": entry_id,
                "amount_inr": "1000.00",
                "reason": "we credited more than the bank moved",
            },
        )
    assert adjusted.status_code == 200, adjusted.text
    (lot,) = await lot_rows(tenant_id)
    assert lot["credits_total"] == lot["credits_remaining"] == Decimal("4000.0000")


async def test_a_full_reversal_empties_the_lot_and_the_route_still_answers() -> None:
    """`credits_total > 0` is a CHECK, so a purchase reversed in full cannot be restated
    to nothing — this is the regression guard for the 422 that produced (the route's most
    important case refusing itself). The credit comes off the queue instead."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "50000.00", "payment_ref": "UTR-WRONG"},
        )
        entry_id = posted.json()["entry_id"]
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(entry_id))),
            json={
                "corrects_entry_id": entry_id,
                "amount_inr": "50000.00",
                "reason": "credited to the wrong client",
            },
        )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["balance_inr"] == "0.00"
    (lot,) = await lot_rows(tenant_id)
    assert lot["credits_remaining"] == Decimal("0.0000")
    assert lot["closed_at"] is not None


async def test_an_adjustment_that_credits_back_opens_a_lot_at_the_list_rates() -> None:
    """Correcting a USAGE row puts credit back, and the minutes it charged for are gone —
    there is nothing to restate, so it is a fresh lot at the standard price (plan §0 Q4).

    The wallet is funded first and the call is charged through the real debit, because a
    credit-back onto an OVERDRAWN wallet correctly opens no lot at all: it repays the debt
    (§0 Q5) and buys no calling time. Both are right, and only this one is a new lot.
    """
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "1000.00", "payment_ref": "UTR-LOT-4"},
        )
    async with tenant_session(tenant_id) as session:
        await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("60"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
        entry_id = (
            await session.execute(
                text("SELECT id FROM credit_ledger WHERE tenant_id = :t AND reason = 'usage'"),
                {"t": tenant_id},
            )
        ).scalar_one()
    async with _client() as http:
        adjusted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token),
            json={
                "corrects_entry_id": str(entry_id),
                "amount_inr": "300.00",
                "reason": "the call was on us",
            },
        )
    assert adjusted.status_code == 200, adjusted.text
    bought, given = await lot_rows(tenant_id)
    assert bought["credits_remaining"] == Decimal("700.0000")
    assert given["source"] == "grant"
    assert given["credits_remaining"] == Decimal("300.0000")
    assert given["sarvam_inr_per_min"] == Decimal("5.0000")


async def test_a_captured_payment_opens_a_lot_at_its_packs_rates() -> None:
    """The self-serve motion: the pack the client chose is what freezes the two rates, and
    it is stamped on the lot so a historical row still resolves after the card moves."""
    tenant_id = await _tenant()
    payment = payments.CapturedPayment(
        payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        amount_inr=Decimal("15000.00"),
        currency="INR",
        pack_id="plus",
    )
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(session, payment=payment)
    (lot,) = await lot_rows(tenant_id)
    assert lot["source"] == "topup"
    assert lot["pack_id"] == "plus"
    assert (lot["sarvam_inr_per_min"], lot["cartesia_inr_per_min"]) == (
        Decimal("4.7000"),
        Decimal("6.5000"),
    )


async def test_a_captured_payment_with_no_pack_falls_to_the_free_amount_rule() -> None:
    """A plain top-up through the provider carries no pack in its notes. It is the same
    ₹6,000 as the manual route above and must buy the same minute."""
    tenant_id = await _tenant()
    payment = payments.CapturedPayment(
        payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        amount_inr=Decimal("6000.00"),
        currency="INR",
    )
    async with tenant_session(tenant_id) as session:
        await payments.credit_captured_payment(session, payment=payment)
    (lot,) = await lot_rows(tenant_id)
    assert lot["pack_id"] is None
    assert lot["cartesia_inr_per_min"] == Decimal("7.0000")
