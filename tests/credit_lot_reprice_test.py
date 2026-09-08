"""Selling credit a client ALREADY HOLDS at another pack's rates (plan §0 Q6).

A lot's terms are frozen for the life of its credit — `credit_lots_terms_frozen` refuses
any UPDATE that touches the two rates, the source or the pack — and that refusal IS the
promise the client was sold ("the rates shown when you paid apply to that purchase's credit
until it is spent"). So the promotion nobody applied at the till, and the rate negotiated
after the transfer landed, cannot be an edit. They are a CLOSE AND REPLACE: the original
lot closes at its own terms and a replacement opens carrying its remaining credit at the
new ones.

THREE PROPERTIES CARRY THE WHOLE FEATURE, and each has a test below that fails without it:

1. **No money moves.** `SUM(credits_remaining)` is unchanged across the pair (invariant
   §2.3.1) and the balance does not twitch. The ledger nonetheless gets a ZERO-DELTA
   `adjustment` marker, because `credit_lots.ledger_entry_id` is NOT NULL and the
   replacement must name an entry — the device migration `c9f3a71e58d2` used for the
   opening lots and for exactly this reason.
2. **The replacement inherits `opened_at`.** Consumption is FIFO by that column, so a
   replacement stamped with the current clock would silently move re-priced credit to the
   BACK of the client's queue: a lot bought in March would start being spent after one
   bought in June because an operator corrected its price.
3. **Both rows survive.** The closed one says what was sold; the open one says what is now
   promised. Neither is deleted and neither is edited.

**IT IS NOT THE TOP-UP'S `rates_of_pack_id`.** That field prices credit AS IT ARRIVES and
is the only instant it CAN be set there; this corrects a decision already made on credit
the client is holding. Two acts, two step-up strings, two audit actions — and the test
below that posts the same pack to both surfaces is what pins them apart.

Run: uv run pytest -q tests/credit_lot_reprice_test.py
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import lots as credit_lots
from apps.api.billing.credit_packs import pack_by_id
from apps.api.billing.credit_routes import lot_reprice_confirmation
from apps.api.billing.credit_routes import lots_router as credit_lots_router
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.lots import CallDemand, read_open_lots
from apps.api.billing.service import (
    LotRates,
    absorbed_calling_inr,
    charge_for_call,
    get_balance,
    lot_reprice_ref,
    reprice_lot,
)
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.credit_lots_helpers import lot_rows


#: BOTH routers on one app, deliberately: the wallet writes and the lot write are separate
#: surfaces on separate nouns, and a test that mounted only one could not assert that the
#: two step-up strings do not open each other's door.
def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    application.include_router(credit_lots_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _admin() -> str:
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
        name="Reprice Clinic",
        slug=f"rp-{uuid.uuid4().hex[:8]}",
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


async def _wallet_with_one_lot(http: AsyncClient, token: str, tenant_id: uuid.UUID) -> uuid.UUID:
    """₹6,000 recorded as a bank transfer — the free-amount rule sells it at the ₹5,000
    rung (₹5.00 / ₹7.00), which is the card position a re-price then moves off."""
    posted = await http.post(
        f"/v1/admin/tenants/{tenant_id}/credits",
        headers=_headers(token),
        json={"amount_inr": "6000.00", "payment_ref": f"UTR-{uuid.uuid4().hex[:8]}"},
    )
    assert posted.status_code == 200, posted.text
    lot_id: str = posted.json()["lot"]["lot_id"]
    return uuid.UUID(lot_id)


async def _balance(tenant_id: uuid.UUID) -> Decimal:
    async with tenant_session(tenant_id) as session:
        return (await get_balance(session, tenant_id=tenant_id)).amount_inr


async def test_a_reprice_closes_the_lot_and_opens_its_replacement_at_the_new_rates() -> None:
    """The whole shape in one pass: two rows, the credit moved across, the rates changed,
    and the client's balance untouched."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        before = await _balance(tenant_id)
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "founding client, agreed in week three"},
        )
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["recorded"] is True
    assert body["closed_lot_id"] == str(lot_id)
    assert body["credits_inr"] == "6000.00"
    assert body["ref"] == lot_reprice_ref(lot_id=lot_id, pack_id="max")

    rows = {row["id"]: row for row in await lot_rows(tenant_id)}
    assert len(rows) == 2, "close-and-replace, never an edit"
    closed = rows[lot_id]
    replacement = rows[uuid.UUID(body["lot"]["lot_id"])]

    # The closed row is the truthful record of what was ORIGINALLY sold. Its rates did not
    # move — the freeze trigger is what makes that a fact rather than an intention.
    assert closed["closed_at"] is not None
    assert closed["credits_remaining"] == Decimal("0.0000")
    assert (closed["sarvam_inr_per_min"], closed["cartesia_inr_per_min"]) == (
        Decimal("5.0000"),
        Decimal("7.0000"),
    )
    # The replacement carries the credit at the ₹50,000 pack's rates, under `override`,
    # naming the pack whose terms were borrowed — the field that answers "why is this
    # client's minute cheaper than the card" from the row itself.
    assert replacement["closed_at"] is None
    assert replacement["credits_remaining"] == Decimal("6000.0000")
    assert replacement["source"] == "override"
    assert replacement["pack_id"] is None, "the client did not buy that pack"
    assert replacement["override_of_pack_id"] == "max"
    assert (replacement["sarvam_inr_per_min"], replacement["cartesia_inr_per_min"]) == (
        Decimal("4.5000"),
        Decimal("6.0000"),
    )
    # NO MONEY MOVED, in either direction, and invariant §2.3.1 still holds.
    assert await _balance(tenant_id) == before
    assert closed["credits_remaining"] + replacement["credits_remaining"] == before


