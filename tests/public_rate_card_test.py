"""The public self-serve rate card (D-545): one builder, no session, nothing but the card.

Three claims, each pinned against the SOURCE rather than against a number typed here:

1. **Every effective rate on the wire is the function the margin guard scores.**
   `pack_effective_rate_inr_per_min` is what `tests/credit_packs_test.py` runs
   `MIN_GROSS_MARGIN` against; the route must publish exactly that, quantised the way
   `_pack_out` quantises it, for every member of `PACK_CATALOGUE`. A ladder change moves
   both or fails here — which is the whole reason the site reads this route instead of
   holding its own copy of the table.
2. **The route is reachable with no session and returns no field beyond the card.** The
   body's keys are asserted as an EQUALITY with the model's declared fields, so a field
   added to `CreditPacksOut` without a reader asking for it fails here rather than
   leaking onto a public page; and the public body is byte-identical to what the
   authenticated `/packs` read returns, because they are the same function.
3. **The guards agree it is public.** Declared in `UNAUTHENTICATED_ROUTES`, under a
   `PUBLIC_PREFIXES` entry, on its own `public_read` rate profile, with a public cache.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_DOWN, Decimal

from apps.api.billing.credit_packs import (
    PACK_CATALOGUE,
    pack_effective_rate_inr_per_min,
    pack_talk_time_minutes,
)
from apps.api.billing.payment_routes import (
    RATE_CARD_CACHE_CONTROL,
    CreditPackOut,
    CreditPacksOut,
    rate_card_out,
)
from apps.api.billing.rates import MONEY_Q, ROUNDING
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
    for pack in body["packs"]:
        for field in ("amount_inr", "bonus_credits", "total_credits", "effective_rate_inr_per_min"):
            assert isinstance(pack[field], str), field
    assert response.headers["cache-control"] == RATE_CARD_CACHE_CONTROL


async def test_every_effective_rate_is_the_margin_guard_function_quantised_once() -> None:
    """Derived, per pack, from the SAME call the margin guard makes — so this test knows
    no rate of its own and cannot be satisfied by a typed ladder."""
    list_rate = get_settings().self_serve_inr_per_min
    async with _anonymous() as http:
        body = (await http.get(PATH)).json()
    by_id = {pack["pack_id"]: pack for pack in body["packs"]}
    assert list(by_id) == [pack.pack_id for pack in PACK_CATALOGUE]
    for pack in PACK_CATALOGUE:
        expected_rate = pack_effective_rate_inr_per_min(pack, list_rate=list_rate).quantize(
            MONEY_Q, rounding=ROUNDING
        )
        expected_minutes = int(
            pack_talk_time_minutes(pack, list_rate=list_rate).quantize(
                Decimal("1"), rounding=ROUND_DOWN
            )
        )
        row = by_id[pack.pack_id]
        assert Decimal(row["effective_rate_inr_per_min"]) == expected_rate, pack.pack_id
        assert row["talk_time_minutes"] == expected_minutes, pack.pack_id
        assert Decimal(row["amount_inr"]) == pack.amount_inr
        assert Decimal(row["bonus_pct"]) == pack.bonus_pct
    # "from" is the LOWEST published row, and the list rate is the 0%-bonus pack's rate:
    # the two ends of the ladder, both derived.
    rates = [Decimal(row["effective_rate_inr_per_min"]) for row in by_id.values()]
    assert Decimal(body["from_inr_per_min"]) == min(rates)
    assert Decimal(body["list_rate_inr_per_min"]) == list_rate.quantize(Decimal("0.01"))
    zero_bonus = [p for p in PACK_CATALOGUE if p.bonus_pct == 0]
    assert zero_bonus, "the ladder has lost its list-rate rung"
    assert Decimal(by_id[zero_bonus[0].pack_id]["effective_rate_inr_per_min"]) == list_rate


def test_the_from_rate_is_derived_and_below_the_list_rate() -> None:
    """The founder's decision (5 Sep 2026) is that the site leads with what the packs
    already deliver: `from` must be a rate a pack produces, strictly under the list rate
    while any pack carries a bonus — never a typed figure."""
    list_rate = get_settings().self_serve_inr_per_min
    card = rate_card_out(list_rate)
    assert card.from_inr_per_min in {p.effective_rate_inr_per_min for p in card.packs}
    assert any(p.bonus_pct > 0 for p in PACK_CATALOGUE)
    assert card.from_inr_per_min < card.list_rate_inr_per_min
    # And it moves with the list rate — it is a derivation, not a constant. Re-derived
    # through the same function rather than doubled here: a rate quantised to 4dp does
    # not double exactly, and a test that pretended it did would be pinning arithmetic
    # the route does not perform.
    doubled = rate_card_out(list_rate * 2)
    assert doubled.from_inr_per_min == min(
        pack_effective_rate_inr_per_min(pack, list_rate=list_rate * 2).quantize(
            MONEY_Q, rounding=ROUNDING
        )
        for pack in PACK_CATALOGUE
    )
    assert doubled.from_inr_per_min > card.from_inr_per_min


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
