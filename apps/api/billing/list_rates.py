"""WHAT A PUBLISHED LIST RATE WAS AT AN INSTANT, and who published it (D-492).

`Settings.self_serve_inr_per_min` is the self-serve motion's price for one calling minute.
It is ONE number with no history — `platform_settings` is keyed by `key`, so an operator's
change OVERWRITES the row — and until this module existed every reader of it answered
"what does a minute cost" with today's answer, including two whose question was "what did a
minute cost in the month I am rendering":

* `billing/service.calling_revenue_inr` priced a CLOSED month's minutes at the live setting.
  A prepaid client's settled statement, and the admin margin panel beside it, were therefore
  re-priced by every later rate move: 14.83 minutes rendered ₹88.98 and then ₹133.47 once
  the rate went 6 -> 9, for a month whose wallet debits had already been taken at ₹6.
* `workers/pipeline` debited a LATE-SETTLING call at the live setting while the
  `llm_surcharge` in the SAME expression was resolved at `month_pricing_instant`. A call
  that settles after the IST month rolls — the reconciliation poller's window, an ARQ retry
  ladder crossing midnight on the 1st — was charged at NEXT month's price.

`platform_list_rates` (migration d3b81f5c02ae) is where that number acquires a valid time.

THE RESOLUTION RULE IS `ops/model_pricing.attested_model_prices`', NOT A SECOND MECHANISM
------------------------------------------------------------------------------------------
"The row for this key with the greatest `effective_from <= T`", with `at` passed in rather
than defaulted to now — which instant to price at is the CALLER's fact
(`billing/plans.month_pricing_instant`: now while the month is open, the month's last
instant once it is closed). A published price has no natural `effective_to` — the next row
IS its end — so this is the `platform_model_prices` shape rather than `plans`' half-open
valid-time window, which exists there because a plan can END without a successor.

WHAT AN EMPTY TABLE MEANS, AND WHY IT IS NOT A BACKFILL (hard rule 11)
----------------------------------------------------------------------
Nobody ever recorded when the self-serve price last moved, so there is no history to write
down. Seeding a row at the beginning of time with today's figure would ASSERT that today's
price was in force in every past month, which is a claim nobody here can make — so the
table ships empty and `self_serve_rate_at` falls back to the live `Settings` value when no
row covers the instant. For those months the current rate is genuinely the only rate we
know; that is a stated limit, not a recorded fact, and it is the pre-existing behaviour
rather than a new one. History accrues from the first ops-console price change after this
lands (`ops/config_routes.py` writes the row in the same transaction as the setting).

Money is NUMERIC INR throughout (hard rule 7): every value in and out of here is a
`Decimal`, and nothing in this module rounds — the caller quantizes at its own quantum
(`billing/rates.MONEY_Q` for a wallet debit, `billing/service.to_paise` for a screen).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.settings import get_settings

#: The one key this table carries today: the name of the `Settings` field it dates, so the
#: two are related by a constant rather than by a matching pair of string literals.
SELF_SERVE_PER_MIN = "self_serve_inr_per_min"

_RATE_AT = (
    "SELECT inr_amount FROM platform_list_rates "
    "WHERE rate_key = :key AND effective_from <= :at "
    "ORDER BY effective_from DESC LIMIT 1"
)

_INSERT = (
    "INSERT INTO platform_list_rates "
    "(rate_key, effective_from, inr_amount, recorded_by, source_note) "
    "VALUES (:key, clock_timestamp(), :amount, :by, :note)"
)


async def self_serve_rate_at(session: AsyncSession, *, at: datetime) -> Decimal:
    """The self-serve price for one calling minute, as published at instant `at`.

    THE ONE ANSWER TO "WHAT DID A MINUTE COST IN MONTH M". Both money readers that price a
    period come here — the client's own statement/margin panel
    (`billing/service.calling_revenue_inr`) and the per-call wallet debit and spend counter
    (`workers/pipeline`) — so a closed month cannot be rendered at one rate on one screen
    and another on the next.

    `at` MUST be timezone-aware: it is compared against `effective_from`, which is
    `timestamptz`, and a naive instant would be read in the process's local timezone —
    a UTC container and an IST laptop would then price the same month differently. There
    is deliberately NO DEFAULT of `now()`: a default would silently re-price a closed month
    at today's terms, which is the entire defect this module exists for.

    WITH NO ROW ON OR BEFORE `at`, THE LIVE SETTING. See the module docstring: no history
    was ever recorded, so for a month before the first console price change the current rate
    is the only rate we know. This is the pre-existing behaviour preserved honestly rather
    than a backfill, and it is why landing this table re-prices nobody on the day it ships.
    """
    if at.tzinfo is None:
        raise ValueError("a list rate is resolved at an aware instant (timestamptz or UTC-aware)")
    row = (await session.execute(text(_RATE_AT), {"key": SELF_SERVE_PER_MIN, "at": at})).first()
    if row is None:
        return get_settings().self_serve_inr_per_min
    # `Decimal(str(...))` like every other money read in this package: psycopg returns
    # NUMERIC as Decimal already, and this costs nothing while making a driver that ever
    # returned something else fail loudly here rather than float its way into a wallet.
    return Decimal(str(row[0]))


async def record_list_rate(
    session: AsyncSession,
    *,
    rate_key: str,
    inr_amount: Decimal,
    recorded_by: UUID,
    note: str,
) -> None:
    """Append the rate that comes into force NOW, on the caller's transaction.

    Called from `ops/config_routes.py` in the SAME transaction as the `platform_settings`
    write it dates, so the price and the record of when it changed land together or neither
    does — money's rule (BACKEND-PATTERNS §4) applied to a published price.

    `effective_from` is `clock_timestamp()` and not `now()`: `now()` is transaction start
    time, and two rate rows written inside one transaction would then collide on the primary
    key. Nothing in this repository writes two, but the collision would be a 500 on an
    operator's Save rather than anything a reader could sort out, and the statement-clock is
    free.

    NO UPDATE, EVER — the table's trigger refuses one. A price correction is a NEW row at a
    later instant, which is what makes a re-rendered statement re-derivable rather than
    re-priced (`platform_list_rates`' migration argues it in full).
    """
    await session.execute(
        text(_INSERT),
        {"key": rate_key, "amount": inr_amount, "by": recorded_by, "note": note},
    )


__all__ = ["SELF_SERVE_PER_MIN", "record_list_rate", "self_serve_rate_at"]
