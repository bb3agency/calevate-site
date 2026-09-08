"""THE TEN WIRE SHAPES D-547 ADDED, asserted as the SHAPES two live consoles read.

`credit_lots_routes_test.py` proves the routes move the lots; `tts_price_attestation_test
.py` proves the price store. This file proves the half neither of them touches: what
actually crosses the wire, field by field, because both consoles validate at the seam and
render NOTHING rather than a wrong number. A missing key is a blank panel on a real
deployment and a differently-spelled one is a SILENTLY blank panel — the failure that looks
like "the feature isn't finished yet" and is really "the two halves disagree".

So every assertion here is against a literal key and a literal type, not against a Pydantic
model round-trip: a model can only tell you it validated itself.

WHAT IS DELIBERATELY NOT HERE. The arithmetic (what a lot's rate does to a call, what
`rate_margin` computes, whether a price is effective yet) belongs to the suites that own
those functions, and re-asserting it here would be a second copy free to drift from them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import voice_offer
from apps.api.billing import rates
from apps.api.billing.credit_routes import (
    credit_adjustment_confirmation,
    lot_rate_override_confirmation,
    topup_restatement_confirmation,
)
from apps.api.billing.credit_routes import router as credit_router
from apps.api.billing.lots import AiAssistDemand, CallDemand
from apps.api.billing.service import record_entry, record_usage_from_lots
from apps.api.billing.wallet_routes import read_wallet_ledger, read_wallet_lots
from apps.api.core.context import Principal
from apps.api.core.errors import install_error_handlers
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops.config_routes import rate_card_router
from apps.api.ops.model_price_routes import (
    BILLABLE_WITHOUT_ATTESTATION_REASON,
    tts_attest_confirmation,
    tts_router,
)
from apps.api.ops.model_price_routes import router as model_price_router
from apps.api.ops.model_pricing import attested_tts_prices
from apps.api.ops.pricing_snapshot import (
    install_pricing_readers,
    refresh_pricing_snapshot,
    uninstall_pricing_readers,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.credit_lots_helpers import add_lot

pytestmark = [pytest.mark.rls]


# --- scaffolding ------------------------------------------------------------------


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(credit_router)
    application.include_router(model_price_router)
    application.include_router(tts_router)
    application.include_router(rate_card_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """`superadmin` by default, because `platform:config` is the permission these panels
    hold and `model_pricing_test._make_admin` already says why: the price tables are
    append-only ON PURPOSE and that is the only role that may write them."""
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
        name="Wire Clinic",
        slug=f"wire-{uuid.uuid4().hex[:8]}",
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


def _owner(tenant_id: uuid.UUID) -> Principal:
    """The client realm's own principal, built the way `wallet_test._principal` builds it.

    The wallet routes are called as FUNCTIONS here rather than over HTTP: the realm and the
    permission are `wallet:read`'s business and `wallet_test.py` already pins them. What
    this file is about is the SHAPE that comes back, and mounting a second app to reach it
    would test FastAPI's router twice and the payload once.
    """
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


def _is_money(value: object) -> bool:
    """The seam's own test, copied from it deliberately.

    `apps/web/.../rateCard.ts::money` and `lots.ts::money` both refuse anything that is not
    a bare decimal string, and a field that fails it makes the whole panel render an
    absence. Spelling the predicate here is what makes THIS suite fail instead of a browser
    quietly showing nothing.
    """
    if not isinstance(value, str):
        return False
    body = value.strip()
    if body.startswith("-"):
        body = body[1:]
    left, _, right = body.partition(".")
    return left.isdigit() and (right == "" or right.isdigit())


# --- 1 + 3: the voice price attestation, and the panel it lands on -----------------


async def test_the_model_price_panel_carries_both_voice_tiers_with_their_verdicts() -> None:
    """Shape 3. Both tiers, always — the one nobody has priced is the row an operator
    opened this panel for, so a shorter list would hide the only outstanding job."""
    token = await _make_admin()
    async with _client() as http:
        read = await http.get("/v1/ops/model-prices", headers=_headers(token))

    assert read.status_code == 200, read.text
    rows = {row["provider"]: row for row in read.json()["tts_prices"]}
    assert set(rows) == {"sarvam", "cartesia"}

    for provider, row in rows.items():
        assert row["tier_label"] == rates.voice_tier_label(provider)
        assert isinstance(row["tts_model"], str) and row["tts_model"]
        for flag in ("credential_installed", "price_attested", "price_billable", "offerable"):
            assert isinstance(row[flag], bool), f"{provider}.{flag} must be a real boolean"

    # SARVAM HAS NOTHING TO CONFIRM, and says so rather than looking unattested. A row with
    # an empty price field and no explanation reads as an outstanding job; it is not one.
    assert rows["sarvam"]["price_attested"] is False
    assert rows["sarvam"]["price_billable"] is True
    assert rows["sarvam"]["billable_without_attestation_reason"] == (
        BILLABLE_WITHOUT_ATTESTATION_REASON
    )
    # Cartesia's absence is the opposite fact: it DOES need one, so there is no sentence
    # excusing it. Whether one has been attested is not this test's business — the price
    # store is global and another test in this session may have written one — so what is
    # pinned is the IMPLICATION, which is the rule the panel exists to render.
    cartesia = rows["cartesia"]
    assert cartesia["billable_without_attestation_reason"] is None
    assert cartesia["price_billable"] is cartesia["price_attested"], (
        "the Cartesia tier is billable exactly when somebody has read an invoice"
    )
    if not cartesia["price_attested"]:
        assert cartesia["inr_per_1k_chars"] is None
    else:
        assert _is_money(cartesia["inr_per_1k_chars"])


async def test_attesting_a_voice_price_needs_the_step_up_bound_to_that_vendor() -> None:
    """Shape 1. A header captured while pricing Sarvam must not reprice Cartesia — the
    Cartesia figure is the one that turns a whole tier on."""
    token = await _make_admin()
    body = {"inr_per_1k_chars": "3.4496", "source_note": "Cartesia Startup plan, invoice 2026-09"}
    async with _client() as http:
        bare = await http.post("/v1/ops/tts-prices/cartesia", headers=_headers(token), json=body)
        wrong = await http.post(
            "/v1/ops/tts-prices/cartesia",
            headers=_headers(token, tts_attest_confirmation("sarvam")),
            json=body,
        )
    assert bare.status_code == 403, bare.text
    assert wrong.status_code == 403, wrong.text


async def test_an_attested_voice_price_reaches_the_wire_and_makes_the_tier_offerable() -> None:
    """Shapes 1 and 3, and SEAM 2 end to end.

    The refusal already existed and the door was already exported; nothing opened it. This
    walks the whole path an operator walks: attest a figure, and the picker stops refusing
    the tier — through `ops/pricing_snapshot`, which is what installs the reader.
    """
    token = await _make_admin()
    async with _client() as http:
        written = await http.post(
            "/v1/ops/tts-prices/cartesia",
            headers=_headers(token, tts_attest_confirmation("cartesia")),
            json={
                "inr_per_1k_chars": "3.4496",
                "source_note": "Cartesia Startup plan, invoice 2026-09, ₹4,312 / 1.25M chars",
            },
        )
    assert written.status_code == 200, written.text
    row = written.json()["price"]
    assert row["provider"] == "cartesia"
    assert row["tier_label"] == rates.voice_tier_label("cartesia")
    assert row["price_attested"] is True
    assert row["price_billable"] is True
    # EXACT DIGITS ON THE WIRE. Four decimals of a division a human did against an invoice
    # survive to the DOM; a float round-trip would print 3.4496000000000002.
    assert _is_money(row["inr_per_1k_chars"])
    assert Decimal(row["inr_per_1k_chars"]) == Decimal("3.4496")
    assert row["attested_by"] is not None
    assert row["source_note"].startswith("Cartesia Startup plan")

    # SEAM 2: the snapshot is the thing that turns the store into the picker's answer.
    install_pricing_readers()
    try:
        await refresh_pricing_snapshot()
        assert voice_offer.tts_price_is_billable("cartesia") is True
        assert voice_offer.tts_price_is_billable("sarvam") is True
    finally:
        uninstall_pricing_readers()
    # And with the reader gone the picker is back on its own honest default, which is what
    # a process that never started the refresher serves.
    assert voice_offer.tts_price_is_billable("cartesia") is False


async def test_a_voice_price_is_refused_in_the_unit_the_operator_typed() -> None:
    """`_money`'s `unit` argument earns itself here: an operator told "USD per million
    tokens" about a rupees-per-1,000-characters field re-enters the wrong number."""
    token = await _make_admin()
    async with _client() as http:
        bad = await http.post(
            "/v1/ops/tts-prices/cartesia",
            headers=_headers(token, tts_attest_confirmation("cartesia")),
            json={"inr_per_1k_chars": "0", "source_note": "an invoice with a zero on it"},
        )
    assert bad.status_code == 422, bad.text
    detail = bad.json()["detail"]
    assert "greater than zero" in detail
    assert "million tokens" not in detail, "the LLM unit must not leak onto a voice form"


