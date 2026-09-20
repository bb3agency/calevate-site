"""What a client pays for a number-month, in rupees — an attestation, never a constant.

**HARD RULE 7, APPLIED WHERE IT HAS NOT BEEN APPLIED BEFORE.** Every other vendor figure
that reaches a bill in this product goes through an operator's attestation:
`billing/rates.llm_inr_per_ktok` opens only on an attested or read figure and RAISES
otherwise, and `agents/voice_offer.tts_price_is_billable` refuses to sell a voice whose
minute nobody has priced. A phone number's monthly rental is the same class of fact and
had no such door, because until a client could buy one there was no client-facing price
at all — only OUR cost, which `billing/number_rental.py` meters from the vendor's USD
quote.

**THE VENDOR'S QUOTE IS NOT THIS NUMBER, AND MUST NOT BE TURNED INTO IT.** The engine's
search returns a `price` described as *"Price of the number in USD"*
(VERIFIED-VENDOR-DOCS: `bolna-findings/mirror/pages/api-reference/phone-numbers/
search.md:122-127`) — that is what Calevate is charged. What a client is charged is a
pricing decision nobody has taken (OPERATIONS §2 gate 26), so converting the vendor quote
at some exchange rate and adding some margin would be taking it by accident, in code.
Until an operator records a rupee figure they can point at, `attested_price_inr` is None
and every purchase refuses.

⚠ **THE CARRIER'S OWN PUBLISHED INDIAN DID PRICE IS UNKNOWN HERE.** `www.plivo.com` is
egress-blocked from this container (measured 20 Sep 2026, curl exit with HTTP 000 through
the egress proxy for the docs, API and pricing hosts), so no per-month figure was read
this session and none is invented. That is exactly the gap this module routes to a human
rather than filling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import ROUNDING
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

NO_PRICE_RULE: Final = "number_price_not_attested"


@dataclass(frozen=True, slots=True)
class AttestedNumberPrice:
    """The live rate, and what it was read from."""

    id: UUID
    inr_per_month: Decimal
    source: str
    attested_at: datetime


_LATEST = (
    "SELECT id, inr_per_month, source, created_at FROM number_price_attestations "
    "ORDER BY created_at DESC, id DESC LIMIT 1"
)


async def attested_price_inr(session: AsyncSession) -> AttestedNumberPrice | None:
    """The newest attested rate, or None when nobody has recorded one.

    Ordered by `id` after `created_at` because two rows written in one transaction share
    `now()` and uuid7 is time-ordered, so the tiebreak is still chronological — the same
    reasoning `sender_attestation.latest_attestation` gives.

    NOT CACHED. It is read on a purchase, which is a rare, money-spending request, and a
    snapshot refreshed on a poll would let a number be sold at a rate an operator changed
    thirty seconds ago and can no longer point at.
    """
    row = (await session.execute(text(_LATEST))).first()
    if row is None:
        return None
    return AttestedNumberPrice(
        id=row[0], inr_per_month=Decimal(row[1]), source=str(row[2]), attested_at=row[3]
    )


async def require_attested_price_inr(session: AsyncSession) -> AttestedNumberPrice:
    """The rate, or the refusal. Raises; writes nothing.

    The client-facing text names no setting, no table and no vendor: which of OUR figures
    is missing is an internals leak, and it is not a thing they can act on.
    """
    price = await attested_price_inr(session)
    if price is None:
        raise ProblemError(
            kind="dependency",
            code=NO_PRICE_RULE,
            title="We cannot quote a price for a number yet",
            detail=(
                "What a phone number costs per month has not been set, so none can be "
                "bought. Nothing has been charged."
            ),
            remediation=(
                "Talk to us and we will confirm the monthly price before the number is bought."
            ),
        )
    return price


async def record_attested_price_inr(
    session: AsyncSession, *, inr_per_month: Decimal, source: str, attested_by: UUID
) -> AttestedNumberPrice:
    """Append one attestation. INSERT-only (hard rule 4); a rate change is a new row.

    `source` is required and non-blank at the CHECK constraint, because hard rule 11 wants
    the evidence to travel with the claim: a rupee figure with nothing behind it is the
    figure a later session repeats as though somebody had read an invoice.
    """
    # `rounding=` stated, never the process-global context: that default is
    # ROUND_HALF_EVEN and any library in the image can mutate it, so an attested
    # price could quantize differently between two deployments of the same code.
    # `billing.rates.ROUNDING` is the one answer money uses here.
    amount = Decimal(inr_per_month).quantize(Decimal("0.01"), rounding=ROUNDING)
    if amount <= 0:
        raise ProblemError.business_rule(
            "number_price_not_positive",
            "A monthly price has to be more than zero.",
            remediation="Record the figure the carrier's invoice or order form states.",
        )
    await session.execute(
        text(
            "INSERT INTO number_price_attestations (id, inr_per_month, source, attested_by) "
            "VALUES (:id, :amount, :source, :uid)"
        ),
        {"id": uuid7(), "amount": amount, "source": source.strip(), "uid": attested_by},
    )
    recorded = await attested_price_inr(session)
    assert recorded is not None  # written one statement ago, in this transaction
    return recorded


__all__ = [
    "NO_PRICE_RULE",
    "AttestedNumberPrice",
    "attested_price_inr",
    "record_attested_price_inr",
    "require_attested_price_inr",
]
