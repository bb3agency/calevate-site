"""Prepaid credit packs: the margin invariant, the catalogue shape, and the bonus grant.

The properties worth protecting, in the order they cost money:

- **Every pack holds ≥20% gross margin at the cost floor.** This is THE guard: a future
  bonus set deep enough to sell minutes below cost fails CI here, and the cost basis is read
  from the cost model (`rates.SELF_SERVE_COST_FLOOR_INR_PER_MIN`), never written as a literal,
  so the check re-scores when the cost model moves.
- **A pack payment grants paid AND bonus credits, once**, as two clearly-labelled ledger
  entries in one transaction, idempotent on the payment id.
- **A plain top-up (no pack) grants no bonus**, and the 0%-bonus pack writes no bonus row.
- **Bonus credits are tenant-isolated** — they ride the existing `credit_ledger` RLS.
- **Money is Decimal end to end** (hard rule 7): the effective rate and credits are exact.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing import payments
from apps.api.billing.credit_packs import MIN_GROSS_MARGIN as MIN_MARGIN
from apps.api.billing.credit_packs import (
    PACK_CATALOGUE,
    CreditPack,
    pack_by_id,
    pack_effective_rate_inr_per_min,
    pack_gross_margin_ratio,
    pack_talk_time_minutes,
)
from apps.api.billing.payment_routes import router as topup_router
from apps.api.billing.payment_routes import webhook_router
from apps.api.billing.rates import SELF_SERVE_COST_FLOOR_INR_PER_MIN
from apps.api.core.errors import install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.signup_routes import router as signup_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# The founder-approved launch rate the whole margin table was struck at. Pinned as a literal
# HERE (not read from config) precisely so this test proves the approved rate card holds
# regardless of what `self_serve_inr_per_min` happens to be set to on any given branch.
APPROVED_LIST_RATE = Decimal("5.00")

WEBHOOK_SECRET = "whsec_pack_test_secret"


# --- the margin guard (pure, no DB) -------------------------------------------


def test_every_pack_holds_the_gross_margin_floor_at_the_live_rate() -> None:
    """THE GUARD. At the configured list rate and the cost model's floor, every pack clears
    the 20% margin line. A bonus raised too far, or a list rate dropped too low, fails here
    — which is the whole point: the invariant is enforced against the numbers in the tree."""
    list_rate = get_settings().self_serve_inr_per_min
    for pack in PACK_CATALOGUE:
        margin = pack_gross_margin_ratio(
            pack, list_rate=list_rate, cost_inr_per_min=SELF_SERVE_COST_FLOOR_INR_PER_MIN
        )
        assert margin >= MIN_MARGIN, (
            f"pack {pack.pack_id} ({pack.bonus_pct}% bonus) margin {margin} "
            f"< floor {MIN_MARGIN} at list rate {list_rate}, cost "
            f"{SELF_SERVE_COST_FLOOR_INR_PER_MIN}"
        )


def test_the_approved_launch_table_holds_at_five_rupees() -> None:
    """The founder-approved rate card, pinned at ₹5.00/min. Each pack's effective rate
    matches the approved table and clears 20% margin at the ₹3.70 floor — so the invariant
    is documented against the exact numbers that were signed off, not just today's config."""
    expected_effective = {
        "starter": Decimal("5.00"),
        "growth": Decimal("4.85"),
        "scale": Decimal("4.76"),
        "pro": Decimal("4.67"),
        "max": Decimal("4.63"),
    }
    for pack in PACK_CATALOGUE:
        effective = pack_effective_rate_inr_per_min(pack, list_rate=APPROVED_LIST_RATE)
        assert abs(effective - expected_effective[pack.pack_id]) < Decimal("0.01"), (
            f"{pack.pack_id}: effective {effective} vs approved {expected_effective[pack.pack_id]}"
        )
        margin = pack_gross_margin_ratio(
            pack,
            list_rate=APPROVED_LIST_RATE,
            cost_inr_per_min=SELF_SERVE_COST_FLOOR_INR_PER_MIN,
        )
        assert margin >= MIN_MARGIN, f"{pack.pack_id} margin {margin} < {MIN_MARGIN} at ₹5.00"


