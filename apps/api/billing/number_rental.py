"""The RECURRING cost of a phone number — the one this product had no home for (D-537).

**WHY THIS EXISTS AT ALL.** Every cost this platform records is per-CALL: a call happens,
`pipeline._meter` writes `usage_events` rows keyed on `call_id`, and a month with no calls
costs nothing. A phone number is not that shape. It is charged monthly whether anybody
rings it or not, it is charged for a client who has stopped using the product, and it is
charged by a vendor whose invoice nobody in this system reads. An unbilled monthly cost
per client is a margin leak that compounds silently — it has no incident, no alarm and no
bound — and it was the founder's own question about this decision.

**THE HOME ALREADY EXISTED AND WAS EMPTY.** `usage_events.unit_type` has carried
`number_rental` since the ledger shipped, in `CLIENT_BILLED_UNIT_TYPES`, with NO WRITER —
correctly, while Model B meant a client rented their number from their own operator and
Calevate never paid for it. `billing/attribution.UnattributedCost` was built for exactly
this row ("`number_rental` is the whole of it and NOTHING WRITES ONE") and so was the
second partial unique index, `ux_usage_events_tenant_unit_ref` on
`(tenant_id, unit_type, ref)` where `ref IS NOT NULL AND call_id IS NULL`. So this module
adds no table, no column and no index: it is the writer three earlier pieces of work
already made room for, which is why a callless cost lands in every total that claims to be
a partition and breaks none of them.

MONEY (hard rule 7)
-------------------
* **NUMERIC INR, never float.** The vendor quotes dollars; `phone_numbers
  .monthly_rental_usd` holds the dollars as `NUMERIC(12,4)`, and the rupee is computed
  here, once, and stored in `unit_cost_paid`.
* **THE RATE IS THE MONTH'S, NOT THE PURCHASE'S.** Bolna debits its wallet in dollars on
  the renewal date, so our rupee cost genuinely differs month to month. Freezing the
  purchase-day rate onto the row would produce a ledger that disagrees with the bank by a
  little, for ever, in a direction nobody could reconstruct. `core/fx.usd_inr_rate_now` is
  the one door, and which rate was used is stamped into `meta` because an append-only row
  cannot be corrected in place (hard rule 4) and the only way it is ever explained later is
  that it says so itself.
* **`qty` IS ONE MONTH.** Not thirty days and not a proration: the vendor charges a whole
  month on the renewal date and stops charging when the number is deleted. A fractional
  first month would be a number we invented; `released_at` is what makes the last month
  stop, and the month a number is released in is charged in full because the vendor
  charged it in full.
* **THIS IS OUR COST, NOT A PRICE.** `unit_cost_paid` is what Calevate paid. Whether the
  rental is absorbed, passed through at cost, or a priced add-on is a founder pricing
  decision that is NOT taken here and is OPERATIONS §2 gate 26's other half. Recording the
  cost is what makes that decision possible; inventing a margin on it would be pricing by
  accident.

⚠ **THE PRICE IS THE VENDOR'S QUOTE AT PURCHASE, AND A VENDOR PRICE RISE IS NOT SEEN BY
THIS MODULE.** `monthly_rental_usd` is whatever the search result the operator accepted
said (`bolna-findings/mirror/pages/api-reference/phone-numbers/search.md:126-133`). Their
listing endpoint reports a current `price` per number (`get_all.md:103-106`) and
`workers/number_rental.py::reconcile_engine_numbers` compares the two and alarms —
this module deliberately does not fetch, because a meter that makes a vendor call cannot
run inside the caller's transaction and a rate limit must never be able to skip a charge.

IDEMPOTENT IN THE DATABASE, NOT IN AN `IF`
-------------------------------------------
`ref` is `number_rental:<number_id>:<YYYY-MM>` and the insert is `ON CONFLICT … DO
NOTHING` against the index predicate spelled verbatim. The failure this survives is the
same tick arriving twice — a retried job, two workers, a month boundary crossed
mid-run — and a check-then-write would let both copies read "not metered yet". The
namespace is OURS and is validated rather than trusted, for `ai_quota.ASSIST_REF_PREFIX`'s
reason: idempotency is a switch that turns metering OFF, so a key any caller could supply
is a way to make a cost disappear.

NO PII (hard rule 6). The `meta` carries the number's ROW id, never the E.164 — a phone
number is exactly what rule 6 names, and a ledger is the last place to put one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.ai_quota import INDEX_PREDICATE
from apps.api.billing.plans import parse_billing_month
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.core.fx import usd_inr_rate_now
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

#: The `usage_events.unit_type` this module writes, and the only one it may.
RENTAL_UNIT_TYPE: Final = "number_rental"

#: The `usage_events.ref` namespace this module owns: `number_rental:<uuid>:<YYYY-MM>`.
#: Validated rather than trusted (module docstring) — and the SHAPE is what makes the
#: idempotency meaningful: one row per number per IST billing month, decided by the
#: database's unique index and not by anybody's read.
RENTAL_REF_PREFIX: Final = "number_rental:"
_REF_RE: Final = re.compile(r"^number_rental:[0-9a-f-]{36}:\d{4}-\d{2}$")


def rental_ref(number_id: UUID, month: str) -> str:
    """THE key. One number, one IST billing month, one charge.

    `parse_billing_month` is called for its refusal, not its value: a caller that passed
    `"2026-13"` would otherwise mint a key no month will ever collide with and charge the
    same rental twice.
    """
    parse_billing_month(month)
    return f"{RENTAL_REF_PREFIX}{number_id}:{month}"


@dataclass(frozen=True, slots=True)
class RentalMetered:
    """What one month's rental cost us, and whether this call is what recorded it.

    `recorded` is False for a replay — the row was already there — and the caller must not
    treat that as an error or as a second charge. It is returned rather than swallowed
    because a job that reports "metered 40 numbers" when 39 were replays is a job whose
    output means nothing.
    """

    ref: str
    cost_inr: Decimal
    recorded: bool


_INSERT_RENTAL = f"""
INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid,
                          ref, occurred_at, meta, created_at)