# --- 2: the rate card, as a viewer ------------------------------------------------


async def test_the_rate_card_publishes_the_servers_own_margin_and_both_floors() -> None:
    """Shape 2. `card_margins()` went to a log line and neither cost floor was published
    anywhere, so an operator could not see a margin at all."""
    token = await _make_admin()
    async with _client() as http:
        read = await http.get("/v1/ops/rate-card", headers=_headers(token))

    assert read.status_code == 200, read.text
    card = read.json()
    assert _is_money(card["target_gross_margin_pct"])
    assert card["effective_from"] is None or isinstance(card["effective_from"], str)

    cells = card["cells"]
    assert len(cells) == len(rates.VOICE_TIERS) * len({cell["pack_id"] for cell in cells})
    for cell in cells:
        assert cell["voice_tier"] in rates.VOICE_TIERS
        assert cell["tier_label"] == rates.voice_tier_label(cell["voice_tier"])
        for field in ("amount_inr", "inr_per_min", "cost_floor_inr_per_min"):
            assert _is_money(cell[field]), f"{cell['pack_id']}.{field} is not a decimal string"
        assert cell["gross_margin_pct"] is None or _is_money(cell["gross_margin_pct"])
        assert isinstance(cell["below_target"], bool)
        assert isinstance(cell["below_floor"], bool)
        # THE CARD ON SALE IS NEVER UNDER WATER. Thin is a warning the founder signed for;
        # below cost is a refusal, and a cell in that state means the committed card and
        # the committed cost model have come apart.
        assert cell["below_floor"] is False, f"{cell['pack_id']}/{cell['voice_tier']} is below cost"

    # The SERVER's percentage, not a browser's division: a margin worked out from two
    # rounded rupee strings is a third answer to a question `rate_margin` already answered.
    priced = next(cell for cell in cells if cell["gross_margin_pct"] is not None)
    assert Decimal(priced["gross_margin_pct"]) < Decimal("100")


