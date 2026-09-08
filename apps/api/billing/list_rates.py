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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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

#: THE ONE CLAUSE THAT MAKES A CANCELLATION REAL, spliced into every resolution query in
#: this module (and into the ops console's "when was the card in force dated" read).
#:
#: An operator who schedules a card and then thinks better of it cannot UPDATE or DELETE the
#: rows: `platform_list_rates` carries `calevate_forbid_mutation` and hard rule 4 has no
#: exception for a change of mind. The compensating entry is a row in
#: `platform_list_rate_cancellations` naming the INSTANT that is withdrawn, and this clause
#: is what makes every reader honour it.
#:
#: **WHY A SECOND TABLE AND NOT "RE-RECORD THE OLD CARD JUST AFTER THE NEW ONE".** That is
#: the shape a pure append-only store suggests, and it leaves a hole: the primary key is
#: `(rate_key, effective_from)`, so the restoring card cannot share the withdrawn card's
#: instant and has to land at least one microsecond after it. For that microsecond
#: `card_at` answers the card that was supposed to never take effect, and a purchase landing
#: inside it freezes rates nobody approved — a window too small to hit on purpose and too
#: real to write down as safe. A cancellation is therefore recorded as its own fact, which
#: also keeps the rate history intact: what was scheduled, and that it was withdrawn, both
#: stay readable.
_NOT_CANCELLED = (
    " AND NOT EXISTS (SELECT 1 FROM platform_list_rate_cancellations c "
    "WHERE c.effective_from = platform_list_rates.effective_from)"
)

_RATE_AT = (
    "SELECT inr_amount FROM platform_list_rates "
    "WHERE rate_key = :key AND effective_from <= :at" + _NOT_CANCELLED + " "
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
    "WHERE rate_key LIKE :prefix AND effective_from <= :at" + _NOT_CANCELLED + " "
    "ORDER BY rate_key, effective_from DESC"
)

_NOW = "SELECT clock_timestamp()"

#: Every card instant still ahead of `:at` that nobody has withdrawn, soonest first.
#: `DISTINCT` because a card is twelve rows sharing one instant and what is being listed is
#: the CARD. Bounded by `PENDING_CARD_LIMIT` at the query rather than in Python: a scheduled
#: card is minted only by a step-up-confirmed operator write, so the list is short by
#: construction, and a ceiling in the statement is the one that cannot be forgotten.
_PENDING_CARDS = (
    "SELECT DISTINCT effective_from FROM platform_list_rates "
    "WHERE rate_key LIKE :prefix AND effective_from > :at" + _NOT_CANCELLED + " "
    "ORDER BY effective_from LIMIT :limit"
)

#: Does this instant name a card at all? Asked before a cancellation is written, so that
#: withdrawing something nobody scheduled is a sentence rather than a silent success.
_CARD_EXISTS = (
    "SELECT 1 FROM platform_list_rates WHERE rate_key LIKE :prefix AND effective_from = :at LIMIT 1"
)

#: `INSERT ... SELECT ... WHERE` rather than `VALUES`, so the "still in the future" half of
#: the rule is decided by the DATABASE's clock inside the same statement. The caller checks
#: it too and with a better sentence; this is the copy no second writer can route around,
#: and it costs nothing.
_CANCEL = (
    "INSERT INTO platform_list_rate_cancellations (effective_from, cancelled_by, reason) "
    "SELECT :at, :by, :reason WHERE CAST(:at AS timestamptz) > now() "
    "ON CONFLICT (effective_from) DO NOTHING RETURNING effective_from"
)


