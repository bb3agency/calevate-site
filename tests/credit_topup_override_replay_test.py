"""RE-POSTING A PAYMENT MAY NOT RE-PRICE THE CREDIT IT ALREADY OPENED (D-547 Q6).

`lot_and_price_wire_test.py` proves the FIRST post of a below-card sale: which pack's
rates were borrowed, that the lot records the borrowing, and that the act is audited under
its own action. This file proves the second post — the half a double-clicked Save, an ARQ
retry or an operator re-keying a UTR actually reaches — and the two refusals in front of
the first one.

WHY THE REPLAY IS THE INTERESTING CASE. A lot's two rates are frozen the moment it opens
(`credit_lots_terms_frozen`), so a re-post carrying a DIFFERENT `rates_of_pack_id` is
asking for something the store cannot do. Answering it 200 — which is what an idempotent
route does by reflex — would tell an operator that the promise they just made to a client
is on the wallet when nothing on the wallet says so, and the client would be billed at the
card. So the route reads back what the lot actually carries and refuses with it.

THE FOUR SHAPES A REPLAY CAN HAVE, one test each:

1. no override at all — the ordinary re-post, which must not acquire a lot read;
2. the SAME pack — a true replay: 200, `recorded: false`, nothing written;
3. a DIFFERENT pack — `topup_override_conflict`, naming the pack the lot carries;
4. no lot at all behind the entry — a payment swallowed whole by an overdraft
   (`service.apply_credit_to_lots` opens no lot when the remainder is nil), which is a
   real wallet state and not a hypothetical: the refusal has to name "the standard card"
   rather than print a null.

The validator tests below it are the same subject one step earlier: an override with no
stated ground, and a ground with no override, never reach the store at all.

Run: uv run pytest -q tests/credit_topup_override_replay_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.credit_routes import (
    LotRepriceIn,
    TopUpIn,
    lot_rate_override_confirmation,
)
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.lots import CallDemand
from apps.api.billing.service import LotRates, record_usage_from_lots
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

# --- scaffolding (the `lot_and_price_wire_test` shape) --------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Replay Clinic",
        slug=f"replay-{uuid.uuid4().hex[:8]}",
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


async def _two_packs(http: AsyncClient, token: str, tenant_id: uuid.UUID) -> tuple[str, str]:
    """Two DIFFERENT pack ids off the card the console itself is offered.

    Read from `CreditsOut.override_packs` rather than typed here, for the reason the route
    publishes them at all: a pack ladder spelled twice is a ladder that drifts.
    """
    packs = (
        await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    ).json()["override_packs"]
    ordered = sorted(packs, key=lambda pack: Decimal(pack["sarvam_inr_per_min"]))
    assert len(ordered) >= 2, "the card must offer at least two rungs to borrow from"
    return str(ordered[0]["pack_id"]), str(ordered[-1]["pack_id"])


async def _entries(tenant_id: uuid.UUID, ref: str) -> list[tuple[str, Decimal]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT reason, delta FROM credit_ledger WHERE tenant_id = :t AND ref = :r"),
                {"t": tenant_id, "r": ref},
            )
        ).all()
    return [(str(row[0]), Decimal(str(row[1]))) for row in rows]


async def _lot_terms(tenant_id: uuid.UUID, entry_id: str) -> dict[str, Any] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT override_of_pack_id, sarvam_inr_per_min, cartesia_inr_per_min "
                    "FROM credit_lots WHERE ledger_entry_id = :eid"
                ),
                {"eid": entry_id},
            )
        ).first()
    if row is None:
        return None
    return {
        "override_of_pack_id": row[0],
        "sarvam_inr_per_min": Decimal(str(row[1])),
        "cartesia_inr_per_min": Decimal(str(row[2])),
    }


# --- 1: the ordinary re-post, which asks the lots nothing ------------------------------


async def test_a_replay_with_no_override_is_answered_without_reading_the_lot() -> None:
    """The common path stays the common path: a payment recorded at the card, re-posted,
    is the 200 this route has always given and credits nothing."""
    token, tenant_id = await _make_admin(), await _tenant()
    body = {"amount_inr": "2500.00", "payment_ref": "UTR-REPLAY-PLAIN"}
    async with _client() as http:
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=body
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=body
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False, "a replay records nothing"
    assert second.json()["entry_id"] == first.json()["entry_id"]
    assert second.json()["balance_inr"] == "2500.00", "the wallet did not move twice"
    assert await _entries(tenant_id, "UTR-REPLAY-PLAIN") == [("topup", Decimal("2500.0000"))]


# --- 2 and 3: the replay that carries an override --------------------------------------


async def test_replaying_an_override_at_the_same_pack_is_the_replay_it_looks_like() -> None:
    """The same promise, posted twice. It must answer the FIRST call's entry and lot — a
    double-clicked Save cannot show one lot and then a second one."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        pack, _other = await _two_packs(http, token, tenant_id)
        body = {
            "amount_inr": "5000.00",
            "payment_ref": "UTR-REPLAY-SAME",
            "rates_of_pack_id": pack,
            "override_reason": "founding-client promotion, agreed on the call",
        }
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(pack)),
            json=body,
        )
        second = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(pack)),
            json=body,
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    replayed = second.json()
    assert replayed["recorded"] is False
    assert replayed["entry_id"] == first.json()["entry_id"]
    assert replayed["lot"]["lot_id"] == first.json()["lot"]["lot_id"], (
        "a replay names the lot the first call opened, never a second one"
    )
    assert replayed["lot"]["override_of_pack_id"] == pack
    # ONE payment, ONE lot: the whole point of the reference being the key.
    assert await _entries(tenant_id, "UTR-REPLAY-SAME") == [("topup", Decimal("5000.0000"))]