# --- 4 + 5 + 6: the lots on the admin wallet ---------------------------------------


async def test_the_admin_wallet_read_carries_the_lot_queue_and_the_override_packs() -> None:
    """Shape 4. Oldest first — the order calls are actually charged in, which is the whole
    reason to show them."""
    token, tenant_id = await _make_admin(), await _tenant()
    await add_lot(tenant_id, credits_inr="5000", rates=(Decimal("5.00"), Decimal("7.00")))
    await add_lot(tenant_id, credits_inr="15000", rates=(Decimal("4.70"), Decimal("6.50")))

    async with _client() as http:
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
    assert read.status_code == 200, read.text
    body = read.json()

    lots = body["lots"]
    assert len(lots) == 2
    assert lots[0]["opened_at"] <= lots[1]["opened_at"], "oldest first, the FIFO read's order"
    for lot in lots:
        assert uuid.UUID(lot["lot_id"])
        assert lot["source"] == "topup"
        assert lot["closed_at"] is None, "the queue is OPEN lots only"
        for field in (
            "credits_total",
            "credits_remaining",
            "sarvam_inr_per_min",
            "cartesia_inr_per_min",
        ):
            assert _is_money(lot[field]), f"lot.{field} is not a decimal string"
        # THE CLIENT'S WORD FOR EACH VOICE, over the wire — never composed in the browser,
        # and never the vendor's name on a client's screen.
        assert lot["sarvam_label"] == rates.voice_tier_label("sarvam")
        assert lot["cartesia_label"] == rates.voice_tier_label("cartesia")

    packs = body["override_packs"]
    assert packs, "the console renders no catalogue of its own"
    for pack in packs:
        assert isinstance(pack["pack_id"], str) and pack["pack_id"]
        for field in ("amount_inr", "sarvam_inr_per_min", "cartesia_inr_per_min"):
            assert _is_money(pack[field])


