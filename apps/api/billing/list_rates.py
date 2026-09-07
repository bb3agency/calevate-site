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

AND SINCE D-547 IT DATES A CARD, NOT A NUMBER
--------------------------------------------
The self-serve motion no longer has ONE price: every credit pack carries a Sarvam and a
Cartesia ₹/min (`billing/credit_packs.PACK_CATALOGUE`), so what comes into force at an
instant is a twelve-cell CARD. `record_card` appends all of it under ONE `effective_from`
and `card_at` resolves it with the same greatest-`effective_from`-≤-`at` rule, per key.
Same table, same append-only trigger, same console writer — the only new thing is the key
shape, `pack:<pack_id>:<voice_tier>` (`pack_rate_key`), chosen so a card row is recognisable
by prefix and a future third voice needs no migration.

`SELF_SERVE_PER_MIN` KEEPS ITS ROW AND ITS READER (plan §10). `self_serve_rate_at` is what
`billing/service`, `billing/attribution` and `workers/pipeline` still price a closed month
with, and Phase B is what moves them onto lots; deleting the key in the same release that
stopped being the only price would break every one of them at once (hard rule 8). So
`record_card` writes it too, at the same instant, holding the same number it always held —
the `starter` pack's Sarvam rate.

Money is NUMERIC INR throughout (hard rule 7): every value in and out of here is a
`Decimal`, and nothing in this module rounds — the caller quantizes at its own quantum
(`billing/rates.MONEY_Q` for a wallet debit, `billing/service.to_paise` for a screen).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack
from apps.api.billing.rates import VOICE_TIERS, VoiceTier
from apps.api.core.settings import get_settings

#: The one key this table carries today: the name of the `Settings` field it dates, so the
#: two are related by a constant rather than by a matching pair of string literals.
SELF_SERVE_PER_MIN = "self_serve_inr_per_min"

_RATE_AT = (
    "SELECT inr_amount FROM platform_list_rates "
    "WHERE rate_key = :key AND effective_from <= :at "
    "ORDER BY effective_from DESC LIMIT 1"
)