async def test_the_replacement_keeps_the_originals_place_in_the_spend_queue() -> None:
    """FIFO is `opened_at` (invariant §2.3.2). A replacement stamped NOW would be spent
    after every lot the client bought later — the order they were promised their money
    would go in, changed by an operator correcting a price."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        first = await _wallet_with_one_lot(http, token, tenant_id)
        # A SECOND, LATER purchase. Without the inheritance the replacement lands behind
        # this one and this test is the only thing that would ever have noticed.
        await _wallet_with_one_lot(http, token, tenant_id)
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{first}/override",
            headers=_headers(token, lot_reprice_confirmation(first)),
            json={"pack_id": "pro", "reason": "promotion nobody applied at the till"},
        )
    assert answer.status_code == 200, answer.text
    replacement = uuid.UUID(answer.json()["lot"]["lot_id"])
    async with tenant_session(tenant_id) as session:
        queue = await read_open_lots(session, tenant_id=tenant_id)
    assert next(lot.lot_id for lot in queue) == replacement, (
        "the re-priced credit must still be spent first"
    )


async def test_the_next_call_is_charged_at_the_replacements_rate() -> None:
    """The point of the whole feature, asserted where it lands: the client's next minute
    costs what they were promised, out of the lot the walk now finds."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "negotiated after the transfer landed"},
        )
    async with tenant_session(tenant_id) as session:
        charged = await charge_for_call(
            session,
            tenant_id=tenant_id,
            call_id=uuid.uuid4(),
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                fallback_rates=LotRates(Decimal("5.00"), Decimal("8.00")),
            ),
        )
    assert charged == Decimal("45.0000"), "10 minutes at the ₹50,000 pack's ₹4.50"


async def test_re_posting_the_same_reprice_changes_nothing() -> None:
    """Idempotent by the marker's own `ref`, enforced by
    `ux_credit_ledger_tenant_reason_ref` rather than by a reader's `if`. A double-clicked
    Save must not close the replacement it just opened."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        first = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "founding client"},
        )
        again = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "founding client"},
        )
    assert first.status_code == again.status_code == 200, again.text
    assert again.json()["recorded"] is False
    assert again.json()["lot"]["lot_id"] == first.json()["lot"]["lot_id"], (
        "the replay names the object the first click created, not a second one"
    )
    assert len(await lot_rows(tenant_id)) == 2, "no third lot"


async def test_a_reprice_needs_the_confirmation_bound_to_that_lot() -> None:
    """The step-up is bound to the LOT, so a header captured while looking at a ₹2,000 lot
    cannot be replayed against the ₹50,000 one beside it."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        other = await _wallet_with_one_lot(http, token, tenant_id)
        bare = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token),
            json={"pack_id": "max", "reason": "no confirmation at all"},
        )
        wrong_lot = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(other)),
            json={"pack_id": "max", "reason": "the other lot's header"},
        )
        # A PACK-bound header from the top-up surface is not this route's key either: the
        # two acts share a prefix and cannot open each other's door.
        wrong_shape = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, "override_lot_rates:max"),
            json={"pack_id": "max", "reason": "the purchase-time header"},
        )
    assert bare.status_code == 403, bare.text
    assert wrong_lot.status_code == 403, wrong_lot.text
    assert wrong_shape.status_code == 403, wrong_shape.text
    assert len(await lot_rows(tenant_id)) == 2, "nothing was re-priced"


