"""Prepaid CREDIT PACKS, each carrying TWO per-minute rates (D-547, 7 Sep 2026).

A credit pack is a PRICING SHAPE on top of the wallet (`credit_ledger`): the client pays a
fixed amount and gets that many credits (**1 credit = ₹1**, always, `CREDIT_INR`). What a
bigger pack buys is not more credits — it is a **CHEAPER MINUTE**.

⚠ **THIS MODULE USED TO SAY "the list rate never changes; the bonus is the only thing that
moves the effective per-minute price down", AND THAT IS NO LONGER TRUE OF ANY PACK.** Until
this change a pack granted `paid x bonus_pct` BONUS credits at a single list rate, and the
effective rate was `list_rate / (1 + bonus)` — a discount expressed as extra rupees in the
wallet. The founder replaced it with a falling rate (§2.2 of
`docs/PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md`) for two reasons that the bonus shape could not
serve: a rate can differ PER VOICE (a Cartesia minute costs us more than a Sarvam one, so
it must cost the client more), and a rate can be FROZEN ON A PURCHASE (Phase B's lot),
which bonus credits sitting in one undifferentiated balance never could.

THE MODEL, in one paragraph
---------------------------
Every pack carries `clear_inr_per_min` and `studio_inr_per_min`. Which one prices a call
is a property of the AGENT that took it — its voice tier, derived from the voice's provider
(`rates.VoiceTier`, plan §2.3.7) — never of the wallet. So the same 15,000 credits buy
3,750 minutes on a Clear agent and 2,459 on a Studio one, and the wallet screen quotes
both (plan Q7). `bonus_pct` is zero on every pack and is retained ONLY as the deprecated
field named in §10; nothing sets it and nothing new may read it.

WHY A STATIC CODE CATALOGUE, NOT A TABLE
----------------------------------------
The catalogue is six founder-set prices that hold a cost-floor invariant checked in CI. It
is NOT operator-editable: a pack whose rate an operator could lower from a console is a
pack whose margin guard an operator could silently break, and the whole point of
`tests/credit_packs_test.py` is that moving a rate is a code change a reviewer sees and CI
scores. A DB table would move the numbers out of the guard's reach for nothing gained —
there is no per-tenant pack, no scheduling, no A/B. So this is code (D-39: a migration is
built only when the schema genuinely needs one, and a static pricing constant does not).
`platform_list_rates` still records WHEN a card came into force (`billing/list_rates.
record_card`) — that is history, not an edit surface.

THE MARGIN INVARIANT — TWO FLOORS, AND IT IS A COST FLOOR, NOT A TARGET
----------------------------------------------------------------------
Each of a pack's two rates is judged against ITS OWN voice's cost floor ON THE ENGINE THE
DEPLOYMENT RUNS (`rates.cost_floor_inr_per_min(voice, engine=...)`, D-681), because the
Studio floor is the dearer one and a minute costs us different amounts on different engines.
The verdict shape is `rates.rate_margin`, shared with the committed-bundle guard (D-469) so
a screen and a test cannot disagree about what "thin" means:

* **below cost is a REFUSAL** — `card_refusals` names it, `tests/credit_packs_test.py`
  fails on it, and the ops console will not write a card containing it.
* **below `MIN_GROSS_MARGIN` is a WARNING.** The founder's card of 14 Sep 2026 (Clear flat
  ₹4.00, Studio 7.00 → 5.50) earns, per engine:

      ThinnestAI  Clear 31.3% (₹2.75)    Studio 32.7% → 14.4% (₹4.7099; not sold there yet)
      Pipecat     Clear  7.8% (₹3.6891)  Studio 25.0% →  4.5% (₹5.2499, carrier included)

  Nothing is below COST. The thin cells are a deliberate opening price, not a defect.
  ⚠ **DO NOT "FIX" A THIN CELL BY MOVING A RATE** — that is a pricing decision, not a test
  failure.

Invariant 6 (plan §2.3) is checked here too: on every pack `cartesia >= sarvam`, and
neither column RISES as `amount_inr` rises. ⚠ It is "never rises", not "always falls": the
Clear column is FLAT at ₹4.00 across all six rungs since 14 Sep 2026, and a guard written
as strict descent would refuse the card that is on sale. A card that inverts either is
refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Final

from apps.api.billing.rates import (
    MIN_GROSS_MARGIN,
    MONEY_Q,
    PREMIUM_VOICE_TIER,
    ROUNDING,
    VALUE_VOICE_TIER,
    VOICE_TIERS,
    RateMargin,
    VoiceTier,
    cost_floor_inr_per_min,
    rate_margin,
)
from apps.api.core.settings import get_settings

# The gross-margin floor and its formula are HOISTED to `billing/rates.py` and imported
# here (D-469): the committed-volume bundle plans check the SAME invariant against the
# SAME cost floor, and one constant in the lowest money module is the only way the two
# guards cannot drift. Re-exported through this module's `__all__` so
# `from billing.credit_packs import MIN_GROSS_MARGIN` — the spelling
# `tests/credit_packs_test.py` uses — keeps working unchanged.

# 1 credit = ₹1. A named constant rather than a bare `1` so the identity is greppable and
# every derivation that assumes it (paid_credits, the talk-time algebra) points here.
CREDIT_INR: Final[Decimal] = Decimal("1")

# The `meta.kind` every bonus ledger entry carries, mirroring `service.ADJUSTMENT_META_KIND`:
# the ledger `reason` is the coarse enum ('bonus'), and this names the exact promotion so an
# auditor reading the row knows it was a pack bonus and which pack funded it.
#
# ⚠ NOTHING WRITES A NEW ONE. No pack carries a bonus since D-547; this constant and its
# clawback twin stay for the rows already on the append-only ledger and for the reversal
# path that still has to be able to recognise them (hard rule 8's two-step: the writer goes
# in Phase B, the reason and these kinds in release 2, plan §10).
PACK_BONUS_META_KIND: Final[str] = "credit_pack_bonus"

# The `meta.kind` on the entry that takes a pack bonus BACK when the purchase that earned it
# is refunded. Its own kind rather than a flag on the grant's, because the grant row is on an
# append-only ledger and cannot be annotated (hard rule 4) — and because "how much of this
# pack's bonus has already been reversed" has to be a query, which it is only if the rows
# that reverse it are recognisable without reading their sign.
PACK_BONUS_CLAWBACK_META_KIND: Final[str] = "credit_pack_bonus_clawback"

#: The client's words for the two rows above. Both are `reason = 'bonus'`, so without these
#: the clawback would read as a bonus with a minus sign, which says nothing about why.
PACK_BONUS_LABEL: Final[str] = "Bonus credit with your pack"
PACK_BONUS_CLAWBACK_LABEL: Final[str] = "Pack bonus taken back after a refund"


@dataclass(frozen=True, slots=True)
class CreditPack:
    """One purchasable pack: an amount, and one per-minute rate per voice tier.

    Both rates are the founder-approved card of 14 Sep 2026 and are stated in the card's own
    unit (₹/min at `MONEY_Q` precision), so the constant a reviewer reads is the constant
    the guard scores and the constant a lot freezes.
    """

    #: Stable identifier carried through the payment provider's `notes` and stamped on the
    #: lot the purchase opens. Never reused or renumbered: a historical `usage_events` /
    #: `credit_ledger` row read back must always resolve to the pack that produced it.
    pack_id: str
    #: What the client pays, in rupees. Equal to the credits granted (1 credit = ₹1).
    amount_inr: Decimal
    #: ₹/min for a call taken by an agent on the CLEAR rung. ⚠ This line named a VENDOR
    #: ("the Sarvam (Bulbul v3) voice") until 19 Sep 2026, and by then the vendor was
    #: wrong: the Sarvam TTS leg was withdrawn on 18 Sep and Gnani `timbre-v2.5` serves
    #: this rung (D-629). A pack sells a RUNG — which vendor speaks it is ours to change
    #: and has changed once already — so the field is documented by what the client bought.
    clear_inr_per_min: Decimal
    #: ₹/min for a call taken by an agent on the STUDIO rung (Cartesia Sonic 3.5 today).
    #: Never below the Clear rate — invariant 6, checked by `card_refusals`.
    studio_inr_per_min: Decimal
    #: The single "best value" badge (the deepest pack). Exactly one pack carries it; pinned
    #: by `tests/credit_packs_test.py`.
    best_value: bool = False
    #: ⚠ **DEPRECATED, ZERO ON EVERY PACK, AND SCHEDULED FOR REMOVAL (plan §10).** The
    #: volume bonus as a percent, before D-547 replaced it with the two rates above. It
    #: survives one release because `billing/payments.py::_grant_pack_bonus` — Phase B's
    #: file, not this one — still reads `bonus_credits`, and hard rule 8 forbids deleting a
    #: field in the same release that stops writing it. Nothing new may read it.
    bonus_pct: Decimal = Decimal("0")

    def inr_per_min(self, voice: VoiceTier) -> Decimal:
        """This pack's rate for one voice tier. THE ONE DOOR to a pack's rate.

        Total over the `VoiceTier` Literal and raising on anything else: a lookup that
        defaulted to the cheaper column would undercharge for a Cartesia minute silently,
        which is the one direction this rate must never fail in.
        """
        if voice == VALUE_VOICE_TIER:
            return self.clear_inr_per_min
        if voice == PREMIUM_VOICE_TIER:
            return self.studio_inr_per_min
        raise ValueError(f"{voice!r} is not a voice tier this card prices")

    @property
    def paid_credits(self) -> Decimal:
        """Credits bought outright. 1 credit = ₹1, so this is the amount paid."""
        return (self.amount_inr * CREDIT_INR).quantize(MONEY_Q, rounding=ROUNDING)

    @property
    def bonus_credits(self) -> Decimal:
        """⚠ DEPRECATED, ₹0 on every pack. See `bonus_pct`; retained for one release
        because `billing/payments.py` still calls it and returns early on a zero."""
        return (self.paid_credits * self.bonus_pct / Decimal(100)).quantize(
            MONEY_Q, rounding=ROUNDING
        )

    @property
    def total_credits(self) -> Decimal:
        """Everything the wallet receives for this pack. Equal to `paid_credits` now that
        no pack carries a bonus, and still written as the sum so the one reader that has
        not moved yet (`billing/payments.py`) keeps its arithmetic."""
        return self.paid_credits + self.bonus_credits


#: THE RATE CARD (founder sign-off, 14 Sep 2026 — `docs/PIPECAT-MIGRATION.md` §12). Six
#: rungs from ₹2,000 to ₹50,000, each with a Clear and a Studio ₹/min.
#: Three properties are deliberate:
#:
#: * **The Clear column is FLAT at ₹4.00** across all six rungs. It used to fall 5.00 →
#:   4.50; the founder replaced the ladder with one number (14 Sep 2026 — the decision is
#:   recorded, its rationale is not, so none is invented here). What the code can say is
#:   that the Clear floor does not amortise the way the Studio one does: every Clear leg is
#:   a per-minute or per-character published price, with no monthly allotment to spread, so
#:   a falling Clear rate would have been a discount against a cost that never fell. The
#:   `starter` rung's Clear rate is what `CreditPacksOut.list_rate_inr_per_min` publishes;
#:   flat means that number now describes every rung.
#: * **The Studio column still falls**, 7.00 → 5.50 in even ₹0.30 steps, a 21.4% fall.
#:   Cartesia's cost is a monthly SUBSCRIPTION with an included allotment, so the
#:   per-minute cost of a Cartesia minute really does fall as volume amortises the fee
#:   (`rates.cartesia_cost_inr_per_call_minute`), and the card passes that shape on. ⚠ It
#:   does not fall for ever: past the allotment the vendor's overage rate applies and the
#:   curve turns back up towards `rates.CARTESIA_COST_FLOOR_INR_PER_MIN`, which is why
#:   every rung carries a break-even volume
#:   (`rates.cartesia_rung_breakeven_call_minutes`) and the ops console prints it.
#: * **SEVERAL CELLS EARN UNDER 20%, ON PURPOSE** — which ones depends on the engine's
#:   floors (module docstring). Nothing is below COST, so the console warns rather than
#:   refuses. It is the founder's opening price to win the first clients.
#:
#: ⚠ **THE BONUS PERCENTAGES ARE GONE, NOT SET TO ZERO BY OVERSIGHT.** They were the margin
#: model until D-547 (`effective = list / (1 + bonus)`); the rates below ARE the margin
#: model now, and `card_refusals` scores them directly against `rates.cost_floor_inr_per_min`
#: for each voice rather than against a derived effective rate.
PACK_CATALOGUE: Final[tuple[CreditPack, ...]] = (
    CreditPack(
        pack_id="starter",
        amount_inr=Decimal("2000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("7.00"),
    ),
    CreditPack(
        pack_id="growth",
        amount_inr=Decimal("5000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("6.70"),
    ),
    CreditPack(
        pack_id="scale",
        amount_inr=Decimal("10000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("6.40"),
    ),
    CreditPack(
        pack_id="plus",
        amount_inr=Decimal("15000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("6.10"),
    ),
    CreditPack(
        pack_id="pro",
        amount_inr=Decimal("25000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("5.80"),
    ),
    CreditPack(
        pack_id="max",
        amount_inr=Decimal("50000"),
        clear_inr_per_min=Decimal("4.00"),
        studio_inr_per_min=Decimal("5.50"),
        best_value=True,
    ),
)

_BY_ID: Final[dict[str, CreditPack]] = {pack.pack_id: pack for pack in PACK_CATALOGUE}


def pack_by_id(pack_id: str) -> CreditPack | None:
    """The pack for this id, or None. Total and never raising: a `pack_id` read back off a
    historical ledger/notes value that this build no longer offers must resolve to "unknown"
    rather than blow up a crediting or rendering path (the same client-favouring asymmetry
    `rates.is_surchargeable_llm_model` applies to a forgotten model)."""
    return _BY_ID.get(pack_id)


def pack_paid_for(pack_id: str | None, amount_inr: Decimal) -> CreditPack | None:
    """The pack a payment of `amount_inr` actually bought, or None.

    A pack's rates and bonus are the price of paying the PACK's amount, so a payment is
    honoured as a pack only when it paid exactly that. The id alone is not evidence: it
    arrives in the provider's `notes`, which the browser authors whenever no server-side
    order exists (`create_topup_intent` hands the notes to the checkout), so without this
    check ₹100 carrying the ₹50,000 pack's id opened a lot at that pack's minute rate.
    Anything else is a free amount and is priced by what was paid
    (`service.RateCard.for_amount`), which can never beat the pack the client did not buy.
    """
    pack = pack_by_id(pack_id) if pack_id is not None else None
    if pack is None or pack.amount_inr != amount_inr:
        return None
    return pack


def pack_talk_time_minutes(pack: CreditPack, *, voice: VoiceTier) -> Decimal:
    """How many minutes of calling this pack's credits buy on one voice, EXACT.

    ``total_credits / rate``. Unquantized; callers that display it round once with the
    money layer's explicit mode (`payment_routes._pack_out` floors, because a client does
    not buy a fraction of a minute and rounding UP would advertise talk time the credits
    do not cover).
    """
    return pack.total_credits / pack.inr_per_min(voice)


def deployment_engine() -> str:
    """The engine this deployment runs (`Settings.engine`), whose floors a card is judged at."""
    return get_settings().engine


def pack_rate_margin(
    pack: CreditPack, *, voice: VoiceTier, engine: str | None = None
) -> RateMargin:
    """The margin verdict for one pack on one voice, against THAT voice's cost floor.

    The cost comes from `rates.cost_floor_inr_per_min(voice)` rather than being passed in,
    which is the opposite of what this function's predecessor did — and deliberately. With
    one floor a caller could not get it wrong; with two, a caller passing the cost is a
    caller that can pass the Clear floor for a Studio rate, and that mistake always
    passes (the Clear floor is the lower one). The pairing is made here, once.

    `engine` defaults to the one this deployment runs, whose floors the card is sold at.
    """
    floor = cost_floor_inr_per_min(voice, engine=engine or deployment_engine())
    return rate_margin(pack.inr_per_min(voice), cost=floor)


def card_margins(
    card: tuple[CreditPack, ...] = PACK_CATALOGUE, *, engine: str | None = None
) -> tuple[tuple[str, VoiceTier, RateMargin], ...]:
    """Every `(pack_id, voice, verdict)` on a card, in card order then voice order.

    THE PREVIEW. The ops console renders it before writing a card
    (`ops/config_routes._record_card`) and `tests/credit_packs_test.py` asserts over it, so
    the twelve numbers an operator is shown are the twelve numbers CI scored.
    """
    judged_at = engine or deployment_engine()
    return tuple(
        (pack.pack_id, voice, pack_rate_margin(pack, voice=voice, engine=judged_at))
        for pack in card
        for voice in VOICE_TIERS
    )


def card_refusals(
    card: tuple[CreditPack, ...] = PACK_CATALOGUE, *, engine: str | None = None
) -> list[str]:
    """Why this card may not be sold — empty when it may. Each string names one break.

    TWO KINDS, and both are refusals rather than warnings because both mean the card is
    wrong rather than thin:

    1. **A rate below its voice's cost floor.** Selling a minute for less than it costs us
       is not a pricing decision, it is a leak; `MIN_GROSS_MARGIN` is a target and being
       under it is reported by `card_margins`, not refused (see the module docstring).
    2. **Invariant 6 (plan §2.3.6)** — `cartesia >= sarvam` on every pack, and neither
       column rising as `amount_inr` rises. A card where a bigger pack buys a dearer minute
       is a card a client can arbitrage by buying the smaller one twice.
    """
    failures = [
        f"pack {pack_id!r} sells a {voice} minute at ₹{verdict.rate} against a "
        f"₹{verdict.cost} cost floor — below cost"
        for pack_id, voice, verdict in card_margins(card, engine=engine)
        if verdict.below_cost
    ]
    failures += [
        # NAMED FOR THE RUNGS, not for the vendors serving them — this sentence read
        # "prices Cartesia ... and Sarvam" until 19 Sep 2026, and by then Sarvam did not
        # synthesise at all (D-629) while the operator's console, the wire and the lot
        # columns all said `clear` / `studio` (D-630). A refusal an operator has to
        # translate is a refusal they cannot act on.
        f"pack {pack.pack_id!r} prices Studio at ₹{pack.studio_inr_per_min} and Clear "
        f"at ₹{pack.clear_inr_per_min}: the dearer rung may not be the cheaper rate "
        "(invariant 6)"
        for pack in card
        if pack.studio_inr_per_min < pack.clear_inr_per_min
    ]
    ordered = sorted(card, key=lambda pack: pack.amount_inr)
    failures += [
        f"pack {bigger.pack_id!r} (₹{bigger.amount_inr}) sells a {voice} minute at "
        f"₹{bigger.inr_per_min(voice)}, dearer than {smaller.pack_id!r} "
        f"(₹{smaller.amount_inr}) at ₹{smaller.inr_per_min(voice)}: a bigger pack never "
        "buys a dearer minute (invariant 6)"
        for smaller, bigger in pairwise(ordered)
        for voice in VOICE_TIERS
        if bigger.inr_per_min(voice) > smaller.inr_per_min(voice)
    ]
    return failures


__all__ = [
    "CREDIT_INR",
    "MIN_GROSS_MARGIN",
    "PACK_BONUS_CLAWBACK_LABEL",
    "PACK_BONUS_CLAWBACK_META_KIND",
    "PACK_BONUS_LABEL",
    "PACK_BONUS_META_KIND",
    "PACK_CATALOGUE",
    "CreditPack",
    "card_margins",
    "card_refusals",
    "deployment_engine",
    "pack_by_id",
    "pack_paid_for",
    "pack_rate_margin",
    "pack_talk_time_minutes",
]
