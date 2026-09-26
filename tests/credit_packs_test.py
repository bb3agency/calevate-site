"""Prepaid credit packs: the two-rate card, the cost-floor guard, and the catalogue shape.

The properties worth protecting, in the order they cost money:

- **No pack sells a minute below what that minute costs us**, on EITHER voice, each judged
  against its OWN floor (`rates.cost_floor_inr_per_min`). This is THE guard: a rate cut
  deep enough to sell below cost fails CI here, and the cost basis is read from the cost
  model, never written as a literal, so the check re-scores when the cost model moves.
- **Invariant 6** (plan §2.3.6): `cartesia >= sarvam` on every pack, and neither column
  rises as the pack gets bigger. A bigger pack that bought a dearer minute would be
  arbitrageable by buying the smaller one twice.
- **The founder-approved card is pinned**, all six rungs and both columns.
- **The catalogue shape**: unique resolvable ids, exactly one `best_value`, ₹1 = 1 credit.
- **The retired bonus path still behaves**, because it is still in `billing/payments.py`
  for one release (hard rule 8's two-step, plan §10) — driven here through a SYNTHETIC
  legacy pack, since no catalogue pack carries a bonus any more.
- **Money is Decimal end to end** (hard rule 7).

The MARGIN each approved rate delivers, and the fact that EIGHT of the twelve cells sit
under the 20% target deliberately, is `tests/cost_floor_test.py` — one file per behaviour.
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
    card_margins,
    card_refusals,
    pack_by_id,
    pack_paid_for,
    pack_rate_margin,
    pack_talk_time_minutes,
)
from apps.api.billing.payment_routes import router as topup_router
from apps.api.billing.payment_routes import webhook_router
from apps.api.billing.rates import (
    VOICE_TIERS,
    cost_floor_inr_per_min,
)
from apps.api.core.errors import install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.signup_routes import router as signup_router
from calevate_shared.config import Settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

#: THE FOUNDER-APPROVED CARD (`docs/PIPECAT-MIGRATION.md` §12, 14 Sep 2026), typed out here
#: so a rate that moves without the founder moving it is a red test rather than a silent
#: repricing. TYPED, not derived, and deliberately: this list IS the founder's instruction,
#: and a version of it computed from the catalogue would assert the catalogue against
#: itself. It superseded the 7 Sep card (Clear 5.00 → 4.50, Studio 8.00 → 6.00).
APPROVED_CARD = [
    ("starter", Decimal("2000"), Decimal("4.00"), Decimal("7.00")),
    ("growth", Decimal("5000"), Decimal("4.00"), Decimal("6.70")),
    ("scale", Decimal("10000"), Decimal("4.00"), Decimal("6.40")),
    ("plus", Decimal("15000"), Decimal("4.00"), Decimal("6.10")),
    ("pro", Decimal("25000"), Decimal("4.00"), Decimal("5.80")),
    ("max", Decimal("50000"), Decimal("4.00"), Decimal("5.50")),
]

WEBHOOK_SECRET = "whsec_pack_test_secret"


def _pack(pack_id: str, amount: str, sarvam: str, cartesia: str) -> CreditPack:
    """A pack outside the catalogue, for the negative cases. Written by a helper so a
    refusal test says only what it is varying."""
    return CreditPack(
        pack_id=pack_id,
        amount_inr=Decimal(amount),
        clear_inr_per_min=Decimal(sarvam),
        studio_inr_per_min=Decimal(cartesia),
    )


# --- the cost-floor guard (pure, no DB) ---------------------------------------


def test_no_pack_sells_a_minute_below_its_voices_cost_floor() -> None:
    """THE GUARD. Twelve rates, two floors, and each rate judged against the floor for the
    voice it is a rate FOR — a Cartesia rate scored against the Sarvam floor would always
    pass, which is why `pack_rate_margin` pairs them rather than taking a cost."""
    assert card_refusals(PACK_CATALOGUE) == []
    for pack in PACK_CATALOGUE:
        for voice in VOICE_TIERS:
            verdict = pack_rate_margin(pack, voice=voice)
            assert verdict.below_cost is False, (
                f"pack {pack.pack_id} sells a {voice} minute at ₹{verdict.rate} "
                f"against a ₹{verdict.cost} floor"
            )
            assert verdict.cost == cost_floor_inr_per_min(voice)


def test_the_guard_has_teeth_on_a_below_cost_rate() -> None:
    """The assertion above is not vacuously true: a rate UNDER the floor is REFUSED, not
    warned. A rate that clears cost but misses the 20% target is the other posture —
    reported, not refused — and the two must be distinguishable.

    ⚠ **THE RATE IS DERIVED NOW, AND THE LITERAL IS WHY.** It was ₹4.00, typed against a
    ₹4.1211 floor. D-592 moved the engine leg from Bolna's $0.02/min BYOK fee to Pipecat's
    $0.01/min active minute, the floor fell to ₹3.3111, and ₹4.00 became a rate that CLEARS
    cost — so a test named "the guard has teeth" was asserting that a profitable rate gets
    refused. A literal on the wrong side of a moving line is the failure mode; half the
    floor cannot land on the wrong side of it.

    ⚠ This docstring has now said three different things about the band, which is the
    hazard a derived rate exists to survive. It said "the whole approved Sarvam column is in
    that band" (true before D-592), then "every rung on both columns now clears the 20%
    target" (true only between D-592 and 14 Sep 2026). What is true today: the founder's
    14 Sep card puts EIGHT of twelve cells under the target — the whole Clear column at
    17.2%, and Studio's `pro` and `max` at 18.8% and 14.4% — and none below cost. The
    assertions below do not depend on any of that, which is the point of deriving them.
    """
    half_floor = (cost_floor_inr_per_min("clear") / 2).quantize(Decimal("0.01"))
    below_cost = _pack("greedy", "50000", str(half_floor), "6.00")
    verdict = pack_rate_margin(below_cost, voice="clear")
    assert verdict.below_cost is True
    assert [f for f in card_refusals((below_cost,)) if "below cost" in f]

    # DERIVED for the same reason as the rate above: a literal ₹4.50 was thin against a
    # ₹4.1211 floor and earns 26% against ₹3.3111. Ten paisa over the floor is thin at any
    # floor — the property this half of the test is actually about.
    thin_rate = (cost_floor_inr_per_min("clear") + Decimal("0.10")).quantize(Decimal("0.01"))
    thin_pack = _pack("thin", "50000", str(thin_rate), "6.00")
    thin = pack_rate_margin(thin_pack, voice="clear")
    assert thin.below_cost is False
    assert thin.below_target is True
    assert thin.margin is not None and thin.margin < MIN_MARGIN
    assert card_refusals((thin_pack,)) == []


def test_a_zero_rate_is_below_cost_and_has_no_margin_to_display() -> None:
    """A free minute is a loss, not an undefined margin. `RateMargin.margin` is None only
    because the ratio has no denominator; `below_cost` still says what it is."""
    verdict = pack_rate_margin(_pack("free", "2000", "0", "0"), voice="clear")
    assert verdict.below_cost is True
    assert verdict.margin is None
    assert verdict.below_target is False


def test_invariant_6_cartesia_is_never_cheaper_than_sarvam() -> None:
    """Plan §2.3.6, first half. Cartesia costs us more per minute; a card that priced it
    lower would sell the dearer voice at the cheaper price on every call."""
    for pack in PACK_CATALOGUE:
        assert pack.studio_inr_per_min >= pack.clear_inr_per_min, pack.pack_id
    inverted = _pack("inverted", "2000", "8.00", "5.00")
    assert [f for f in card_refusals((inverted,)) if "invariant 6" in f]


def test_invariant_6_a_bigger_pack_never_buys_a_dearer_minute() -> None:
    """Plan §2.3.6, second half — checked on BOTH columns, because a card can be monotone
    on one and not the other and the reader would see a sensible-looking table."""
    for voice in VOICE_TIERS:
        rates = [pack.inr_per_min(voice) for pack in PACK_CATALOGUE]
        assert rates == sorted(rates, reverse=True), f"the {voice} column must not rise"
    climbing = (_pack("small", "2000", "5.00", "8.00"), _pack("big", "50000", "5.50", "8.50"))
    failures = card_refusals(climbing)
    assert len([f for f in failures if "dearer minute" in f]) == 2, failures


def test_the_founder_approved_card_is_pinned() -> None:
    """THE RATE CARD ITSELF: id, amount and both rates, in ladder order, all six rungs.

    The rates ARE the margin model since D-547 (they replaced `list_rate / (1 + bonus)`),
    so a rate that moves without the founder moving it changes what we earn per minute.
    The amounts carry the founder's instruction (a ₹2,000 entry floor, a ₹50,000 ceiling)
    plus the deliberate choice of ROUND rungs over the competitor's ₹x,999 charm prices.
    """
    assert [
        (p.pack_id, p.amount_inr, p.clear_inr_per_min, p.studio_inr_per_min) for p in PACK_CATALOGUE
    ] == APPROVED_CARD
    amounts = [p.amount_inr for p in PACK_CATALOGUE]
    assert amounts == sorted(amounts), "the ladder is read top to bottom; keep it ascending"
    assert amounts[0] == Decimal("2000"), "the founder's ₹2,000 entry floor"
    assert amounts[-1] == Decimal("50000"), "the founder's ₹50,000 ceiling"
    for amount in amounts:
        # Round rungs, not charm prices: what makes the rate and the talk time easy to hold
        # in your head.
        assert amount % Decimal("1000") == 0, f"{amount} is not a round rung"


def test_the_legacy_list_rate_setting_still_equals_the_entry_rungs_clear_rate() -> None:
    """`Settings.self_serve_inr_per_min` IS the card's entry rung, and nothing enforces it
    except this.

    The setting is the pre-D-547 single price, kept alive for one release (plan §10) and
    still read by `billing/service`, `billing/attribution` and `workers/pipeline` to price a
    CLOSED month, and by `list_rates.self_serve_rate_at` as the fallback for any instant no
    recorded card covers. The ops console keeps the two equal on every write
    (`config_routes._record_card` passes `list_rates.card_list_rate(card)`), but a card
    changed in CODE — which is the only way this catalogue changes — touches no console and
    updates no setting.

    So the default and the entry rung have to be moved together, and when D-601 cut the
    card to ₹4.00 they were not: for one commit a wallet was debited ₹4.00 from the lot
    while a closed month on a deployment with no recorded card still rendered at ₹5.00.
    `tests/client_rate_billing_test.py` caught it. The two figures cannot be derived from
    one another (`calevate_shared` may not import `apps.api`), so the equality is asserted
    here instead.
    """
    # The CODE DEFAULT, not the live value: the setting is operator-editable by design, and
    # what has to stay paired with the code catalogue is the figure a deployment falls back
    # to when nobody has set one. (`tests/platform_config_test.py` reads it the same way.)
    default = Settings.model_fields["self_serve_inr_per_min"].get_default(call_default_factory=True)
    assert default == PACK_CATALOGUE[0].clear_inr_per_min


def test_the_fifteen_thousand_rung_exists_between_ten_and_twenty_five() -> None:
    """The `plus` pack is new in D-547 and its position in the ladder is the decision — a
    rung appended at the end would break the monotonicity every other assertion rests on."""
    plus = pack_by_id("plus")
    assert plus is not None
    assert plus.amount_inr == Decimal("15000")
    ids = [p.pack_id for p in PACK_CATALOGUE]
    assert ids.index("scale") < ids.index("plus") < ids.index("pro")


def test_the_card_preview_is_twelve_rows_in_card_then_voice_order() -> None:
    """What the ops console renders before it writes a card, and what CI scores, are the
    same twelve verdicts in the same order (`ops/config_routes._record_card`)."""
    preview = card_margins()
    assert len(preview) == len(PACK_CATALOGUE) * len(VOICE_TIERS)
    assert [(pack_id, voice) for pack_id, voice, _ in preview] == [
        (pack.pack_id, voice) for pack in PACK_CATALOGUE for voice in VOICE_TIERS
    ]
    assert preview == card_margins(PACK_CATALOGUE)


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


def test_a_pack_is_bought_only_by_paying_its_price() -> None:
    """The pack id rides in provider notes a browser can author; the amount is what the
    provider actually captured. Only the pair together is a pack purchase."""
    for pack in PACK_CATALOGUE:
        assert pack_paid_for(pack.pack_id, pack.amount_inr) is pack
        assert pack_paid_for(pack.pack_id, Decimal(f"{pack.amount_inr}.00")) is pack
        assert pack_paid_for(pack.pack_id, pack.amount_inr - Decimal("0.01")) is None
        assert pack_paid_for(pack.pack_id, pack.amount_inr + Decimal("1")) is None
    assert pack_paid_for(None, Decimal("2000")) is None
    assert pack_paid_for("no-such-pack", Decimal("2000")) is None


def test_a_pack_prices_by_voice_and_refuses_a_tier_it_does_not_carry() -> None:
    """`inr_per_min` is total over the two tiers and RAISES otherwise. A lookup that fell
    back to the cheaper column would undercharge a Cartesia minute silently."""
    plus = pack_by_id("plus")
    assert plus is not None
    assert plus.inr_per_min("clear") == Decimal("4.00")
    assert plus.inr_per_min("studio") == Decimal("6.10")
    with pytest.raises(ValueError, match="not a voice tier"):
        plus.inr_per_min("elevenlabs")  # type: ignore[arg-type]


def test_credits_are_one_rupee_each_and_talk_time_divides_by_the_voices_rate() -> None:
    """1 credit = ₹1, so a ₹15,000 pack holds 15,000 credits — and buys 3,750 minutes on
    Sarvam (₹4.00) against 2,459 on Cartesia (₹6.10). The pair is the client-facing number
    the wallet screen shows (plan Q7), and it is why one balance can no longer print one
    "minutes left"."""
    plus = pack_by_id("plus")
    assert plus is not None
    assert plus.paid_credits == Decimal("15000.0000")
    assert plus.total_credits == plus.paid_credits
    sarvam = pack_talk_time_minutes(plus, voice="clear")
    cartesia = pack_talk_time_minutes(plus, voice="studio")
    assert int(sarvam) == 3750
    assert int(cartesia) == 2459
    assert cartesia < sarvam


def test_no_pack_carries_a_bonus_any_more() -> None:
    """The deprecated fields are zero on every rung, not merely unused: `billing/payments.py`
    still reads `bonus_credits` for one release (plan §10) and must find nothing to grant."""
    for pack in PACK_CATALOGUE:
        assert pack.bonus_pct == Decimal("0"), pack.pack_id
        assert pack.bonus_credits == Decimal("0.0000"), pack.pack_id
        assert pack.total_credits == pack.paid_credits, pack.pack_id


# --- the RETIRED bonus grant (DB) ---------------------------------------------
#
# No catalogue pack carries a bonus since D-547, so every test below that needs one drives
# `payments.pack_paid_for` through `_legacy_bonus_pack` — a synthetic pack with the ₹5,000
# rung's old 3%. The machinery is still in `billing/payments.py` and is retired in Phase B
# (plan §10's two-step), so it is still covered here rather than left to rot untested; what
# it must never do again is fire for a REAL pack, which `test_no_catalogue_pack_grants_a_
# bonus_row` asserts against the live catalogue.


def _legacy_bonus_pack(pack_id: str, amount: str, bonus_pct: str) -> CreditPack:
    """A pre-D-547 pack: two rates AND a bonus. Only a test builds one now."""
    return CreditPack(
        pack_id=pack_id,
        amount_inr=Decimal(amount),
        clear_inr_per_min=Decimal("5.00"),
        studio_inr_per_min=Decimal("8.00"),
        bonus_pct=Decimal(bonus_pct),
    )


@pytest.fixture
def legacy_bonus(monkeypatch: pytest.MonkeyPatch) -> CreditPack:
    """Make `growth` a 3%-bonus pack again, for the crediting path only.

    `payments.py` imports `pack_paid_for` by name, so the patch is on the payments module's
    own binding — the catalogue itself is untouched and every other assertion in this file
    still reads the real card. The stand-in keeps the price check, so a test that pays the
    wrong amount still gets no pack.
    """
    pack = _legacy_bonus_pack("growth", "5000", "3")
    monkeypatch.setattr(
        payments,
        "pack_paid_for",
        lambda pack_id, amount_inr: (
            pack if pack_id == pack.pack_id and amount_inr == pack.amount_inr else None
        ),
    )
    return pack


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
                # `email_verified_at` IS SET, because `signup.assert_email_verified` now
                # requires a proved mailbox before a tenant is created. This helper only
                # needs A TENANT to bill; the gate itself is asserted in
                # `tests/self_serve_test.py`.
                "INSERT INTO users (id, email, email_verified_at, created_at, updated_at) "
                "VALUES (:i, :e, now(), now(), now())"
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


async def test_a_legacy_bonus_pack_grants_paid_and_bonus_credits(
    legacy_bonus: CreditPack,
) -> None:
    """A pre-D-547 pack: one paid `topup` (₹5,000) and one `bonus` (₹150), both keyed on
    the payment id, and a balance that reflects the sum."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("GROWTH")
    # ₹5,000 in paise.
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=500000, pack_id="growth")
    )

    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "credited"
    # Balance = paid + bonus = 5000 + 150 = 5150.
    assert response.json()["balance_inr"] == "5150.00"

    entries = await _ledger(tenant_id)
    assert entries == [
        ("topup", Decimal("5000.0000"), payment_id),
        ("bonus", Decimal("150.0000"), payment_id),
    ]