async def test_replaying_an_override_at_a_different_pack_is_refused_with_the_pack_the_lot_carries() -> (  # noqa: E501
    None
):
    """THE GUARD ITSELF: a payment reference replayed with different rates.

    Rates are frozen when the lot opens, so this request cannot be honoured; 200 would tell
    the operator it had been. The refusal names BOTH packs — the one on the lot and the one
    asked for — because that pair is what decides what they do next, and it points at the
    only paths that can still keep the promise.
    """
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        cheap, dear = await _two_packs(http, token, tenant_id)
        body = {
            "amount_inr": "5000.00",
            "payment_ref": "UTR-REPLAY-DIFF",
            "rates_of_pack_id": cheap,
            "override_reason": "founding-client promotion, agreed on the call",
        }
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(cheap)),
            json=body,
        )
        conflicted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(dear)),
            json={**body, "rates_of_pack_id": dear},
        )

    assert first.status_code == 200, first.text
    assert conflicted.status_code == 409, conflicted.text
    problem = conflicted.json()
    assert problem["type"].endswith("topup_override_conflict")
    assert cheap in problem["detail"], "it names the rates the credit is actually priced at"
    assert dear in problem["detail"], "and the rates that were asked for"
    assert "fresh payment reference" in problem["remediation"], (
        "the operator is sent to a path that can still keep the promise"
    )

    # NOTHING MOVED. The refusal is worthless if the second post half-applied.
    assert await _entries(tenant_id, "UTR-REPLAY-DIFF") == [("topup", Decimal("5000.0000"))]
    terms = await _lot_terms(tenant_id, first.json()["entry_id"])
    assert terms is not None
    assert terms["override_of_pack_id"] == cheap, "the frozen terms are still the frozen terms"
    assert Decimal(first.json()["lot"]["sarvam_inr_per_min"]) == terms["sarvam_inr_per_min"]


# --- 4: the entry that opened no lot ---------------------------------------------------


async def test_an_override_replayed_onto_a_payment_that_opened_no_lot_names_the_standard_card() -> (
    None
):
    """A payment entirely swallowed by an overdraft opens NO lot (`apply_credit_to_lots`
    returns `lot_id=None` when the remainder is nil), so there is no row to read the terms
    off. The refusal must still be a sentence: "the standard card" rather than a null
    printed into the middle of it, because a null there reads as a bug and tells the
    operator nothing about what the client is being charged.
    """
    token, tenant_id = await _make_admin(), await _tenant()
    # Drive the wallet negative the way a real one goes negative: minutes talked with no
    # lot to pay for them, priced at the caller's fallback (₹5/min x 100 = -₹500).
    #
    # The payment below repays that debt EXACTLY, which is the shape that reaches
    # `apply_credit_to_lots` with nothing left over. A PART payment now works too — see
    # `test_a_part_payment_against_arrears_is_recorded_rather_than_refused` below, which is
    # the defect this file surfaced: `record_entry` used to refuse any top-up that left the
    # balance still negative, so money that had arrived could not be recorded.
    async with tenant_session(tenant_id) as session:
        await record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref="call:overdraft-1",
            demand=CallDemand(
                minutes=Decimal("100"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("8.00")),
            ),
            allow_negative=True,
        )

    async with _client() as http:
        cheap, dear = await _two_packs(http, token, tenant_id)
        body = {
            "amount_inr": "500.00",
            "payment_ref": "UTR-REPLAY-NOLOT",
            "rates_of_pack_id": cheap,
            "override_reason": "negotiated rate, part payment against the arrears",
        }
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(cheap)),
            json=body,
        )
        conflicted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(dear)),
            json={**body, "rates_of_pack_id": dear},
        )

    assert first.status_code == 200, first.text
    assert first.json()["lot"] is None, "the whole payment repaid the overdraft"
    assert await _lot_terms(tenant_id, first.json()["entry_id"]) is None

    assert conflicted.status_code == 409, conflicted.text
    problem = conflicted.json()
    assert problem["type"].endswith("topup_override_conflict")
    assert "the standard card" in problem["detail"], (
        "a missing lot is described in words, never as a null in the sentence"
    )
    assert dear in problem["detail"]
    assert await _entries(tenant_id, "UTR-REPLAY-NOLOT") == [("topup", Decimal("500.0000"))]


