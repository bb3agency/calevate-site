"""Fixtures shared by the `credit_lots_*` suites (D-547, Phase B1).

One place to make a tenant, put credit on its wallet and open a lot, so that eight test
files cannot drift about what "a funded wallet with two lots" means. Deliberately NOT in
`tests/conftest.py`: nothing outside this feature needs them yet, and a helper in conftest
is a helper every suite pays to import.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import pytest
from apps.api.billing import lots
from apps.api.billing import service as billing_service
from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack, pack_by_id
from apps.api.billing.rates import PREMIUM_VOICE_TIER, VALUE_VOICE_TIER
from apps.api.billing.service import record_entry
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

# TWO FROZEN RATE PAIRS, FROM THE CARD THAT WAS IN FORCE ON 7 SEP 2026 — NOT FROM THE CARD
# ON SALE TODAY, AND THAT IS THE POINT RATHER THAN AN OVERSIGHT.
#
# A lot's rates are frozen at purchase for the life of its credit (`credit_lots_terms_frozen`
# refuses any UPDATE that touches them), so a wallet holds lots priced at cards that are no
# longer sold — permanently, and by design. Fixtures built out of TODAY's catalogue would
# assert that relationship away: the founder's card of 14 Sep 2026 made the Clear column FLAT
# at ₹4.00 on all six rungs, so two rungs of the live card differ on Studio only, and every
# suite below that shows a call splitting across two lots at two Clear rates would have
# nothing to show.
#
# So these stay what they were: the `growth` and `plus` rungs of the superseded card, i.e.
# what a client who bought on 8 Sep is still holding. `add_lot(pack_id="growth",
# rates=GROWTH)` reads as "a lot bought on the growth rung, at the rates that rung sold at
# then", which is a row the production database really contains.
#
# ⚠ **THEY ARE NOT THE CATALOGUE AND MUST NOT BE READ AS IT.** A test about how the rungs of
# a card relate to each other installs `GRADUATED_CARD` below and reads its rates through
# `graduated_pack(...)`, never these.

#: The ₹5,000 (`growth`) rung as the 7 Sep card sold it, used wherever a test needs "some
#: ordinary lot" and does not care which.
GROWTH = (Decimal("5.00"), Decimal("7.00"))
#: The ₹15,000 (`plus`) rung as the same card sold it — a CHEAPER minute on both voices,
#: which is what makes a two-lot split at two rates visible on either tier.
PLUS = (Decimal("4.70"), Decimal("6.50"))

#: A card whose rungs price DIFFERENTLY, for the suites whose property is the order of two
#: rungs' rates (a re-price only lowers; a refunded lot must not keep pricing minutes).
#:
#: The card on sale cannot carry those properties: since D-728 (11 Oct 2026) every pack is
#: flat at the same two rates, so any two catalogue rungs price every minute identically and
#: a test built on them passes whether or not the behaviour exists. A recorded card in
#: `platform_list_rates` would make the rungs differ too, but it is shared state every
#: other suite reading the card would see. So the card is installed per test by
#: `graduated_card`, which replaces the one reader every lot opener asks
#: (`service.rate_card_at` -> `card_at`).
#:
#: Shaped as the tests need it, never rising as the amount rises, and above every engine's
#: cost floor (`credit_packs` module docstring):
#: - `starter` matches `growth` on Clear and is dearer on Studio only, so a guard that
#:   compared one tier would let a re-price onto it through;
#: - `max` is cheaper than `growth` on both tiers.
GRADUATED_CARD: Final[Mapping[str, tuple[Decimal, Decimal]]] = {
    "starter": (Decimal("4.50"), Decimal("6.50")),
    "growth": (Decimal("4.50"), Decimal("6.00")),
    "scale": (Decimal("4.40"), Decimal("5.90")),
    "plus": (Decimal("4.30"), Decimal("5.80")),
    "pro": (Decimal("4.25"), Decimal("5.75")),
    "max": (Decimal("4.20"), Decimal("5.50")),
}
assert set(GRADUATED_CARD) == {pack.pack_id for pack in PACK_CATALOGUE}, (
    "GRADUATED_CARD must price every pack the catalogue sells"
)


def graduated_pack(pack_id: str) -> CreditPack:
    """The catalogue pack `pack_id`, at `GRADUATED_CARD`'s rates."""
    pack = pack_by_id(pack_id)
    assert pack is not None, pack_id
    clear, studio = GRADUATED_CARD[pack_id]
    return replace(pack, clear_inr_per_min=clear, studio_inr_per_min=studio)


@pytest.fixture
def graduated_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every lot opened or re-priced in the test is priced from `GRADUATED_CARD`."""

    async def _card_at(_session: object, *, at: datetime) -> dict[str, dict[str, Decimal]]:
        assert at.tzinfo is not None, "a card is resolved at an aware instant"
        return {
            pack_id: {VALUE_VOICE_TIER: clear, PREMIUM_VOICE_TIER: studio}
            for pack_id, (clear, studio) in GRADUATED_CARD.items()
        }

    monkeypatch.setattr(billing_service, "card_at", _card_at)


async def make_tenant(prefix: str = "lot") -> UUID:
    created = await create_org_with_receptionist(
        name="Lots Clinic",
        slug=f"{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.test",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def credit_entry(tenant_id: UUID, *, amount: str, ref: str | None = None) -> UUID:
    """Append a top-up and return the entry's id — what `open_lot` needs to link to."""
    ref = ref or f"pay-{uuid.uuid4().hex[:10]}"
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal(amount),
            reason="topup",
            ref=ref,
            # A top-up that only PARTLY repays an overdraft is money that really arrived,
            # and `record_entry` refuses a positive delta that leaves the balance negative
            # unless told otherwise. Phase B2's §4.B.5 books the repayment before opening
            # a lot; the fixtures here have to be able to reach that state.
            allow_negative=True,
        )
        entry_id = (
            await session.execute(
                text(
                    "SELECT id FROM credit_ledger WHERE tenant_id = :t AND ref = :r "
                    "AND reason = 'topup'"
                ),
                {"t": tenant_id, "r": ref},
            )
        ).scalar_one()
    return UUID(str(entry_id))


async def add_lot(
    tenant_id: UUID,
    *,
    credits_inr: str,
    rates: tuple[Decimal, Decimal] = GROWTH,
    source: lots.LotSource = "topup",
    pack_id: str | None = "growth",
    override_of_pack_id: str | None = None,
) -> UUID:
    """Money in, and the lot it opens — the pair every credit-adding writer will do in one
    transaction once Phase B2 wires them."""
    entry_id = await credit_entry(tenant_id, amount=credits_inr)
    async with tenant_session(tenant_id) as session:
        return await lots.open_lot(
            session,
            tenant_id=tenant_id,
            credits_inr=Decimal(credits_inr),
            clear_inr_per_min=rates[0],
            studio_inr_per_min=rates[1],
            source=source,
            pack_id=pack_id,
            ledger_entry_id=entry_id,
            override_of_pack_id=override_of_pack_id,
        )


async def lot_rows(tenant_id: UUID) -> list[dict[str, Any]]:
    """Every lot of a tenant, open or closed, oldest first — the assertion surface."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, source, pack_id, override_of_pack_id, credits_total, "
                    "credits_remaining, clear_inr_per_min, studio_inr_per_min, "
                    "closed_at FROM credit_lots WHERE tenant_id = :t "
                    "ORDER BY opened_at, id"
                ),
                {"t": tenant_id},
            )
        ).mappings()
        return [dict(row) for row in rows]