async def test_a_pack_bonus_is_granted_exactly_once_on_replay(
    legacy_bonus: CreditPack,
) -> None:
    """A redelivered pack payment credits paid+bonus once — the payment id is the key on
    both the `topup` and the `bonus` namespace."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("REPLAY")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=500000, pack_id="growth")
    )

    async with _client() as http:
        first = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)
        replay = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert first.json()["status"] == "credited"
    assert replay.json()["status"] == "duplicate"

    entries = await _ledger(tenant_id)
    # ₹5,000 paid + ₹150 bonus (3%), exactly one of each.
    assert entries == [
        ("topup", Decimal("5000.0000"), payment_id),
        ("bonus", Decimal("150.0000"), payment_id),
    ]


async def test_the_bonus_survives_a_direct_replay_via_the_ledger_ref(
    legacy_bonus: CreditPack,
) -> None:
    """Called directly (an ARQ retry or manual replay), the paid+bonus pair still lands
    once — the ledger `ref` under each reason is the arbiter, not the expiring inbox."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("DIRECT")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_id,
        amount_inr=Decimal("5000.00"),
        currency="INR",
        pack_id="growth",
    )
    async with tenant_session(tenant_id) as session:
        first = await payments.credit_captured_payment(session, payment=payment)
    async with tenant_session(tenant_id) as session:
        second = await payments.credit_captured_payment(session, payment=payment)

    assert first.recorded is True
    assert first.bonus_inr == Decimal("150.0000")  # 3% of 5000
    assert second.recorded is False
    assert await _ledger(tenant_id) == [
        ("topup", Decimal("5000.0000"), payment_id),
        ("bonus", Decimal("150.0000"), payment_id),
    ]