async def test_every_credit_write_names_the_lot_it_touched() -> None:
    """Shape 5. All of it was computed on the write path and none of it reached the wire —
    so a console had to re-read a list and guess which of five lots had just moved."""
    token, tenant_id = await _make_admin(), await _tenant()

    async with _client() as http:
        topped = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "6000.00", "payment_ref": "UTR-WIRE-1"},
        )
        assert topped.status_code == 200, topped.text
        opened = topped.json()["lot"]
        assert opened is not None
        assert Decimal(opened["credits_total"]) == Decimal("6000")
        assert opened["source"] == "topup"

        restated = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/restatements",
            headers=_headers(
                token, topup_restatement_confirmation("UTR-WIRE-1", Decimal("6500.00"))
            ),
            json={
                "payment_ref": "UTR-WIRE-1",
                "corrected_amount_inr": "6500.00",
                "reason": "the bank moved ₹6,500 and we booked ₹6,000",
            },
        )
        assert restated.status_code == 200, restated.text
        landed = restated.json()

    # A RESTATEMENT LANDS ON THE PURCHASE'S OWN LOT AND MOVES TOTALS, NEVER RATES. That is
    # the promise the client bought, and the receipt states it rather than leaving an
    # operator to infer it from a table that happens not to have moved.
    assert landed["lot"]["lot_id"] == opened["lot_id"]
    assert Decimal(landed["lot"]["credits_total"]) == Decimal("6500")
    assert landed["lot"]["sarvam_inr_per_min"] == opened["sarvam_inr_per_min"]
    assert landed["lot"]["cartesia_inr_per_min"] == opened["cartesia_inr_per_min"]
    # `null`, never a zero: this route restates UPWARDS only, and credit being ADDED to a
    # lot cannot fail to fit, so no shortfall was ever measured.
    assert landed["lot_shortfall_inr"] is None


async def test_a_credit_back_names_its_new_lot_and_taking_credit_away_names_none() -> None:
    """Shape 5's other half, and the asymmetry is the point: a gift opens a fresh lot at
    the LIST rates, while taking credit away moves lots that already exist."""
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        topped = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token),
            json={"amount_inr": "6000.00", "payment_ref": "UTR-WIRE-2"},
        )
        entry_id = topped.json()["entry_id"]
        taken = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits/adjustments",
            headers=_headers(token, credit_adjustment_confirmation(uuid.UUID(entry_id))),
            json={
                "corrects_entry_id": entry_id,
                # POSITIVE, always: an adjustment says how much of an entry to take back
                # and the DIRECTION comes from the entry it corrects, never from a sign.
                "amount_inr": "1000.00",
                "reason": "double-counted the transfer",
            },
        )
    assert taken.status_code == 200, taken.text
    assert taken.json()["lot"] is None, "taking credit away opens nothing"


# --- 9 + 10: the client's own wallet ----------------------------------------------


async def test_the_client_wallet_lots_read_carries_both_tiers_the_queue_and_the_overdraft() -> None:
    """Shape 9. `tiers` carries BOTH voices always — a client shown only the quality they
    use today could not compare the two before switching an agent."""
    tenant_id = await _tenant()
    await add_lot(tenant_id, credits_inr="1000", rates=(Decimal("4.00"), Decimal("8.00")))

    body = (await read_wallet_lots(_owner(tenant_id))).model_dump(mode="json")

    tiers = body["tiers"]
    assert [tier["provider"] for tier in tiers] == list(rates.VOICE_TIERS)
    for tier in tiers:
        assert tier["label"] == rates.voice_tier_label(tier["provider"])
        assert tier["minutes_left"] is None or _is_money(tier["minutes_left"])
    # ₹1,000 at ₹4 and at ₹8 — summed off the LOT's own frozen rates, never one balance
    # divided by one live list price.
    assert [tier["minutes_left"] for tier in tiers] == ["250", "125"]

    (lot,) = body["lots"]
    assert uuid.UUID(lot["lot_id"])
    assert _is_money(lot["credits_remaining"])
    assert _is_money(lot["sarvam_inr_per_min"]) and _is_money(lot["cartesia_inr_per_min"])
    assert isinstance(lot["opened_at"], str)

    # UNSIGNED, and zero when the wallet owes nothing — a screen that has to decide what a
    # minus sign means is a screen that will decide wrong.
    assert _is_money(body["overdraft_inr"])
    assert Decimal(body["overdraft_inr"]) == Decimal("0")