def test_a_bonus_that_breaks_the_floor_would_fail_the_guard() -> None:
    """The guard has teeth: a hypothetical over-generous pack (15% at ₹5.00) really does
    fall below 20% margin, so the assertion above is not vacuously true."""
    greedy = CreditPack(pack_id="greedy", amount_inr=Decimal("50000"), bonus_pct=Decimal("15"))
    margin = pack_gross_margin_ratio(
        greedy, list_rate=APPROVED_LIST_RATE, cost_inr_per_min=SELF_SERVE_COST_FLOOR_INR_PER_MIN
    )
    assert margin < MIN_MARGIN


# --- catalogue shape ----------------------------------------------------------


def test_exactly_one_pack_is_best_value() -> None:
    best = [p for p in PACK_CATALOGUE if p.best_value]
    assert len(best) == 1
    # The deepest pack (largest amount) carries the badge.
    assert best[0].amount_inr == max(p.amount_inr for p in PACK_CATALOGUE)


def test_pack_ids_are_unique_and_resolvable() -> None:
    ids = [p.pack_id for p in PACK_CATALOGUE]
    assert len(ids) == len(set(ids))
    for pack in PACK_CATALOGUE:
        assert pack_by_id(pack.pack_id) is pack
    assert pack_by_id("no-such-pack") is None


def test_credit_derivations_are_one_rupee_per_credit() -> None:
    """1 credit = ₹1: paid credits equal the amount, bonus is amountxpct, total is the sum,
    and talk time is total/list_rate."""
    growth = pack_by_id("growth")
    assert growth is not None
    assert growth.paid_credits == Decimal("2999.0000")
    assert growth.bonus_credits == Decimal("89.9700")  # 2999 x 3%
    assert growth.total_credits == Decimal("3088.9700")
    # At ₹5.00/min: 3088.97 credits ÷ 5 = 617.79 minutes.
    minutes = pack_talk_time_minutes(growth, list_rate=APPROVED_LIST_RATE)
    assert abs(minutes - Decimal("617.794")) < Decimal("0.01")


def test_the_starter_pack_has_no_bonus() -> None:
    starter = pack_by_id("starter")
    assert starter is not None
    assert starter.bonus_pct == 0
    assert starter.bonus_credits == Decimal("0.0000")
    assert starter.total_credits == starter.paid_credits


# --- the bonus grant (DB) -----------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(signup_router)
    application.include_router(topup_router)
    application.include_router(webhook_router)
    return application


def _client() -> AsyncClient:
    address = f"198.51.100.{uuid.uuid4().int % 250 + 1}"
    transport = ASGITransport(app=_app(), client=(address, 12345))
    return AsyncClient(transport=transport, base_url="http://api")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "self_serve_signup_enabled", True)
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_localonly")


async def _signed_up_user() -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    return f"dev:client:{user_id}"


async def _self_serve_tenant() -> tuple[uuid.UUID, str]:
    token = await _signed_up_user()
    body = {
        "business_name": "Sunrise Dental",
        "slug": f"sun-{uuid.uuid4().hex[:8]}",
        "vertical_template": "clinic",
        "language": "te-IN",
    }
    async with _client() as http:
        response = await http.post("/v1/auth/signup", headers=_headers(token), json=body)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["tenant_id"]), token


def _payment_id(tag: str) -> str:
    return f"pay_{tag}_{uuid.uuid4().hex[:12]}"


def _envelope(
    *, payment_id: str, tenant_id: uuid.UUID, amount: int, pack_id: str | None
) -> dict[str, Any]:
    notes: dict[str, str] = {payments.NOTES_TENANT_KEY: str(tenant_id)}
    if pack_id is not None:
        notes[payments.NOTES_PACK_KEY] = pack_id
    entity: dict[str, Any] = {
        "id": payment_id,
        "amount": amount,
        "currency": "INR",
        "status": "captured",
        "notes": notes,
    }
    return {"event": "payment.captured", "payload": {"payment": {"entity": entity}}}


def _sign(body: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body, separators=(",", ":")).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {payments.SIGNATURE_HEADER: signature, "Content-Type": "application/json"}


async def _ledger(tenant_id: uuid.UUID) -> list[tuple[str, Decimal, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT reason, delta, ref FROM credit_ledger WHERE tenant_id = :t "
                    "ORDER BY occurred_at, id"
                ),
                {"t": tenant_id},
            )
        ).all()
    return [(str(r[0]), Decimal(str(r[1])), r[2]) for r in rows]


