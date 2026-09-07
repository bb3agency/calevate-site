"""The public self-serve rate card (D-545): one builder, no session, nothing but the card.

Three claims, each pinned against the SOURCE rather than against a number typed here:

1. **Every rate on the wire is the catalogue rate the margin guard scores.** `PACK_CATALOGUE`
   is what `tests/credit_packs_test.py` runs `card_refusals` against; the route must publish
   exactly those twelve rates, quantised the way `_pack_out` quantises them, for every
   member. A ladder change moves both or fails here — which is the whole reason the site
   reads this route instead of holding its own copy of the table. ⚠ Since D-547 the card is
   STATIC: this body does not move when `self_serve_inr_per_min` does, and one test below
   says so, because the previous behaviour was the opposite and the site cached it.
2. **The route is reachable with no session and returns no field beyond the card.** The
   body's keys are asserted as an EQUALITY with the model's declared fields, so a field
   added to `CreditPacksOut` without a reader asking for it fails here rather than
   leaking onto a public page; and the public body is byte-identical to what the
   authenticated `/packs` read returns, because they are the same function.
3. **The guards agree it is public.** Declared in `UNAUTHENTICATED_ROUTES`, under a
   `PUBLIC_PREFIXES` entry, on its own `public_read` rate profile, with a public cache.
4. **The NAME a client reads for a voice crosses this wire too, and is not a vendor's.**
   Added 7 Sep 2026 with the founder's decision that no client-facing surface names a
   vendor as a product tier: the label comes from `rates.VOICE_TIER_LABELS`, so the site
   renders what the API sent rather than a copy of it, and the field names beside it keep
   the vendor spelling because that is what the ledger means by them.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal

import pytest
from apps.api.billing.credit_packs import PACK_CATALOGUE, pack_talk_time_minutes
from apps.api.billing.payment_routes import (
    RATE_CARD_CACHE_CONTROL,
    CreditPackOut,
    CreditPacksOut,
    rate_card_out,
)
from apps.api.billing.rates import MONEY_Q, ROUNDING, VOICE_TIERS, voice_tier_label
from apps.api.core.ratelimit import profile_for
from apps.api.core.rbac import PUBLIC_PREFIXES
from apps.api.core.settings import get_settings
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from scripts.check_public_routes import UNAUTHENTICATED_ROUTES

PATH = "/v1/public/rate-card"


def _anonymous() -> AsyncClient:
    """A stranger: no bearer, no cookie, no org header, a fresh address per client so the
    per-test limiter namespace is the only thing shared with the rest of the suite."""
    address = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(address, 4321)), base_url="http://api"
    )


async def test_the_rate_card_answers_a_stranger_with_the_card_and_nothing_else() -> None:
    async with _anonymous() as http:
        response = await http.get(PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    # EQUALITY with the model, not a subset: a new field reaches the public page only by
    # being declared here on purpose.
    assert set(body) == set(CreditPacksOut.model_fields)
    for pack in body["packs"]:
        assert set(pack) == set(CreditPackOut.model_fields)
    # Money is a string on the wire (hard rule 7) — never a JSON number a browser floats.
    assert isinstance(body["list_rate_inr_per_min"], str)
    assert isinstance(body["from_inr_per_min"], str)
    assert isinstance(body["from_sarvam_inr_per_min"], str)
    assert isinstance(body["from_cartesia_inr_per_min"], str)
    for pack in body["packs"]:
        for field in (
            "amount_inr",
            "bonus_credits",
            "total_credits",
            "sarvam_inr_per_min",
            "cartesia_inr_per_min",
            "effective_rate_inr_per_min",
        ):
            assert isinstance(pack[field], str), field
    assert response.headers["cache-control"] == RATE_CARD_CACHE_CONTROL


async def test_every_rate_on_the_wire_is_the_catalogue_rate_quantised_once() -> None:
    """Derived, per pack per voice, from the SAME tuple the margin guard scores — so this
    test knows no rate of its own and cannot be satisfied by a typed ladder."""
    async with _anonymous() as http:
        body = (await http.get(PATH)).json()
    by_id = {pack["pack_id"]: pack for pack in body["packs"]}
    assert list(by_id) == [pack.pack_id for pack in PACK_CATALOGUE]
    for pack in PACK_CATALOGUE:
        row = by_id[pack.pack_id]
        for voice in VOICE_TIERS:
            expected_rate = pack.inr_per_min(voice).quantize(MONEY_Q, rounding=ROUNDING)
            expected_minutes = int(
                pack_talk_time_minutes(pack, voice=voice).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
            )
            assert Decimal(row[f"{voice}_inr_per_min"]) == expected_rate, (pack.pack_id, voice)
            assert row[f"{voice}_minutes"] == expected_minutes, (pack.pack_id, voice)
        assert Decimal(row["amount_inr"]) == pack.amount_inr
        assert Decimal(row["total_credits"]) == pack.total_credits
    # The two "from" figures are the LOWEST published row per column, and the list rate is
    # the ENTRY rung's Sarvam rate: the two ends of the ladder, both derived.
    assert Decimal(body["from_sarvam_inr_per_min"]) == min(
        Decimal(row["sarvam_inr_per_min"]) for row in by_id.values()
    )
    assert Decimal(body["from_cartesia_inr_per_min"]) == min(
        Decimal(row["cartesia_inr_per_min"]) for row in by_id.values()
    )
    assert Decimal(body["list_rate_inr_per_min"]) == PACK_CATALOGUE[0].sarvam_inr_per_min


async def test_the_deprecated_fields_stay_on_the_wire_holding_the_safe_value() -> None:
    """Plan §10's two-step: nothing an existing reader uses disappears in this release.

    `bonus_pct`/`bonus_credits` are ZERO (no pack grants a bonus), and the two single-value
    rate fields hold the SARVAM figure — the cheaper column — so an unmigrated reader
    under-quotes a Cartesia minute rather than over-quoting it. Getting that direction wrong
    would have the marketing site advertise a price we do not charge.
    """
    async with _anonymous() as http:
        body = (await http.get(PATH)).json()
    assert Decimal(body["from_inr_per_min"]) == Decimal(body["from_sarvam_inr_per_min"])
    assert Decimal(body["from_inr_per_min"]) < Decimal(body["from_cartesia_inr_per_min"])
    for row in body["packs"]:
        assert Decimal(row["bonus_pct"]) == 0
        assert Decimal(row["bonus_credits"]) == 0
        assert Decimal(row["total_credits"]) == Decimal(row["paid_credits"])
        assert Decimal(row["effective_rate_inr_per_min"]) == Decimal(row["sarvam_inr_per_min"])
        assert row["talk_time_minutes"] == row["sarvam_minutes"]


async def test_the_card_names_each_voice_tier_without_naming_its_vendor() -> None:
    """The founder's rule of 7 Sep 2026, pinned at the one place the name crosses the wire.

    A client buys a named voice QUALITY; which vendor speaks it is ours and must be able to
    change without a client-visible rename. So the label travels with the rate (the
    marketing site may not hold its own copy — `apps/web/tests/marketingPages.test.tsx`
    checks the other end), it comes from `rates.VOICE_TIER_LABELS` rather than from a
    string typed into this module, and it may not BE the vendor's name — which is the half
    a copy-paste would break silently, because "Sarvam" reads like a perfectly good label
    to anybody who has not been told the rule.

    The field NAMES beside it still say `sarvam`/`cartesia` on purpose: those mean the
    vendor and are the ledger's vocabulary (plan §2.3.7), and renaming a vendor in a money
    column is how a leg becomes unauditable.
    """
    async with _anonymous() as http:
        body = (await http.get(PATH)).json()
    for voice in VOICE_TIERS:
        label = body[f"{voice}_tier_label"]
        assert label == voice_tier_label(voice)
        assert label.strip(), voice
        for vendor in ("sarvam", "cartesia", "bulbul", "sonic"):
            assert vendor not in label.lower(), (voice, label)
    assert body["sarvam_tier_label"] != body["cartesia_tier_label"]


async def test_the_packs_arrive_in_ladder_order_with_both_columns_falling() -> None:
    """The WIRE order is load-bearing, so it is pinned here and not only in the catalogue.

    `/pricing` renders the rows in the order they arrive and tells the reader, in words,
    that putting more on at once brings the rate down. That sentence is true of the PAGE
    only if the response is ascending by amount with neither column rising — a property of
    this body, not of the tuple behind it, and one a `sorted()` slipped into the builder
    would break without failing `tests/credit_packs_test.py`.
    """
    async with _anonymous() as http:
        rows = (await http.get(PATH)).json()["packs"]
    amounts = [Decimal(row["amount_inr"]) for row in rows]
    assert amounts == sorted(amounts) and len(set(amounts)) == len(amounts)
    for voice in VOICE_TIERS:
        rates = [Decimal(row[f"{voice}_inr_per_min"]) for row in rows]
        assert rates == sorted(rates, reverse=True), voice
        # And the dearer voice is dearer on every rung, which is what lets the page put the
        # two columns side by side without explaining an inversion.
    for row in rows:
        assert Decimal(row["cartesia_inr_per_min"]) >= Decimal(row["sarvam_inr_per_min"])
        assert row["cartesia_minutes"] <= row["sarvam_minutes"]


def test_the_from_rates_are_derived_and_below_the_list_rate() -> None:
    """The founder's rule survives D-547: the site leads with a rate a pack actually
    delivers, never a typed figure. Both columns fall across the ladder, so both "from"
    figures come from the deepest pack and the Sarvam one is under the list rate."""
    card = rate_card_out()
    assert card.from_sarvam_inr_per_min in {p.sarvam_inr_per_min for p in card.packs}
    assert card.from_cartesia_inr_per_min in {p.cartesia_inr_per_min for p in card.packs}
    assert card.from_sarvam_inr_per_min < card.list_rate_inr_per_min
    assert card.from_cartesia_inr_per_min > card.from_sarvam_inr_per_min


def test_the_card_no_longer_moves_with_the_self_serve_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """⚠ THE BEHAVIOUR CHANGE, PINNED. This body used to be derived from the live
    `self_serve_inr_per_min` console setting; since D-547 every rate comes from the static
    catalogue and the setting prices nothing on this card. The setting stays readable (plan
    §10) and still dates its own row, so the check is that moving it changes NOTHING here —
    a regression to the old behaviour would silently reprice the public marketing site from
    an ops console."""
    before = rate_card_out()
    monkeypatch.setattr(get_settings(), "self_serve_inr_per_min", Decimal("99.00"))
    assert rate_card_out() == before


def test_the_guards_agree_the_route_is_public_and_bounded() -> None:
    assert f"GET {PATH}" in UNAUTHENTICATED_ROUTES
    assert any(PATH.startswith(prefix) for prefix in PUBLIC_PREFIXES)
    assert profile_for(PATH, "GET").name == "public_read"
    # Not a per-person ceiling: the one caller is the marketing site's server.
    assert profile_for(PATH, "GET").per_client > profile_for("/v1/me", "GET").per_client


async def test_a_bearer_or_org_header_changes_nothing() -> None:
    """Nothing about the caller is read: a garbage credential and an org header are
    ignored rather than refused, because the body has no caller-dependent bit in it."""
    async with _anonymous() as http:
        plain = (await http.get(PATH)).json()
        decorated = await http.get(
            PATH, headers={"Authorization": "Bearer not-a-token", "X-Org-Slug": "acme"}
        )
    assert decorated.status_code == 200, decorated.text
    assert decorated.json() == plain