_COLUMNS = "(rate_key, effective_from, inr_amount, recorded_by, source_note)"
_INSERT = (
    f"INSERT INTO platform_list_rates {_COLUMNS} "
    "VALUES (:key, clock_timestamp(), :amount, :by, :note)"
)
#: The same append with the instant SUPPLIED rather than taken from the statement clock —
#: `record_card` reads the clock once and binds it to every row, so a whole card shares one
#: `effective_from`. Derived from the same `_COLUMNS` literal as `_INSERT` so the two
#: statements cannot come to disagree about the column list (`check_raw_sql`'s rule: SQL is
#: built from literals in one place, never assembled from values).
_INSERT_AT = f"INSERT INTO platform_list_rates {_COLUMNS} VALUES (:key, :at, :amount, :by, :note)"


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
    """Append ONE rate that comes into force NOW, on the caller's transaction.

    ⚠ **THE OPS CONSOLE NO LONGER CALLS THIS; `record_card` DOES, AND IT WRITES THE LEGACY
    KEY ITSELF (D-547).** This survives as the one-row primitive — the shape a single-key
    correction takes, and what `tests/self_serve_list_rate_test.py` drives to prove the
    statement clock advances inside a transaction, which is the whole reason `record_card`
    reads the clock once instead of thirteen times. It is deliberately NOT what `record_card`
    is built on: that function needs one instant across every row and this one cannot give
    it, and pushing an `effective_from` parameter down here would put a card's requirement
    into the primitive that exists to not have one.

    Money's rule (BACKEND-PATTERNS §4) applies either way: the price and the record of when
    it changed land in the caller's transaction together or neither does.

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


#: The prefix every per-(pack, voice) card row's key carries. A row is a card row iff its
#: key starts with this, which is what makes `card_at` one query instead of twelve and what
#: lets a future third voice tier be added with no migration and no new key SHAPE.
PACK_RATE_KEY_PREFIX = "pack"

#: Every voice tier by its wire spelling. A dict rather than the `in VOICE_TIERS` membership
#: test it replaces because that test narrows nothing for the type checker, and the arm a
#: `cast` would need is an arm no test can reach — an unreachable branch in this package is
#: an uncovered unit the ratchet scores (`ledgers-and-money`, budget zero), and a coverage
#: suppression is forbidden here for exactly that reason -- it scores as an uncovered unit
#: too. The directive is described rather than spelled out on purpose: coverage's exclude
#: pattern matches it ANYWHERE on a line, so writing it inside this very sentence excluded
#: the constant below and cost this surface its zero.
_VOICE_BY_NAME: Final[Mapping[str, VoiceTier]] = {voice: voice for voice in VOICE_TIERS}


def pack_rate_key(pack_id: str, voice: VoiceTier) -> str:
    """`pack:<pack_id>:<voice_tier>` — the `platform_list_rates.rate_key` for one cell.

    Built by a function rather than written at each call site for `SELF_SERVE_PER_MIN`'s
    reason: the writer and the reader must agree on the spelling, and two string literals
    agreeing is a coincidence that survives until somebody renames a pack.
    """
    return f"{PACK_RATE_KEY_PREFIX}:{pack_id}:{voice}"


def _parse_pack_rate_key(rate_key: str) -> tuple[str, VoiceTier] | None:
    """The inverse, or None for a key this build cannot interpret.

    TOTAL AND NEVER RAISING, for `credit_packs.pack_by_id`'s reason: the rows are append-only
    history, so a card recorded by an older build can name a pack id or a voice tier this one
    has forgotten. That row is not a card cell we can resolve, and the honest answer is to
    skip it — not to fail a statement-rendering read on it.
    """
    prefix, _, rest = rate_key.partition(":")
    pack_id, _, name = rest.rpartition(":")
    voice = _VOICE_BY_NAME.get(name)
    if prefix != PACK_RATE_KEY_PREFIX or not pack_id or voice is None:
        return None
    return pack_id, voice


_CARD_AT = (
    "SELECT DISTINCT ON (rate_key) rate_key, inr_amount FROM platform_list_rates "
    "WHERE rate_key LIKE :prefix AND effective_from <= :at "
    "ORDER BY rate_key, effective_from DESC"
)

_NOW = "SELECT clock_timestamp()"


async def record_card(
    session: AsyncSession,
    *,
    card: Sequence[CreditPack] = PACK_CATALOGUE,
    self_serve_inr_per_min: Decimal,
    recorded_by: UUID,
    note: str,
) -> datetime:
    """Append a whole card — every (pack, voice) rate plus `SELF_SERVE_PER_MIN` — at ONE
    instant, on the caller's transaction. Returns the `effective_from` it stamped.

    **ONE INSTANT FOR THE WHOLE CARD, AND THAT IS THE REASON THIS IS NOT TWELVE CALLS TO
    `record_list_rate`.** That function stamps `clock_timestamp()` per statement, which is
    the STATEMENT clock and genuinely advances between statements inside one transaction. A
    card written that way would have twelve `effective_from` values microseconds apart, and
    a lot opened in that window would freeze a card that is half old and half new — a
    client charged the new Cartesia rate against the old Sarvam one. So the instant is read
    once, here, and bound to every row.

    ⚠ **THE CARD IS NOT VALIDATED HERE.** `credit_packs.card_refusals` is the guard, and the
    caller runs it (`ops/config_routes._record_card`) so the operator gets the refusal
    BEFORE anything is written and with every margin in it. A validation buried in the
    writer would be a 500 on a Save instead of an answer.

    NO UPDATE, EVER — the table's trigger refuses one, as it does for `record_list_rate`.
    A correction is a new card at a later instant, which is what makes a lot's frozen rates
    re-derivable rather than re-priced.
    """
    # `scalar_one()` is typed `Any` by SQLAlchemy, so the instant is bound to a declared
    # `datetime` here rather than returned straight through — mypy is strict and a
    # timestamp that reached a caller as `Any` is a timestamp nothing checks.
    at: datetime = (await session.execute(text(_NOW))).scalar_one()
    rows = [
        {
            "key": pack_rate_key(pack.pack_id, voice),
            "at": at,
            "amount": pack.inr_per_min(voice),
            "by": recorded_by,
            "note": note,
        }
        for pack in card
        for voice in VOICE_TIERS
    ]
    rows.append(
        {
            "key": SELF_SERVE_PER_MIN,
            "at": at,
            "amount": self_serve_inr_per_min,
            "by": recorded_by,
            "note": note,
        }
    )
    await session.execute(text(_INSERT_AT), rows)
    return at


async def card_at(
    session: AsyncSession, *, at: datetime
) -> Mapping[str, Mapping[VoiceTier, Decimal]]:
    """The pack card in force at `at`, as `{pack_id: {voice: ₹/min}}`.

    THE SAME RESOLUTION RULE `self_serve_rate_at` USES — greatest `effective_from` ≤ `at`,
    per key — expressed as one `DISTINCT ON` rather than twelve round trips, because a card
    is read on the path that opens a lot and twelve queries under a per-tenant advisory lock
    is twelve times the lock hold for one answer.

    **WITH NO ROW FOR A CELL, THE STATIC CATALOGUE.** `self_serve_rate_at`'s argument
    exactly: nobody recorded a card before this landed, so seeding one at the beginning of
    time would ASSERT that today's rates were in force in every past month. The catalogue is
    what this build sells, it is the honest answer for an instant with no history, and it is
    why landing this re-prices nobody. The fallback is per CELL rather than per card: a card
    recorded before `plus` existed resolves the five packs it recorded and answers the
    catalogue for `plus`, which is the only reading that does not silently drop a pack.

    `at` MUST be timezone-aware, for `self_serve_rate_at`'s reason — a naive instant would be
    read in the process's local timezone and a UTC container would price a month differently
    from an IST laptop.
    """
    if at.tzinfo is None:
        raise ValueError("a card is resolved at an aware instant (timestamptz or UTC-aware)")
    recorded: dict[str, dict[VoiceTier, Decimal]] = {}
    rows = await session.execute(text(_CARD_AT), {"prefix": f"{PACK_RATE_KEY_PREFIX}:%", "at": at})
    for rate_key, amount in rows:
        parsed = _parse_pack_rate_key(rate_key)
        if parsed is None:
            continue
        pack_id, voice = parsed
        # `Decimal(str(...))` for `self_serve_rate_at`'s reason: a driver that ever returned
        # a float fails loudly here rather than floating its way into a lot's frozen rate.
        recorded.setdefault(pack_id, {})[voice] = Decimal(str(amount))
    return {
        pack.pack_id: {
            voice: recorded.get(pack.pack_id, {}).get(voice, pack.inr_per_min(voice))
            for voice in VOICE_TIERS
        }
        for pack in PACK_CATALOGUE
    }


__all__ = [
    "PACK_RATE_KEY_PREFIX",
    "SELF_SERVE_PER_MIN",
    "card_at",
    "pack_rate_key",
    "record_card",
    "record_list_rate",
    "self_serve_rate_at",
]