# --- the validators in front of all of it ---------------------------------------------


def test_an_explicit_null_reason_is_an_ordinary_topup_and_not_a_refusal() -> None:
    """A console that always sends the field sends `"override_reason": null` for every
    ordinary payment. That is not an empty reason — it is no reason offered, which is what
    a top-up at the card IS, and it must validate."""
    payload = TopUpIn.model_validate(
        {
            "amount_inr": "2500.00",
            "payment_ref": "UTR-NULL-REASON",
            "rates_of_pack_id": None,
            "override_reason": None,
        }
    )
    assert payload.override_reason is None
    assert payload.rates_of_pack_id is None


@pytest.mark.parametrize("reason", ["   ", "  ab  ", "\t\n \n"])
def test_a_reason_that_is_only_padding_cannot_stand_in_for_saying_why(reason: str) -> None:
    """`min_length=3` counts the padding; this counts the words. A below-card sale carrying
    `"  "` as its ground is exactly the row an auditor stops on, and it would read as
    explained on every screen that renders the field."""
    with pytest.raises(ValidationError) as raised:
        TopUpIn.model_validate(
            {
                "amount_inr": "5000.00",
                "payment_ref": "UTR-PADDED",
                "rates_of_pack_id": "scale",
                "override_reason": reason,
            }
        )
    assert "say why this purchase is being sold at another pack's rates" in str(raised.value)


def test_a_reason_with_no_pack_is_refused_because_nothing_would_ever_say_so() -> None:
    """The worse of the two all-or-nothing failures, and the reason the check runs in both
    directions: an operator who believes they applied an override and did not gets a lot at
    the CARD rates with nothing on it — not the lot, not the ledger meta, not the audit
    action — recording that they meant otherwise. The client is then billed at the card
    against a promise that was made out loud."""
    with pytest.raises(ValidationError) as raised:
        TopUpIn.model_validate(
            {
                "amount_inr": "5000.00",
                "payment_ref": "UTR-NO-PACK",
                "override_reason": "founding-client promotion",
            }
        )
    assert "override_reason means nothing without rates_of_pack_id" in str(raised.value)

    # The sibling direction, asserted beside it so the pair cannot drift apart.
    with pytest.raises(ValidationError) as unexplained:
        TopUpIn.model_validate(
            {
                "amount_inr": "5000.00",
                "payment_ref": "UTR-NO-REASON",
                "rates_of_pack_id": "scale",
            }
        )
    assert "override_reason is required when rates_of_pack_id is set" in str(unexplained.value)


@pytest.mark.parametrize("reason", ["   ", "  ab  "])
def test_a_reprice_reason_that_is_only_padding_is_refused_in_its_own_words(reason: str) -> None:
    """The re-price surface carries its own sentence because it is its own act: correcting
    the price of credit a client is ALREADY HOLDING, not pricing credit as it arrives. An
    operator sent the top-up's sentence here would go looking for a purchase to fix."""
    with pytest.raises(ValidationError) as raised:
        LotRepriceIn.model_validate({"pack_id": "scale", "reason": reason})
    assert "say why this credit is being re-priced" in str(raised.value)


async def test_a_part_payment_against_arrears_is_recorded_rather_than_refused() -> None:
    """MONEY THAT ARRIVED CAN ALWAYS BE RECORDED, even when it does not clear the debt.

    `record_entry` refuses an entry that leaves the balance below zero, and it did so
    REGARDLESS OF THE DELTA'S SIGN — so recording a part payment against an overdrawn
    wallet raised `insufficient_credits`, telling an operator the client was short of
    credit as the reason they could not record the client PAYING. A positive delta cannot
    make a balance worse, so the guard protected nothing on this path; it belongs to the
    debit path, where it is the whole point.

    The wallet stays negative afterwards and that is correct: a part payment is a part
    payment. What must not happen is the payment being lost.
    """
    token, tenant_id = await _make_admin(), await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref="call:arrears-1",
            demand=CallDemand(
                minutes=Decimal("100"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("8.00")),
            ),
            allow_negative=True,
        )

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            json={"amount_inr": "100.00", "payment_ref": "neft-part-1"},
            headers=_headers(token),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recorded"] is True
    # Still owing 400: the debt shrank by exactly what was paid, and nothing was invented.
    assert Decimal(body["balance_inr"]) == Decimal("-400.00")
    # No lot: every rupee went to the arrears, so there is no remainder to open one with.
    assert body["lot"] is None