async def test_a_lot_already_at_those_rates_is_refused_rather_than_re_opened() -> None:
    """It would be a valid close-and-replace producing an identical lot, a marker row and
    an audit entry recording a decision nobody made — and it is what an operator sees when
    they have picked the wrong lot."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        # ₹6,000 was already sold at the ₹5,000 (`growth`) rung's rates.
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "growth", "reason": "no change at all"},
        )
    assert answer.status_code == 422, answer.text
    assert answer.json()["type"].endswith("/lot_already_at_those_rates"), answer.text
    assert len(await lot_rows(tenant_id)) == 1


async def test_a_lot_whose_credit_is_all_spent_is_refused_with_a_sentence() -> None:
    """Re-pricing changes what the credit a client STILL HOLDS costs per minute; it cannot
    repay minutes already made. A 404 would send an operator looking for a lot they can
    see on their screen."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        async with tenant_session(tenant_id) as session:
            await charge_for_call(
                session,
                tenant_id=tenant_id,
                call_id=uuid.uuid4(),
                demand=CallDemand(
                    minutes=Decimal("1200"),  # ₹6,000 at ₹5.00 — the whole lot
                    voice_tier="sarvam",
                    fallback_rates=LotRates(Decimal("5.00"), Decimal("8.00")),
                ),
            )
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "too late"},
        )
    assert answer.status_code == 422, answer.text
    assert answer.json()["type"].endswith("/lot_is_spent"), answer.text


async def test_an_unknown_pack_is_refused_before_the_confirmation_is_read() -> None:
    """`record_topup`'s order and its reason: an operator who named a pack that does not
    exist should be told that, not told their header is wrong — which sends them to fix
    the header and meet the same refusal again."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token),
            json={"pack_id": "platinum", "reason": "a pack that does not exist"},
        )
    assert answer.status_code == 422, answer.text
    assert answer.json()["type"].endswith("/unknown_credit_pack"), answer.text


async def test_another_tenants_lot_is_not_visible_to_re_price() -> None:
    """RLS makes "no such lot" and "someone else's lot" one answer, deliberately."""
    token = await _admin()
    mine, theirs = await _tenant(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, theirs)
        answer = await http.post(
            f"/v1/admin/tenants/{mine}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "reaching across the wall"},
        )
    assert answer.status_code == 404, answer.text
    (untouched,) = await lot_rows(theirs)
    assert untouched["closed_at"] is None


async def test_the_marker_moves_no_money_and_says_where_the_lot_came_from() -> None:
    """The ledger row exists so the replacement has an entry to name, and for no other
    reason: zero delta, `balance_after` unchanged, and every fact of the decision on it."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        answer = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "founding client, agreed in week three"},
        )
    assert answer.status_code == 200, answer.text
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT delta, balance_after, reason, meta FROM credit_ledger "
                    "WHERE tenant_id = :t AND ref = :r"
                ),
                {"t": tenant_id, "r": answer.json()["ref"]},
            )
        ).one()
    delta, balance_after, reason, meta = row
    assert delta == Decimal("0.0000")
    assert balance_after == Decimal("6000.0000")
    assert reason == "adjustment"
    assert meta["kind"] == "lot_rate_override"
    assert meta["reason"] == "founding client, agreed in week three"
    # Rates as STRINGS on both sides of the change (hard rule 7), written out rather than
    # left to be looked up from today's card: the card moves and this decision does not.
    assert meta["previous_sarvam_inr_per_min"] == "5.0000"
    assert meta["sarvam_inr_per_min"] == "4.50"
    assert meta["rates_of_pack_id"] == "max"