async def record_card(
    session: AsyncSession,
    *,
    card: Sequence[CreditPack] = PACK_CATALOGUE,
    effective_from: datetime | None = None,
    self_serve_inr_per_min: Decimal,
    recorded_by: UUID,
    note: str,
) -> datetime:
    """Append a whole card — every (pack, voice) rate plus `SELF_SERVE_PER_MIN` — at ONE
    instant, on the caller's transaction. Returns the `effective_from` it stamped.

    **`effective_from` MAY BE IN THE FUTURE, AND THAT IS WHAT MAKES A PRICE CHANGE A
    NOTICE RATHER THAN AN AMBUSH.** It used to be `clock_timestamp()` and nothing else, so
    every card came into force the instant Save was pressed. A dated card changes NOTHING
    until its date: `card_at` resolves the greatest `effective_from` at or before the
    instant asked about, so a card dated a month out is invisible to every reader —
    including `service.rate_card_at`, the one door a lot opener uses — until that month has
    passed. Omitted, the statement clock is read once and bound to every row, which is the
    behaviour every existing caller keeps.

    The instant must be timezone-aware for `card_at`'s reason: it lands in a `timestamptz`
    and is compared against one, and a naive value would be read in the process's local
    timezone — a UTC container would schedule a change an IST laptop dates differently.

    **THE NOTICE PERIOD IS NOT ENFORCED HERE** (`notice_refusal` is where it lives, and the
    ops route is what runs it). This function is also what re-dates the card ALREADY in
    force when an unrelated platform setting moves (`ops/config_routes._record_card`), and
    that write is not a price change to give notice of — a floor inside the writer would
    refuse it, or would have to learn to tell the two apart, which is a policy question the
    writer has no way to answer.

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
    if effective_from is not None and effective_from.tzinfo is None:
        raise ValueError("a card is dated at an aware instant (timestamptz or UTC-aware)")
    at: datetime = (
        effective_from
        if effective_from is not None
        else (await session.execute(text(_NOW))).scalar_one()
    )
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


# --- scheduling a card: the notice period, and withdrawing one -----------------------
#
# WHY THE CARD MAY BE EDITED AT ALL, AND WHY THAT IS SAFE. Terms §6.1 promises that a later
# card change does not reprice credit a client already holds, and `credit_lots` makes that
# true BY CONSTRUCTION rather than by anybody remembering it: a purchase freezes its two
# ₹/min figures onto the lot it opens (`service.rate_card_at` reads the card in force at the
# instant the money arrives, once), and every minute is then debited against the lot it is
# spent from. So a card recorded today can only ever price a purchase made after it takes
# effect. That property is what makes an editable card defensible at all — without it an
# operator's Save would silently restate the value of credit somebody had already paid for.

#: How far ahead of the write a new card must be dated. THIRTY DAYS, ALWAYS, INCLUDING A
#: PRICE CUT (founder's decision, 8 Sep 2026 — D-550).
#:
#: The reasoning is predictability rather than fairness. A client planning a campaign budget
#: needs to know that the rate they were quoted this morning is the rate they can still buy
#: at for a month; a rule with an exception for cuts is a rule an operator has to reason
#: about under time pressure, and "is this really a cut for every client on every pack and
#: every voice?" is exactly the question a twelve-cell card makes hard to answer correctly.
#: One number, no exceptions, no judgement call at the console.
#:
#: THIRTY DAYS is the common notice norm for SaaS list-price changes — long enough that a
#: client sees a change land in a monthly planning cycle before it prices anything, short
#: enough that we are not quoting a rate we no longer want to sell for a quarter. Deliberately
#: NOT cited to a particular vendor's policy: what is defensible is that notice periods in
#: this class cluster at 30 days for monthly-cycle products and stretch further for annual
#: commitments, and our cycle is a prepaid top-up a client makes when they choose to. No
#: vendor page was read for this figure (hard rule 11), and none is cited as if it had been.
CARD_NOTICE_DAYS: Final = 30

#: How many scheduled cards one console read will list. A pending card can only be minted by
#: a step-up-confirmed operator write, so this is a sanity ceiling and not a page size —
#: there is no cursor, because a card ladder read one page at a time is the thing an operator
#: must not be able to do (`check_list_bounds`' entry for the read says the same).
PENDING_CARD_LIMIT: Final = 24


def notice_refusal(effective_from: datetime, *, now: datetime) -> str | None:
    """Why this date may not be used, or None when it may. The 30-day floor, in one place.

    A FUNCTION RATHER THAN AN `if` IN THE ROUTE because it is the rule a test reverts to see
    go red, and because `card_refusals` set the shape: a refusal is a SENTENCE an operator
    can act on, containing the date they asked for and the earliest one they may have.

    Both instants must be aware (`card_at`'s reason). The comparison is a strict `<`: a card
    dated exactly thirty days out is accepted, because a floor nobody can land on exactly is
    a floor that reads as thirty-one days to everyone who tries.
    """
    if effective_from.tzinfo is None or now.tzinfo is None:
        raise ValueError("a card is dated at an aware instant (timestamptz or UTC-aware)")
    earliest = now + timedelta(days=CARD_NOTICE_DAYS)
    if effective_from < earliest:
        return (
            f"a new rate card takes effect no sooner than {CARD_NOTICE_DAYS} days after it "
            f"is recorded, so the earliest date this card can start is "
            f"{earliest.isoformat()} — you asked for {effective_from.isoformat()}. This "
            "holds for a price CUT too: clients are told what a minute will cost them a "
            "month before it changes, in either direction."
        )
    return None


def card_with_rates(cells: Mapping[str, Mapping[VoiceTier, Decimal]]) -> tuple[CreditPack, ...]:
    """The pack ladder priced at `cells` — the catalogue's rungs, somebody else's rates.

    THE BRIDGE BETWEEN A CARD AS RATES AND A CARD AS PACKS. `card_at` answers rates, and
    every guard that judges a card (`credit_packs.card_refusals`, `card_margins`) takes
    `CreditPack`s, because what makes a rate refusable is its relation to the pack's
    `amount_inr` — which is NOT in `platform_list_rates` and never will be: this table dates
    ₹/min cells, and what a pack COSTS is the catalogue's own fact (`service.RateCard` takes
    the same reading, and only the two together make the per-cell fallback mean anything).

    A pack the mapping does not price keeps its catalogue rate, for `card_at`'s reason: the
    only other reading silently drops a rung, and a dropped rung is a purchase nobody can
    price. `dataclasses.replace` rather than a constructor call so a field added to
    `CreditPack` — `best_value` was added after this ladder was first written — travels
    without this function learning about it.
    """
    return tuple(
        replace(
            pack,
            sarvam_inr_per_min=cells.get(pack.pack_id, {}).get("sarvam", pack.sarvam_inr_per_min),
            cartesia_inr_per_min=cells.get(pack.pack_id, {}).get(
                "cartesia", pack.cartesia_inr_per_min
            ),
        )
        for pack in PACK_CATALOGUE
    )


def card_list_rate(card: Sequence[CreditPack]) -> Decimal:
    """What `SELF_SERVE_PER_MIN` holds for this card: the entry rung's Sarvam rate.

    "The list rate" has meant the cheapest pack's cheaper voice since D-547 — it is what
    `payment_routes.CreditPacksOut.list_rate_inr_per_min` publishes and what the marketing
    site leads with — so a card that moves that cell moves the list rate with it. Derived
    from the card rather than taken as a second argument, because the two coming apart is
    how `self_serve_rate_at` would answer a rate the card never sold.
    """
    return min(card, key=lambda pack: pack.amount_inr).sarvam_inr_per_min


@dataclass(frozen=True, slots=True)
class PendingCard:
    """A card that has been recorded and has not taken effect yet.

    `cells` is what will be IN FORCE on the day — `card_at` resolved AT that instant, not
    the twelve rows this card happens to carry. The difference matters for a card recorded
    by an older build, or one that omits a rung: what an operator needs to see is the card
    the platform will actually price with, carry-forward and catalogue fallback included.
    """

    effective_from: datetime
    cells: Mapping[str, Mapping[VoiceTier, Decimal]]


async def pending_cards(session: AsyncSession, *, at: datetime) -> tuple[PendingCard, ...]:
    """Every card dated after `at` that nobody has withdrawn, soonest first.

    What an ops console lists so a card can be cancelled, and what a client console reads to
    say "your rates change on the 12th" before the day arrives. Withdrawn cards are absent
    rather than flagged: a cancelled card prices nothing, ever, so listing it as a change
    that is coming would be false.
    """
    if at.tzinfo is None:
        raise ValueError("a card is resolved at an aware instant (timestamptz or UTC-aware)")
    rows = await session.execute(
        text(_PENDING_CARDS),
        {"prefix": f"{PACK_RATE_KEY_PREFIX}:%", "at": at, "limit": PENDING_CARD_LIMIT},
    )
    instants = [row[0] for row in rows]
    # A list built in a loop rather than a generator: `card_at` is awaited per instant and
    # an async comprehension is not a `tuple()` argument.
    scheduled = []
    for instant in instants:
        scheduled.append(
            PendingCard(effective_from=instant, cells=await card_at(session, at=instant))
        )
    return tuple(scheduled)


async def cancel_card(
    session: AsyncSession, *, effective_from: datetime, cancelled_by: UUID, reason: str
) -> bool:
    """Withdraw a card that has not taken effect. True if this call withdrew it.

    **THIS IS A COMPENSATING ENTRY, NOT AN EDIT** (hard rule 4). Nothing is updated and
    nothing is deleted: `platform_list_rates` keeps every row it was given, and a row in
    `platform_list_rate_cancellations` records that the instant they share was withdrawn,
    by whom and why. The rate history therefore still answers "what was scheduled, and did
    it happen" — which a DELETE would erase and which is the question an operator asks after
    a pricing mistake.

    **ONLY WHILE IT IS STILL IN THE FUTURE, and the caller enforces that** — the route
    refuses a past instant with a sentence, because cancelling a card already in force would
    retroactively reprice every lot opened since it started, which is the one thing this
    whole module exists to prevent. Verified here as well, cheaply, so no second writer can
    reach past it: a `effective_from <= now()` cancellation is refused by the database's own
    clock rather than by the caller's.

    Idempotent (`ON CONFLICT DO NOTHING`): a double-clicked Cancel withdraws one card once
    and reports the second press as the no-op it was, exactly as `_record_card` treats a
    double-clicked Save. So False means "this call wrote nothing" — the card was already
    withdrawn, or its instant has passed since the caller looked — never "no such card",
    which `card_is_scheduled` is the question for.
    """
    if effective_from.tzinfo is None:
        raise ValueError("a card is dated at an aware instant (timestamptz or UTC-aware)")
    # `RETURNING` rather than `rowcount`: SQLAlchemy types the latter loosely enough that
    # a bool derived from it reaches mypy as `Any`, and "did this write happen" is exactly
    # the answer that must not be untyped.
    written = (
        await session.execute(
            text(_CANCEL), {"at": effective_from, "by": cancelled_by, "reason": reason}
        )
    ).first()
    return written is not None


async def card_is_scheduled(session: AsyncSession, *, effective_from: datetime) -> bool:
    """Is there a card at this exact instant? Asked before withdrawing one.

    An instant that names no card is an operator typing a date by hand, or a console holding
    a stale list — and answering "cancelled" to it would be a cheerful lie about a card that
    never existed (`revert_config` makes the same refusal for the same reason).
    """
    if effective_from.tzinfo is None:
        raise ValueError("a card is dated at an aware instant (timestamptz or UTC-aware)")
    row = (
        await session.execute(
            text(_CARD_EXISTS),
            {"prefix": f"{PACK_RATE_KEY_PREFIX}:%", "at": effective_from},
        )
    ).first()
    return row is not None


__all__ = [
    "CARD_NOTICE_DAYS",
    "PACK_RATE_KEY_PREFIX",
    "PENDING_CARD_LIMIT",
    "SELF_SERVE_PER_MIN",
    "PendingCard",
    "cancel_card",
    "card_at",
    "card_is_scheduled",
    "card_list_rate",
    "card_with_rates",
    "notice_refusal",
    "pack_rate_key",
    "pending_cards",
    "record_card",
    "record_list_rate",
    "self_serve_rate_at",
]