async def test_a_direct_second_grant_of_a_pack_bonus_is_a_no_op(
    legacy_bonus: CreditPack,
) -> None:
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
        amount_inr=Decimal("5000.00"),
        currency="INR",
        pack_id="growth",
    )
    pack = legacy_bonus
    async with tenant_session(tenant_id) as session:
        first = await payments.credit_captured_payment(session, payment=payment)
    assert first.bonus_entry_id is not None
    assert first.bonus_inr == Decimal("150.0000")  # 3% of 5000

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
    assert replay.bonus_inr == Decimal("150.0000")
    # Still exactly one topup and one bonus row — the second grant wrote nothing.
    assert await _ledger(tenant_id) == [
        ("topup", Decimal("5000.0000"), payment_id),
        ("bonus", Decimal("150.0000"), payment_id),
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


async def test_no_catalogue_pack_grants_a_bonus_row() -> None:
    """THE D-547 BEHAVIOUR, on the LIVE catalogue and with nothing patched: buying the
    ₹15,000 `plus` pack credits ₹15,000 and writes no bonus row at all. The discount is the
    pack's per-minute rates now, and a ₹0 bonus row would be noise on an append-only
    ledger."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("PLUS")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=1500000, pack_id="plus")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.json()["status"] == "credited"
    assert response.json()["balance_inr"] == "15000.00"
    assert await _ledger(tenant_id) == [("topup", Decimal("15000.0000"), payment_id)]


async def test_an_unknown_pack_id_credits_the_payment_without_a_bonus() -> None:
    """A pack id this build no longer offers must not lose a real payment: the paid credit
    lands, and no bonus is invented for a pack the catalogue cannot price."""
    tenant_id, _ = await _self_serve_tenant()
    payment_id = _payment_id("GHOST")
    raw, headers = _sign(
        _envelope(payment_id=payment_id, tenant_id=tenant_id, amount=300000, pack_id="retired-2024")
    )
    async with _client() as http:
        response = await http.post("/hooks/v1/razorpay", content=raw, headers=headers)

    assert response.json()["status"] == "credited"
    assert await _ledger(tenant_id) == [("topup", Decimal("3000.0000"), payment_id)]


async def test_a_pack_bonus_is_invisible_to_another_tenant(legacy_bonus: CreditPack) -> None:
    """Bonus rows ride `credit_ledger`'s existing FORCEd RLS: a bonus written for one tenant
    is zero rows from another tenant's session."""
    tenant_a, _ = await _self_serve_tenant()
    tenant_b, _ = await _self_serve_tenant()
    payment_id = _payment_id("RLS")
    payment = payments.CapturedPayment(
        payment_id=payment_id,
        tenant_id=tenant_a,
        amount_inr=Decimal("5000.00"),
        currency="INR",
        pack_id="growth",
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
    assert body["amount_inr"] == "25000.00"
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
        assert isinstance(pack["clear_inr_per_min"], str)
        assert isinstance(pack["studio_inr_per_min"], str)
        assert isinstance(pack["total_credits"], str)
    # The list rate IS the entry rung's Sarvam rate since D-547.
    starter = next(p for p in body["packs"] if p["pack_id"] == "starter")
    assert Decimal(starter["clear_inr_per_min"]) == Decimal(body["list_rate_inr_per_min"])
    assert next(p for p in body["packs"] if p["best_value"])["pack_id"] == "max"