async def test_the_reprice_is_audited_under_its_own_action() -> None:
    """ "Show me every below-card sale" must be one query. A re-price is a DIFFERENT act
    from a purchase-time override on a different object, so it has its own action name."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
        await http.post(
            f"/v1/admin/tenants/{tenant_id}/credit-lots/{lot_id}/override",
            headers=_headers(token, lot_reprice_confirmation(lot_id)),
            json={"pack_id": "max", "reason": "founding client"},
        )
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT actor_type, object_type, object_id FROM audit_log "
                    "WHERE action = 'credit.lot_rate_override' AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).one()
    # The SUMMARY is not a column — `compliance.audit.write_audit` sends it to the log
    # stream, because hashing a field the row does not carry would make the chain
    # unverifiable. What the row itself must say is WHO acted on WHICH object.
    assert found == ("admin", "credit_lots", str(lot_id))


async def test_a_lot_that_moved_under_the_reprice_is_a_conflict_not_a_silent_mint() -> None:
    """The CAS on `credits_remaining` is the backstop the advisory lock should make
    unreachable, and it is real rather than defensive: without it a call that spent part of
    this lot between the read and the write would move a STALE figure onto the replacement
    and mint or destroy credit. Driven by making the close fail, which is exactly what a
    lost race does."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
    pack = pack_by_id("max")
    assert pack is not None
    with pytest.MonkeyPatch.context() as patch:

        async def _lost_race(*_args: object, **_kwargs: object) -> bool:
            return False

        patch.setattr(credit_lots, "close_lot", _lost_race)
        with pytest.raises(ProblemError) as raised:
            async with tenant_session(tenant_id) as session:
                await reprice_lot(
                    session,
                    tenant_id=tenant_id,
                    lot_id=lot_id,
                    pack=pack,
                    reason="a call landed mid-flight",
                    operator_id=None,
                )
    assert raised.value.code == "credit_lots_contended"
    # NOTHING WAS MINTED: the transaction rolled back, so there is still one lot and it is
    # still open at its original terms.
    (only,) = await lot_rows(tenant_id)
    assert only["closed_at"] is None
    assert only["credits_remaining"] == Decimal("6000.0000")


async def test_a_reprice_with_no_operator_records_no_actor_on_the_marker() -> None:
    """`operator_id` is optional because the SERVICE is callable from a path that has no
    human behind it (a migration, a future automated correction). The key is then ABSENT
    rather than null — the tri-state a nullable would create is what `split_meta` avoids on
    the row beside it, and a `repriced_by: null` reads as "we do not know who", which is a
    different and worse claim than "nobody was asked"."""
    token, tenant_id = await _admin(), await _tenant()
    async with _client() as http:
        lot_id = await _wallet_with_one_lot(http, token, tenant_id)
    pack = pack_by_id("max")
    assert pack is not None
    async with tenant_session(tenant_id) as session:
        answer = await reprice_lot(
            session,
            tenant_id=tenant_id,
            lot_id=lot_id,
            pack=pack,
            reason="no human in this path",
            operator_id=None,
        )
        assert answer is not None
        meta = (
            await session.execute(
                text("SELECT meta FROM credit_ledger WHERE id = :i"),
                {"i": answer.ledger_entry_id},
            )
        ).scalar_one()
    assert "repriced_by" not in meta


def test_a_managed_trial_is_absorbed_at_the_plan_rungs_and_not_at_a_list_rate() -> None:
    """`absorbed_calling_inr`'s other branch. A managed tenant has no wallet, so there is
    nothing counterfactual about their calling except that it is not invoiced — the figure
    is the overage their plan would have charged, exactly as `calling_revenue_inr` answers
    it when the month is billed."""
    assert absorbed_calling_inr(
        plan_tier="managed",
        minutes=Decimal("120"),
        overage_cost_inr=Decimal("240.00"),
        llm_surcharge_inr=Decimal("18.00"),
        # NOT READ on this branch: a number nothing else here uses, so an answer that ever
        # moved with it would be unmistakable.
        self_serve_rate_inr_per_min=Decimal("999.00"),
    ) == Decimal("258.00")