async def test_a_pack_payment_grants_paid_and_bonus_credits() -> None:
    """The ₹2,999 growth pack: one paid `topup` (₹2,999) and one `bonus` (₹89.97), both
    keyed on the payment id, and a balance that reflects the sum."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("GROWTH")
    # ₹2,999 in paise.
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=299900, pack_id="growth")
    )

    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "credited"
    # Balance = paid + bonus = 2999 + 89.97 = 3088.97.
    assert response.json()["balance_inr"] == "3088.97"

    entries = await _ledger(tenant_id)
    assert entries == [
        ("topup", Decimal("2999.0000"), payment_id),
        ("bonus", Decimal("89.9700"), payment_id),
    ]


async def test_a_pack_bonus_is_granted_exactly_once_on_replay() -> None:
    """A redelivered pack payment credits paid+bonus once — the payment id is the key on
    both the `topup` and the `bonus` namespace."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("REPLAY")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=999900, pack_id="scale")
    )

    async with _client() as http:
        first = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        replay = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert first.json()["status"] == "credited"
    assert replay.json()["status"] == "duplicate"

    entries = await _ledger(tenant_id)
    # ₹9,999 paid + ₹499.95 bonus (5%), exactly one of each.
    assert entries == [
        ("topup", Decimal("9999.0000"), payment_id),
        ("bonus", Decimal("499.9500"), payment_id),
    ]


async def test_the_bonus_survives_a_direct_replay_via_the_ledger_ref() -> None:
    """Called directly (an ARQ retry or manual replay), the paid+bonus pair still lands
    once — the ledger `ref` under each reason is the arbiter, not the expiring inbox."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("DIRECT")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal("50000.00"),
        currency="INR",
        pack_id="max",
    )
    async with tenant_session(tenant_id) as session:
        first = await payments.credit_captured_payment(session, payment=payment)
    async with tenant_session(tenant_id) as session:
        second = await payments.credit_captured_payment(session, payment=payment)

    assert first.recorded is True
    assert first.bonus_inr == Decimal("4000.0000")  # 8% of 50000
    assert second.recorded is False
    assert await _ledger(tenant_id) == [
        ("topup", Decimal("50000.0000"), payment_id),
        ("bonus", Decimal("4000.0000"), payment_id),
    ]


async def test_a_direct_second_grant_of_a_pack_bonus_is_a_no_op() -> None:
    """The defense-in-depth guard inside `_grant_pack_bonus` itself.

    `credit_captured_payment` short-circuits on the paid `topup` replay (its own
    `find_topup` guard) and returns before it ever re-enters `_grant_pack_bonus`, so the
    replay tests above never exercise the bonus leg's OWN idempotency. This one does:
    it drives `_grant_pack_bonus` directly a second time — the state a manual replay or a
    future caller that bypasses the outer guard would produce — and asserts the second
    call finds the existing `bonus` row by ref and returns it, appending no second bonus
    ledger entry. Same check-then-write-under-lock discipline the paid leg uses, proven
    against the branch that carries it."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("BONUS-DIRECT")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal("50000.00"),
        currency="INR",
        pack_id="max",
    )
    pack = pack_by_id("max")
    assert pack is not None
    async with tenant_session(tenant_id) as session:
        first = await payments.credit_captured_payment(session, payment=payment)
    assert first.bonus_entry_id is not None
    assert first.bonus_inr == Decimal("4000.0000")  # 8% of 50000

    # A SECOND, DIRECT grant — the paid topup and the bonus both already exist. The outer
    # `credit_captured_payment` would never reach here (it short-circuits on the paid row),
    # so this is the only vehicle for the branch.
    async with tenant_session(tenant_id) as session:
        replay = await payments._grant_pack_bonus(
            session,
            payment=payment,
            pack=pack,
            paid_entry_id=first.entry_id,
            ip=None,
        )

    assert replay.recorded is True
    assert replay.bonus_entry_id == first.bonus_entry_id  # the existing row, not a new one
    assert replay.bonus_inr == Decimal("4000.0000")
    # Still exactly one topup and one bonus row — the second grant wrote nothing.
    assert await _ledger(tenant_id) == [
        ("topup", Decimal("50000.0000"), payment_id),
        ("bonus", Decimal("4000.0000"), payment_id),
    ]