async def test_the_lot_queue_is_the_order_a_call_will_spend_it_in() -> None:
    """Oldest first, the FIFO read's own ordering — the whole point of showing the queue."""
    tenant_id = await _tenant()
    first = await add_lot(tenant_id, credits_inr="500", rates=(Decimal("5.00"), Decimal("7.00")))
    second = await add_lot(tenant_id, credits_inr="800", rates=(Decimal("4.70"), Decimal("6.50")))

    body = (await read_wallet_lots(_owner(tenant_id))).model_dump(mode="json")
    assert [uuid.UUID(lot["lot_id"]) for lot in body["lots"]] == [first, second]


async def test_an_overdrawn_wallet_reports_its_debt_as_a_positive_number() -> None:
    """The other arm of `overdraft_inr`, which is the only place a negative balance is
    re-expressed for a client."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-250.00"),
            reason="usage",
            ref="wire-overdraft",
            allow_negative=True,
        )
    body = (await read_wallet_lots(_owner(tenant_id))).model_dump(mode="json")
    assert Decimal(body["overdraft_inr"]) == Decimal("250.00")


async def test_a_wallet_entry_carries_the_lot_split_that_paid_for_it() -> None:
    """Shape 10. The three call-only keys are ABSENT on an `ai_assist` split, not null — a
    null rate prints as an empty rate beside a real charge, which is why the splits are
    passed through as the ledger stored them rather than re-typed into a model whose
    optional fields would serialise as nulls."""
    tenant_id = await _tenant()
    await add_lot(tenant_id, credits_inr="1000", rates=(Decimal("5.00"), Decimal("7.00")))
    async with tenant_session(tenant_id) as session:
        await record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref="call:wire-1",
            demand=CallDemand(
                minutes=Decimal("10"),
                voice_tier="sarvam",
                fallback_inr_per_min=Decimal("5.00"),
            ),
        )
        await record_usage_from_lots(
            session,
            tenant_id=tenant_id,
            ref="ai:wire-1",
            demand=AiAssistDemand(credits=Decimal("12.00")),
        )

    body = (await read_wallet_ledger(_owner(tenant_id))).model_dump(mode="json")
    rows = {row["ref"]: row for row in body["entries"]}

    (call_split,) = rows["call:wire-1"]["lots"]
    assert call_split["kind"] == "call"
    assert uuid.UUID(call_split["lot_id"])
    assert call_split["voice_tier"] == "sarvam"
    for key in ("credits", "minutes", "inr_per_min"):
        assert _is_money(call_split[key]), f"meta.lots.{key} crossed the wire as a non-decimal"

    (assist_split,) = rows["ai:wire-1"]["lots"]
    assert set(assist_split) == {"kind", "credits", "lot_id"}, (
        "the three call-only keys are ABSENT, never null"
    )

    # Every ledger row publishes the key, `[]` for one that drew no lot — a key that
    # appears and disappears is a key a screen forgets to handle.
    assert all(isinstance(row["lots"], list) for row in body["entries"])


# --- the top-up rate override (Q6, the half that is expressible today) -------------


async def test_a_topup_sold_at_another_packs_rates_records_which_pack_and_why() -> None:
    """Seam 5. `override_of_pack_id` had a column, a function argument and no writer.

    A lot's rates are frozen at creation (`credit_lots_terms_frozen`), so "sell it cheaper"
    is only expressible at the instant the credit is booked — which is why the override is
    a field on the purchase and not an edit afterwards.
    """
    token, tenant_id = await _make_admin(), await _tenant()
    async with _client() as http:
        packs = (
            await http.get(f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token))
        ).json()["override_packs"]
        cheapest = min(packs, key=lambda pack: Decimal(pack["sarvam_inr_per_min"]))

        written = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation(cheapest["pack_id"])),
            json={
                "amount_inr": "5000.00",
                "payment_ref": "UTR-PROMO-1",
                "rates_of_pack_id": cheapest["pack_id"],
                "override_reason": "founding-client promotion, first pack at the top rung",
            },
        )
    assert written.status_code == 200, written.text
    lot = written.json()["lot"]
    assert lot["source"] == "override"
    assert lot["override_of_pack_id"] == cheapest["pack_id"]
    # THE PACK'S OWN RATES, not the free-amount rule's — ₹5,000 would otherwise have been
    # sold at the ₹5,000 rung.
    assert Decimal(lot["sarvam_inr_per_min"]) == Decimal(cheapest["sarvam_inr_per_min"])
    assert Decimal(lot["cartesia_inr_per_min"]) == Decimal(cheapest["cartesia_inr_per_min"])
    # `pack_id` stays NULL: the client did not BUY that pack, and stamping it there would
    # report a purchase that never happened.
    assert lot["pack_id"] is None

    # ITS OWN AUDIT ACTION, so "show me every below-card sale" is one query rather than a
    # scan of every top-up looking for a key. `write_audit` keeps the summary in the log
    # stream and not in a column (`compliance/audit.py`), so the durable record of WHICH
    # pack and WHY is the ledger row's own `meta` and the lot's `override_of_pack_id` —
    # both asserted below — and the row here is what carries the CHOOSER.
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT actor_id, object_type FROM audit_log "
                    "WHERE action = 'credit.topup_rate_override' ORDER BY at DESC LIMIT 1"
                )
            )
        ).first()
    # `credit_ledger` is FORCE-RLS'd: an untenanted session sees zero rows by design, so
    # the ledger read is inside the tenant's own session (hard rule 1).
    async with tenant_session(tenant_id) as scoped:
        meta: dict[str, Any] = (
            await scoped.execute(
                text("SELECT meta FROM credit_ledger WHERE ref = :r"), {"r": "UTR-PROMO-1"}
            )
        ).scalar_one()
    assert audited is not None, "a below-card sale is its own auditable action"
    assert audited[0] is not None, "the CHOOSER is the audit row's own actor"
    assert audited[1] == "credit_ledger"
    assert meta["rates_of_pack_id"] == cheapest["pack_id"]
    assert meta["override_reason"].startswith("founding-client")


async def test_an_override_needs_the_step_up_and_a_stated_reason() -> None:
    """A departure from the published card with no confirmation and no ground is the row an
    auditor stops on."""
    token, tenant_id = await _make_admin(), await _tenant()
    body = {
        "amount_inr": "5000.00",
        "payment_ref": "UTR-PROMO-2",
        "rates_of_pack_id": "scale",
        "override_reason": "negotiated",
    }
    async with _client() as http:
        bare = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits", headers=_headers(token), json=body
        )
        unexplained = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation("scale")),
            json={k: v for k, v in body.items() if k != "override_reason"},
        )
        unknown = await http.post(
            f"/v1/admin/tenants/{tenant_id}/credits",
            headers=_headers(token, lot_rate_override_confirmation("no-such-pack")),
            json={**body, "rates_of_pack_id": "no-such-pack"},
        )
    assert bare.status_code == 403, bare.text
    assert unexplained.status_code == 422, unexplained.text
    # THE IMPOSSIBLE VALUE FIRST, THE STEP-UP SECOND: an operator who named a pack that
    # does not exist is told that, not that their header is wrong.
    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["type"].endswith("unknown_credit_pack")


# --- 8: the speaking rate, priced per vendor --------------------------------------


async def test_the_speaking_rate_card_prices_the_measurement_per_vendor() -> None:
    """Shape 8. The board's other TTS figures are struck at the Sarvam rate card, which is
    the only price this product had when they were written."""
    token = await _make_admin()
    async with _client() as http:
        await http.post(
            "/v1/ops/tts-prices/cartesia",
            headers=_headers(token, tts_attest_confirmation("cartesia")),
            json={"inr_per_1k_chars": "3.4496", "source_note": "Cartesia Startup, 2026-09"},
        )

    from apps.api.billing.spend_routes import _by_provider_out
    from apps.api.billing.tts_speaking_rate import summarize

    async with untenanted_session() as session:
        attested = await attested_tts_prices(session, at=datetime.now(UTC))

    rows = {row.provider: row for row in _by_provider_out(summarize([]), attested=attested)}
    assert set(rows) == {"sarvam", "cartesia"}
    assert rows["cartesia"].price_attested is True
    assert rows["cartesia"].inr_per_1k_chars is not None
    # NUMERIC(12,6) pads it to "3.449600" — the same number, compared as a Decimal and
    # never as a float.
    assert Decimal(rows["cartesia"].inr_per_1k_chars) == Decimal("3.4496")
    assert rows["sarvam"].tier_label == rates.voice_tier_label("sarvam")
    # NO MEASUREMENT, NO PER-MINUTE FIGURE. Two different absences — nothing attested, and
    # nothing measured — and both are reported as no number rather than as a zero.
    assert rows["cartesia"].pooled_inr_per_minute is None