VALUES (:id, :tid, NULL, :unit, 1, :cost, :ref, now(), CAST(:meta AS jsonb), now())
ON CONFLICT (tenant_id, unit_type, ref) WHERE {INDEX_PREDICATE}
DO NOTHING
RETURNING id
"""


def rental_inr(monthly_rental_usd: Decimal) -> tuple[Decimal, str, str | None]:
    """One month's rental in rupees, plus the rate's provenance.

    Quantized at `MONEY_Q` with `ROUNDING` — the storage quantum and mode this repository
    has exactly one spelling of — because `unit_cost_paid` is NUMERIC(12,4) and a value
    that does not fit it is rounded by the database silently, at whatever mode the server
    happens to use.
    """
    resolved = usd_inr_rate_now(get_settings().usd_inr_rate)
    cost = (monthly_rental_usd * resolved.rate).quantize(MONEY_Q, rounding=ROUNDING)
    return cost, resolved.source, resolved.as_of.isoformat() if resolved.as_of else None


async def record_number_rental(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    number_id: UUID,
    month: str,
    monthly_rental_usd: Decimal,
    provider: str | None,
) -> RentalMetered:
    """Meter ONE number's rental for ONE IST billing month. The only writer of the unit.

    Commits in the CALLER's transaction, like every other meter in this system: a rental
    recorded whose surrounding work rolled back is a charge against a number nobody
    bought.

    A ZERO OR NEGATIVE RENTAL IS REFUSED RATHER THAN RECORDED. A zero is not a free number
    — it is a price we failed to read (the vendor's `price` was missing, or was quoted in a
    currency this product refuses), and writing it would put a permanent ₹0 into an
    append-only ledger that no later correction can replace. The caller alarms instead.
    """
    if monthly_rental_usd <= 0:
        raise ValueError(
            f"a rental of {monthly_rental_usd} USD is not a price; refusing to meter a "
            "number whose cost could not be read"
        )
    ref = rental_ref(number_id, month)
    if not _REF_RE.match(ref):  # pragma: no cover - `rental_ref` is the only mint
        raise ValueError("a number rental ref must be minted by `rental_ref`")
    cost, fx_source, fx_as_of = rental_inr(monthly_rental_usd)
    # Hard rule 6: the number's ROW id and the carrier, never the E.164.
    meta = {
        "number_id": str(number_id),
        "provider": provider,
        "month": month,
        "source_usd": str(monthly_rental_usd),
        "fx_source": fx_source,
        "fx_as_of": fx_as_of,
    }
    row = (
        await session.execute(
            text(_INSERT_RENTAL),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "unit": RENTAL_UNIT_TYPE,
                "cost": cost,
                "ref": ref,
                "meta": json.dumps(meta),
            },
        )
    ).first()
    recorded = row is not None
    log.info(
        "number_rental_metered",
        extra={"number_id": str(number_id), "month": month, "recorded": recorded},
    )
    return RentalMetered(ref=ref, cost_inr=cost, recorded=recorded)


__all__ = [
    "RENTAL_REF_PREFIX",
    "RENTAL_UNIT_TYPE",
    "RentalMetered",
    "record_number_rental",
    "rental_inr",
    "rental_ref",
]