async def test_a_plain_topup_grants_no_bonus() -> None:
    """No pack in the notes → one `topup` row and nothing else."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("PLAIN")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=250000, pack_id=None)
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.json()["status"] == "credited"
    assert await _ledger(tenant_id) == [("topup", Decimal("2500.0000"), payment_id)]


async def test_the_starter_pack_grants_no_bonus_row() -> None:
    """The 0%-bonus pack credits the paid amount and writes no ₹0 bonus row."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("STARTER")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=149900, pack_id="starter")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.json()["status"] == "credited"
    assert await _ledger(tenant_id) == [("topup", Decimal("1499.0000"), payment_id)]


async def test_an_unknown_pack_id_credits_the_payment_without_a_bonus() -> None:
    """A pack id this build no longer offers must not lose a real payment: the paid credit
    lands, and no bonus is invented for a pack the catalogue cannot price."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("GHOST")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=200000, pack_id="retired-2024")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.json()["status"] == "credited"
    assert await _ledger(tenant_id) == [("topup", Decimal("2000.0000"), payment_id)]


async def test_a_pack_bonus_is_invisible_to_another_tenant() -> None:
    """Bonus rows ride `credit_ledger`'s existing FORCEd RLS: a bonus written for one tenant
    is zero rows from another tenant's session."""
    tenant_a, _ = await _self_serve_tenant()
    tenant_b, _ = await _self_serve_tenant()
    payment_id = _payment_id("RLS")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_a,
        amount_inr=Decimal("9999.00"),
        currency="INR",
        pack_id="scale",
    )
    async with tenant_session(tenant_a) as session:
        await payments.credit_captured_payment(session, payment=payment)

    # Tenant A sees both rows; tenant B sees none of them.
    assert len(await _ledger(tenant_a)) == 2
    async with tenant_session(tenant_b) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE ref = :r AND reason = 'bonus'"),
                {"r": payment_id},
            )
        ).scalar_one()
    assert rows == 0


# --- the intent and the catalogue endpoint ------------------------------------


async def test_the_intent_prices_a_pack_from_the_catalogue() -> None:
    """Selecting a pack starts an intent whose amount comes from the catalogue (not the
    body) and whose notes carry the pack id through to the order."""
    tenant_id, token = await _self_serve_tenant()
    async with _client() as http:
        response = await http.post(
            "/v1/billing/topups/intent", headers=_headers(token), json={"pack_id": "pro"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["amount_inr"] == "24999.00"
    assert body["pack_id"] == "pro"
    assert body["notes"][payments.NOTES_PACK_KEY] == "pro"
    assert body["notes"][payments.NOTES_TENANT_KEY] == str(tenant_id)


async def test_the_intent_refuses_both_a_pack_and_an_amount() -> None:
    _, token = await _self_serve_tenant()
    async with _client() as http:
        both = await http.post(
            "/v1/billing/topups/intent",
            headers=_headers(token),
            json={"pack_id": "pro", "amount_inr": "1000.00"},
        )
        neither = await http.post("/v1/billing/topups/intent", headers=_headers(token), json={})
    assert both.status_code == 422, both.text
    assert neither.status_code == 422, neither.text


async def test_the_intent_refuses_an_unknown_pack() -> None:
    _, token = await _self_serve_tenant()
    async with _client() as http:
        response = await http.post(
            "/v1/billing/topups/intent", headers=_headers(token), json={"pack_id": "nope"}
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("unknown_credit_pack")


async def test_the_packs_endpoint_lists_the_catalogue_priced() -> None:
    _, token = await _self_serve_tenant()
    async with _client() as http:
        response = await http.get("/v1/billing/topups/packs", headers=_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    ids = [p["pack_id"] for p in body["packs"]]
    assert ids == [p.pack_id for p in PACK_CATALOGUE]
    # Money is a string on the wire (hard rule 7).
    for pack in body["packs"]:
        assert isinstance(pack["amount_inr"], str)
        assert isinstance(pack["effective_rate_inr_per_min"], str)
        assert isinstance(pack["total_credits"], str)
    # The starter pack has no bonus, so its effective rate equals the list rate beside it.
    starter = next(p for p in body["packs"] if p["pack_id"] == "starter")
    assert Decimal(starter["effective_rate_inr_per_min"]) == Decimal(body["list_rate_inr_per_min"])
    assert next(p for p in body["packs"] if p["best_value"])["pack_id"] == "max"
