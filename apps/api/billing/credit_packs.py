"""Prepaid CREDIT PACKS with volume bonuses (founder-approved, Aug 2026).

The self-serve motion already has a wallet (`credit_ledger`), a list rate
(`self_serve_inr_per_min`, ₹5.00/min) and a top-up path (Razorpay → `billing/payments.py`).
A credit pack is a PRICING SHAPE on top of that path, modelled on Outpero's packs: the
client pays a fixed amount, and a larger amount buys proportionally MORE calling because it
grants BONUS credits on top of the paid ones. The list rate never changes; the bonus is the
only thing that moves the effective per-minute price down.

THE MODEL, in one paragraph
---------------------------
**1 credit = ₹1.** A call burns credits at the LIST rate (`self_serve_inr_per_min`), so
``talk_time_minutes = credits / list_rate``. A pack grants:

* **paid credits** = the rupees the client paid (1:1), and
* **bonus credits** = ``paid x bonus_pct`` — a promotional grant funded by us.

The client therefore holds ``paid x (1 + bonus_pct)`` credits for a spend of ``paid``, so
the price they actually pay per minute is::

    effective_rate = amount_paid / talk_time = amount_paid x list_rate / total_credits
                   = list_rate / (1 + bonus_pct)

The bonus is the whole lever, and the list rate is untouched — which is why usage metering,
the runway framing and every existing rate reader keep quoting ₹5.00/min unchanged.

WHY A STATIC CODE CATALOGUE, NOT A TABLE
----------------------------------------
The catalogue is five founder-set prices that hold a margin invariant checked in CI. It is
NOT operator-editable: a pack whose bonus an operator could raise from a console is a pack
whose ≥20%-margin guarantee (below) an operator could silently break, and the whole point of
`tests/credit_packs_test.py::test_every_pack_holds_the_gross_margin_floor` is that changing a
bonus is a code change a reviewer sees and CI scores. A DB table would move the numbers out
of the guard's reach for nothing gained — there is no per-tenant pack, no scheduling, no A/B.
So this is code (D-39: a migration is built only when the schema genuinely needs one, and a
static pricing constant does not). If packs ever become operator-editable the correct shape
is a table with RLS and this catalogue becomes its seed — but not before that need is real.

THE MARGIN INVARIANT
--------------------
Every pack must hold at least `MIN_GROSS_MARGIN` gross margin at our per-minute cost floor
(`rates.SELF_SERVE_COST_FLOOR_INR_PER_MIN`). The deepest pack sits closest to the floor, so
the guard is what stops a future "let's give the ₹50k pack 12%" from quietly selling minutes
below cost. The cost basis is read from the cost model in `rates.py`, never written as a
literal in the test, so it moves with the cost model and the guard re-scores when it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from apps.api.billing.rates import (
    MIN_GROSS_MARGIN,
    MONEY_Q,
    ROUNDING,
    gross_margin_ratio,
)

# The gross-margin floor and its formula are HOISTED to `billing/rates.py` and imported
# here (D-469): the committed-volume bundle plans now check the SAME invariant against the
# SAME cost floor, and one constant in the lowest money module is the only way the two
# guards cannot drift. Re-exported through this module's `__all__` so
# `from billing.credit_packs import MIN_GROSS_MARGIN` — the spelling
# `tests/credit_packs_test.py` uses — keeps working unchanged.

# 1 credit = ₹1. A named constant rather than a bare `1` so the identity is greppable and
# every derivation that assumes it (paid_credits, the effective-rate algebra) points here.
CREDIT_INR: Final[Decimal] = Decimal("1")

# The `meta.kind` every bonus ledger entry carries, mirroring `service.ADJUSTMENT_META_KIND`:
# the ledger `reason` is the coarse enum ('bonus'), and this names the exact promotion so an
# auditor reading the row knows it was a pack bonus and which pack funded it.
PACK_BONUS_META_KIND: Final[str] = "credit_pack_bonus"

# The `meta.kind` on the entry that takes a pack bonus BACK when the purchase that earned it
# is refunded. Its own kind rather than a flag on the grant's, because the grant row is on an
# append-only ledger and cannot be annotated (hard rule 4) — and because "how much of this
# pack's bonus has already been reversed" has to be a query, which it is only if the rows
# that reverse it are recognisable without reading their sign.
PACK_BONUS_CLAWBACK_META_KIND: Final[str] = "credit_pack_bonus_clawback"


@dataclass(frozen=True, slots=True)
class CreditPack:
    """One purchasable pack. Amounts and bonuses are the founder-approved rate card.

    `bonus_pct` is a PERCENT (``Decimal("8")`` = 8%), never a fraction — it is the number a
    human sets on the rate card, and keeping it in the card's own unit means the constant a
    reviewer reads is the constant the guard scores.
    """

    #: Stable identifier carried through the payment provider's `notes` and stamped on the
    #: bonus ledger row. Never reused or renumbered: a historical `usage_events`/`credit_ledger`
    #: row read back must always resolve to the pack that produced it.
    pack_id: str
    #: What the client pays, in rupees. Equal to the paid credits granted (1 credit = ₹1).
    amount_inr: Decimal
    #: Volume bonus as a percent of the paid amount.
    bonus_pct: Decimal
    #: The single "best value" badge (the deepest pack). Exactly one pack carries it; pinned
    #: by `tests/credit_packs_test.py`.
    best_value: bool = False

    @property
    def paid_credits(self) -> Decimal:
        """Credits bought outright. 1 credit = ₹1, so this is the amount paid."""
        return (self.amount_inr * CREDIT_INR).quantize(MONEY_Q, rounding=ROUNDING)

    @property
    def bonus_credits(self) -> Decimal:
        """Credits granted for free — the volume bonus. ``paid x bonus_pct``.

        Quantized to the ledger's storage quantum (`MONEY_Q`, NUMERIC(12,4)) because this
        value lands in `credit_ledger.delta`: a bonus the ledger cannot store exactly is a
        bonus that would be rounded on write, so it is rounded HERE, once, with the one
        explicit mode the money layer uses.
        """
        return (self.paid_credits * self.bonus_pct / Decimal(100)).quantize(
            MONEY_Q, rounding=ROUNDING
        )

    @property
    def total_credits(self) -> Decimal:
        """Everything the wallet receives for this pack: paid + bonus."""
        return self.paid_credits + self.bonus_credits


#: THE RATE CARD. Amounts mirror Outpero's packs; bonuses are founder-approved and capped so
#: every pack clears `MIN_GROSS_MARGIN` at the cost floor (see the guard). The ₹50,000 pack
#: takes 8% — the margin-safe end of the approved "8-9%" range: at 9% its effective rate
#: (₹4.587) dips below the 20%-margin line at a ₹3.70 cost floor, so 8% is the cap the
#: invariant permits and the guard enforces.
PACK_CATALOGUE: Final[tuple[CreditPack, ...]] = (
    CreditPack(pack_id="starter", amount_inr=Decimal("1499"), bonus_pct=Decimal("0")),
    CreditPack(pack_id="growth", amount_inr=Decimal("2999"), bonus_pct=Decimal("3")),
    CreditPack(pack_id="scale", amount_inr=Decimal("9999"), bonus_pct=Decimal("5")),
    CreditPack(pack_id="pro", amount_inr=Decimal("24999"), bonus_pct=Decimal("7")),
    CreditPack(pack_id="max", amount_inr=Decimal("50000"), bonus_pct=Decimal("8"), best_value=True),
)

_BY_ID: Final[dict[str, CreditPack]] = {pack.pack_id: pack for pack in PACK_CATALOGUE}


def pack_by_id(pack_id: str) -> CreditPack | None:
    """The pack for this id, or None. Total and never raising: a `pack_id` read back off a
    historical ledger/notes value that this build no longer offers must resolve to "unknown"
    rather than blow up a crediting or rendering path (the same client-favouring asymmetry
    `rates.is_surchargeable_llm_model` applies to a forgotten model)."""
    return _BY_ID.get(pack_id)


def pack_effective_rate_inr_per_min(pack: CreditPack, *, list_rate: Decimal) -> Decimal:
    """The price the client actually pays per minute on this pack, EXACT (unquantized).

    ``amount_paid x list_rate / total_credits``. Computed from the credits actually granted
    (not the closed-form ``list_rate / (1 + bonus)``) so the figure the guard scores and the
    figure a screen shows both reflect the real grant, bonus rounding and all. Unquantized
    because it feeds the margin ratio, which divides by it — rounding here would round twice.
    """
    return pack.amount_inr * list_rate / pack.total_credits


def pack_talk_time_minutes(pack: CreditPack, *, list_rate: Decimal) -> Decimal:
    """How many minutes of calling this pack's credits buy at the list rate, EXACT.

    ``total_credits / list_rate``. Unquantized; callers that display it round once with the
    money layer's explicit mode.
    """
    return pack.total_credits / list_rate


def pack_gross_margin_ratio(
    pack: CreditPack, *, list_rate: Decimal, cost_inr_per_min: Decimal
) -> Decimal:
    """Gross margin as a fraction of retail: ``(effective_rate - cost) / effective_rate``.

    This is the number the margin guard asserts against `MIN_GROSS_MARGIN`. The cost is
    supplied by the caller from the cost model (`rates.SELF_SERVE_COST_FLOOR_INR_PER_MIN`),
    never baked in here, so the invariant re-scores when the cost model moves. The
    `(effective - cost) / effective` formula is `rates.gross_margin_ratio` (D-469), shared
    with the committed-bundle guard so the two cannot disagree about what margin means.
    """
    effective = pack_effective_rate_inr_per_min(pack, list_rate=list_rate)
    return gross_margin_ratio(rate=effective, cost=cost_inr_per_min)


__all__ = [
    "CREDIT_INR",
    "MIN_GROSS_MARGIN",
    "PACK_BONUS_CLAWBACK_META_KIND",
    "PACK_BONUS_META_KIND",
    "PACK_CATALOGUE",
    "CreditPack",
    "pack_by_id",
    "pack_effective_rate_inr_per_min",
    "pack_gross_margin_ratio",
    "pack_talk_time_minutes",
]
