"""Credit lots: the FIFO store a prepaid wallet is actually spent from (D-547).

`PLAN-CREDIT-LOTS-AND-VOICE-TIERS.md` §2, §3.1, §4.B and ADDENDUM 2. Migration
`c9f3a71e58d2` created the table; this module is the only code that draws one down.

THE ONE IDEA. A pack's discount is delivered as a CHEAPER MINUTE frozen on the purchase
that bought it, not as bonus credits. So a wallet is no longer one balance and one rate:
it is a queue of LOTS, each with the two per-minute rates (Sarvam, Cartesia) it was sold
at, spent oldest-first. The money stays on `credit_ledger` — one signed balance, still
append-only (hard rule 4) — and this table carries the terms. `SUM(credits_remaining)`
equals that balance whenever it is non-negative (invariant §2.3.1); a negative balance
means every lot is at zero and the difference is overdraft.

RATES ARRIVE AS PARAMETERS AND ARE NEVER READ FROM THE CATALOGUE HERE. `credit_packs`
knows what a pack costs today; a lot knows what it was sold at, which is a different
question and is answered by the row. That is also what keeps this module callable from
the pipeline, from payments and from the ops console without any of them agreeing on a
card (Phase B2 wires those four).

--------------------------------------------------------------------------------
CONCURRENCY: THE ADVISORY LOCK IS THE SERIALISATION, THE CAS IS THE BACKSTOP
--------------------------------------------------------------------------------
Every function here runs INSIDE the caller's transaction and takes
`service.lock_tenant_credits` — the SAME per-tenant `pg_advisory_xact_lock` key
`record_entry` takes (`billing/service.py:233-248`), re-entrant within a transaction, so
a caller that already holds it pays nothing. Taking it here rather than trusting the
caller is `find_entry_by_ref`'s decision and its argument: a critical section that is
only as good as every future caller remembering it is not a critical section. A Redis
mutex is refused for BACKEND-PATTERNS §5's reason — the window that must be covered is
"our read until our COMMIT", which is of unknown length and which a TTL-bounded lease
silently outlives.

The decrement is nevertheless a compare-and-swap: `UPDATE ... WHERE id = :id AND
credits_remaining = :seen`, with `rowcount == 0` read as "lost the race", the lot re-read
and the portion recomputed. **There is deliberately no `SELECT ... FOR UPDATE` in front
of it**, and that is a departure from the plan's own sentence, taken for the reason
CLAUDE.md hard rule 10 gives: row locks plus CAS is fetching the same guarantee twice,
and it makes the retry arm unreachable — a defensive branch no test can enter is the
thing the ratchet exists to refuse, and BACKEND-PATTERNS §5 puts the guard IN the write
for exactly this shape. With CAS alone the arm is real and `tests/credit_lots_cas_test.py`
drives it with two sessions. What a lost race costs: one extra read and one extra UPDATE
attempt; what it cannot cost is a double spend, because the guard is the value we based
the arithmetic on.

--------------------------------------------------------------------------------
WHAT A SPLIT IS
--------------------------------------------------------------------------------
A debit returns the list of lots it drew from, which the caller writes into the `usage`
row's `meta.lots` (invariant §2.3.5, ADDENDUM 2 §2.1). `SUM(credits)` over the splits IS
the row's delta, whatever kind they are; a reader totalling TALK MINUTES filters
`kind == "call"`. An `ai_assist` split carries no `minutes`, `inr_per_min` or
`voice_tier` **as absent keys, not nulls** — the dashboard-AI debit buys rupees of
assistance, and a key whose null means "not applicable" is the tri-state defect
`AgentSnapshot.*_readable` exists to avoid. `lot_id` follows the same rule: it is absent
on the OVERDRAFT portion, because that portion came from no lot at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import TYPE_CHECKING, ClassVar, Literal
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession

# The MODULE and not the symbol, deliberately: Phase B2 makes `service` import this file,
# and a `from ... import lock_tenant_credits` here would then resolve at import time
# against a half-initialised module. Attribute access on the module object does not.
from apps.api.billing import service as credit_service
from apps.api.billing.rates import MONEY_Q, ROUNDING
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

if TYPE_CHECKING:  # `LotRates` is a type here and never a runtime import.
    # The PAIR of per-minute rates, `service.LotRates`. Imported for the annotation only:
    # `service` imports this module at runtime, so a runtime import here would be the
    # circular one the module-object import above exists to avoid. `from __future__ import
    # annotations` is what makes the annotation a string and this legal.
    from apps.api.billing.service import LotRates

#: WHICH VOICE A CALL SPOKE IN, and therefore which of a lot's two rates prices it.
#: Spelled here rather than imported from `agents/voices.py` because Phase C owns that
#: file and this module must not depend on the catalogue to price a minute;
#: `tests/credit_lots_vocabulary_test.py` holds the two spellings equal once C lands.
VoiceTier = Literal["sarvam", "cartesia"]

#: Where a lot's credits came from. The DB twin is `models.LOT_SOURCES` and the CHECK
#: built from it; `tests/credit_lots_vocabulary_test.py` holds them equal.
LotSource = Literal["topup", "grant", "bonus_legacy", "migration", "override"]

#: How many times one lot may lose the CAS race before we stop. A lost race means another
#: writer committed between our read and our write, which under the advisory lock cannot
#: happen at all and outside it is rare — so a run of eight is not contention, it is a
#: caller in a loop or a defect, and spinning silently would hide it.
_MAX_CAS_ATTEMPTS = 8

_LOT_COLUMNS = """
SELECT id, tenant_id, source, pack_id, override_of_pack_id, credits_total,
       credits_remaining, sarvam_inr_per_min, cartesia_inr_per_min, opened_at,
       closed_at
FROM credit_lots
"""

_SELECT_OPEN_LOTS = (
    _LOT_COLUMNS
    + """
WHERE tenant_id = :tid AND closed_at IS NULL
ORDER BY opened_at, id
"""
)

#: One lot by id, still open. `tenant_id` is not in the predicate because RLS already is:
#: the policy is `tenant_id = current_setting('app.tenant_id')::uuid` for every verb, so a
#: lot of another tenant is not visible to ask about (`tests/credit_lots_rls_test.py`).
_SELECT_ONE_OPEN_LOT = (
    _LOT_COLUMNS
    + """
WHERE id = :id AND closed_at IS NULL
"""
)

#: A lot by id whether or not it is closed — the restatement path, which must be able to
#: correct (and REOPEN) a lot that has already been spent to nothing.
_SELECT_ANY_LOT = (
    _LOT_COLUMNS
    + """
WHERE id = :id
"""
)

_INSERT_LOT = """
INSERT INTO credit_lots
    (id, tenant_id, source, pack_id, override_of_pack_id, credits_total,
     credits_remaining, sarvam_inr_per_min, cartesia_inr_per_min, ledger_entry_id,
     opened_at, created_at, updated_at)
VALUES (:id, :tid, :source, :pack_id, :override_of_pack_id, :credits, :credits,
        :sarvam, :cartesia, :ledger_entry_id,
        COALESCE(CAST(:opened_at AS timestamptz), clock_timestamp()), clock_timestamp(),
        clock_timestamp())
"""

#: CLOSE A LOT WITHOUT SPENDING IT — the first half of a re-price (D-547 Q6, close-and-
#: replace). `credits_remaining` and `closed_at` are both inside the freeze trigger's
#: allowlist, so this is the ONE shape of "stop this lot" the terms freeze permits; the
#: rates, the source and the pack on the row never move, which is what makes the closed row
#: a truthful record of what was sold. The credit is not destroyed: the caller opens the
#: replacement carrying `credits_remaining` in the same transaction, which is what keeps
#: invariant §2.3.1 (`SUM(credits_remaining)` = balance) true at every commit.
#:
#: CAS on `credits_remaining`, like `_TAKE_FROM_LOT` and for the same reason: a call that
#: spent part of this lot between our read and our write would otherwise move a stale
#: figure onto the replacement and mint or destroy credit.
_CLOSE_LOT = """
UPDATE credit_lots
SET credits_remaining = 0,
    closed_at = clock_timestamp(),
    updated_at = clock_timestamp()
WHERE id = :id AND credits_remaining = :seen AND closed_at IS NULL
"""

#: THE CAS. `credits_remaining = :seen` is the guard; `closed_at IS NULL` keeps a lot that
#: another writer just emptied from being drawn again. `clock_timestamp()` and not `now()`
#: for `record_entry`'s reason: `now()` is transaction-start time, and a pipeline
#: transaction does plenty before it charges.
_TAKE_FROM_LOT = """
UPDATE credit_lots
SET credits_remaining = credits_remaining - :take,
    closed_at = CASE WHEN credits_remaining - :take = 0
                     THEN clock_timestamp() ELSE closed_at END,
    updated_at = clock_timestamp()
WHERE id = :id AND credits_remaining = :seen AND closed_at IS NULL
"""

#: ADDENDUM 2 §2.2. `credits_total` moves by the delta; `credits_remaining` FLOORS at
#: zero, because moving both by the same delta is what violates
#: `credits_remaining >= 0` and stops an operator mid-correction. The lot closes when the
#: remainder is nil and REOPENS when an upward restatement puts credits back on it.
_RESTATE_LOT = """
UPDATE credit_lots
SET credits_total = credits_total + :delta,
    credits_remaining = GREATEST(credits_remaining + :delta, 0),
    closed_at = CASE WHEN GREATEST(credits_remaining + :delta, 0) = 0
                     THEN COALESCE(closed_at, clock_timestamp()) ELSE NULL END,
    updated_at = clock_timestamp()
WHERE id = :id AND credits_total = :seen_total AND credits_remaining = :seen_remaining
"""


@dataclass(frozen=True, slots=True)
class OpenLot:
    """One lot with credits still on it, as the FIFO scan reads it."""

    lot_id: UUID
    tenant_id: UUID
    source: str
    pack_id: str | None
    override_of_pack_id: str | None
    credits_total: Decimal
    credits_remaining: Decimal
    sarvam_inr_per_min: Decimal
    cartesia_inr_per_min: Decimal
    opened_at: datetime
    #: `None` for every lot the FIFO scan returns — it selects open lots only. It is a real
    #: value on the by-id read, which `service.reprice_lot` uses to tell "this credit is
    #: already spent" (a sentence an operator can act on) from "no such lot" (a 404).
    closed_at: datetime | None

    def rate_for(self, voice_tier: VoiceTier) -> Decimal:
        """What a minute of `voice_tier` costs out of THIS lot."""
        if voice_tier == "sarvam":
            return self.sarvam_inr_per_min
        return self.cartesia_inr_per_min


@dataclass(frozen=True, slots=True)
class CallDemand:
    """MINUTES of talk time on one voice tier — the quantity a call fixes.

    A call is not a demand for a number of credits: what the client used is minutes, and
    what they owe is minutes multiplied by the rate of whichever lot pays for them, which
    is not knowable until the lots are walked. `fallback_rates` prices the case with no
    lots at all (a wallet already in overdraft, one that has never been topped up, or one
    whose reversal emptied it) and is REQUIRED rather than optional so that no caller can
    reach an unpriced minute.

    **IT IS A PAIR, AND IT USED TO BE ONE NUMBER.** `workers/pipeline` passed the Sarvam
    list rate as THE fallback for both voices, so a Studio minute on a wallet with no open
    lot — a new tenant before their first pack, a wallet after a full reversal, a migrated
    negative balance — was debited at ₹5.00 against a card that sells it at ₹8.00 and a
    cost floor of ₹4.36. One figure cannot price two voices, and a caller resolving it by
    hand beside `voice_tier` is a caller who can resolve the wrong one; the pair plus
    `LotRates.rate_for` makes them unable to disagree.
    """

    minutes: Decimal
    voice_tier: VoiceTier
    fallback_rates: LotRates

    @property
    def fallback_inr_per_min(self) -> Decimal:
        """This demand's fallback rate — the pair, resolved by this demand's own voice."""
        return self.fallback_rates.rate_for(self.voice_tier)


@dataclass(frozen=True, slots=True)
class AiAssistDemand:
    """RUPEES of dashboard-AI assistance (plan §4.B.7). Face value, ₹1 = 1 credit: there
    is no rate and no voice, which is why this is its own demand rather than a call with
    two fields left empty."""

    credits: Decimal


#: What a debit is asking for. A union rather than one dataclass with optional fields:
#: the two are priced by different arithmetic, and the discriminator is what decides which.
LotDemand = CallDemand | AiAssistDemand


@dataclass(frozen=True, slots=True)
class CallSplit:
    """One lot's contribution to a call, priced at THAT lot's rate for the call's voice.

    `lot_id is None` means the OVERDRAFT portion: the minutes the lots could not cover,
    priced at the last lot consumed (plan §0 Q5) or at the caller's fallback when there
    were no lots. It serialises with the key absent, never as a null.
    """

    lot_id: UUID | None
    credits: Decimal
    minutes: Decimal
    inr_per_min: Decimal
    voice_tier: VoiceTier
    kind: ClassVar[str] = "call"


@dataclass(frozen=True, slots=True)
class AiAssistSplit:
    """One lot's contribution to a dashboard-AI debit: credits, and nothing else."""

    lot_id: UUID | None
    credits: Decimal
    kind: ClassVar[str] = "ai_assist"


LotSplit = CallSplit | AiAssistSplit


@dataclass(frozen=True, slots=True)
class LotRestatement:
    """What an operator's correction did to one lot (ADDENDUM 2 §2.2).

    `shortfall` is the part of a downward restatement the lot could not absorb because it
    had already been spent. It is NOT taken off the lot — it becomes wallet overdraft,
    which is a balance-level fact the CALLER books on the ledger, and which the next
    purchase repays before opening its own lot.
    """

    lot_id: UUID
    credits_total: Decimal
    credits_remaining: Decimal
    closed: bool
    shortfall: Decimal


def _money(amount: Decimal) -> Decimal:
    """A rupee figure at the ledger's own scale (hard rule 7)."""
    return amount.quantize(MONEY_Q, rounding=ROUNDING)


def _minutes(amount: Decimal) -> Decimal:
    """A minute figure, quantised DOWNWARDS.

    `ROUND_DOWN` and not `ROUNDING`, and it is not a money decision: this number is what
    a client is told they got for their credits, and rounding it up quotes a minute the
    lot did not pay for. `prepaid_minutes_left` floors for the same reason.
    """
    return amount.quantize(MONEY_Q, rounding=ROUND_DOWN)


def split_meta(splits: Sequence[LotSplit]) -> list[dict[str, str]]:
    """THE `meta.lots` SERIALISATION — one function, so the writer and every reader share
    one spelling (invariant §2.3.5).

    Digits as STRINGS, never Decimals or floats: this crosses JSONB and comes back through
    `json.loads`, where a JSON number would be a binary double by the time a statement
    renders it (hard rule 7, the same argument `record_entry`'s outbox payload makes).

    An inapplicable key is ABSENT (ADDENDUM 2 §2.1): `minutes`, `inr_per_min` and
    `voice_tier` on an `ai_assist` split, and `lot_id` on the overdraft portion of either.
    """
    rows: list[dict[str, str]] = []
    for split in splits:
        row: dict[str, str] = {"kind": split.kind, "credits": str(split.credits)}
        if split.lot_id is not None:
            row["lot_id"] = str(split.lot_id)
        if isinstance(split, CallSplit):
            row["minutes"] = str(split.minutes)
            row["inr_per_min"] = str(split.inr_per_min)
            row["voice_tier"] = split.voice_tier
        rows.append(row)
    return rows


def credits_of(splits: Sequence[LotSplit]) -> Decimal:
    """What the debit comes to: the sum of every split, whatever kind. This is the number
    the caller passes to `record_entry` as a NEGATIVE delta, and the one invariant §2.3.5
    holds equal to the row's own delta."""
    return _money(sum((split.credits for split in splits), Decimal("0")))


async def read_open_lots(session: AsyncSession, *, tenant_id: UUID) -> list[OpenLot]:
    """Every lot with credits left, OLDEST FIRST — the FIFO order invariant §2.3.2 fixes.

    The one read behind the debit, the runway and the client's own "3,200 credits at
    ₹4.70 / ₹6.50, then 2,000 at ₹5.00 / ₹8.00" list, so those three can never disagree
    about what a wallet holds or in which order it will be spent.
    """
    rows = (await session.execute(text(_SELECT_OPEN_LOTS), {"tid": tenant_id})).mappings().all()
    return [_lot_of(row) for row in rows]


def _lot_of(row: RowMapping) -> OpenLot:
    # `Decimal(str(...))`, never `Decimal(...)`: the convention every NUMERIC read in this
    # tree keeps, so the day a driver hands back a float the wallet does not inherit the
    # binary error (`service._newest_balance` carries the worked example).
    return OpenLot(
        lot_id=UUID(str(row["id"])),
        tenant_id=UUID(str(row["tenant_id"])),
        source=str(row["source"]),
        pack_id=None if row["pack_id"] is None else str(row["pack_id"]),
        override_of_pack_id=(
            None if row["override_of_pack_id"] is None else str(row["override_of_pack_id"])
        ),
        credits_total=Decimal(str(row["credits_total"])),
        credits_remaining=Decimal(str(row["credits_remaining"])),
        sarvam_inr_per_min=Decimal(str(row["sarvam_inr_per_min"])),
        cartesia_inr_per_min=Decimal(str(row["cartesia_inr_per_min"])),
        opened_at=row["opened_at"],
        closed_at=row["closed_at"],
    )


async def _read_open_lot(session: AsyncSession, *, lot_id: UUID) -> OpenLot | None:
    """One open lot, re-read after a lost CAS race. `None` means it is gone or closed —
    another writer emptied it — and the walk moves to the next lot rather than retrying
    against a row that can no longer pay."""
    row = (
        (await session.execute(text(_SELECT_ONE_OPEN_LOT), {"id": lot_id})).mappings().one_or_none()
    )
    return None if row is None else _lot_of(row)


async def read_lot(session: AsyncSession, *, lot_id: UUID) -> OpenLot | None:
    """One lot by id, open or CLOSED — the correction paths' read.

    Public and shared by the two of them rather than private to the restatement, because
    both have to reach a lot that is already spent: ADDENDUM 2 §2.2's correction, and
    `service.reprice_lot`, which needs the closed state itself in order to refuse a
    re-price of credit the client no longer holds with a sentence instead of a 404.
    """
    row = (await session.execute(text(_SELECT_ANY_LOT), {"id": lot_id})).mappings().one_or_none()
    return None if row is None else _lot_of(row)


async def open_lot(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    credits_inr: Decimal,
    sarvam_inr_per_min: Decimal,
    cartesia_inr_per_min: Decimal,
    source: LotSource,
    pack_id: str | None,
    ledger_entry_id: UUID,
    override_of_pack_id: str | None = None,
    opened_at: datetime | None = None,
) -> UUID:
    """Open one lot for credits that have just been added, and return its id.

    Called in the SAME transaction as the `credit_ledger` row it names — every credit-adding
    writer opens exactly one (Phase B2). `ledger_entry_id` is UNIQUE on the table, so a
    replayed payment that somehow reached this function twice fails loudly rather than
    doubling a client's calling time.

    The rates are the CALLER'S: the pack's, the free-amount rule's (plan §0 Q3), the list
    rates for a grant (Q4), or an operator's override borrowed from another pack (Q6). This
    function neither reads nor validates them against a catalogue — a lot is a record of
    what was sold, and the day the card moves this row must not.

    `opened_at` DEFAULTS TO NOW AND EXISTS FOR ONE CALLER: the re-price (Q6), which closes
    a lot and opens a replacement carrying the same credit at another pack's rates. FIFO
    order is `opened_at` (invariant §2.3.2), so a replacement stamped with the current
    clock would silently move re-priced credit to the BACK of the client's queue and change
    the order they were promised their money would be spent in — a lot bought in March
    would start being spent after one bought in June because an operator corrected its
    price. The replacement therefore INHERITS the original's `opened_at` and keeps its
    place. No other caller passes it: money that has just arrived is opened now.

    `ValueError`, not a `ProblemError`: every argument here comes from our own catalogue or
    console, never from a client's keyboard, so a bad one is a defect to fix and not a
    sentence to render. The table's CHECKs say the same thing a layer down; these exist so
    the message names which term was wrong.
    """
    if credits_inr <= 0:
        raise ValueError(f"a lot must open with credits > 0, got {credits_inr}")
    if sarvam_inr_per_min <= 0:
        raise ValueError(f"a lot's Sarvam rate must be > 0, got {sarvam_inr_per_min}")
    if cartesia_inr_per_min < sarvam_inr_per_min:
        raise ValueError(
            f"a lot's Cartesia rate may not be below its Sarvam rate: "
            f"{cartesia_inr_per_min} < {sarvam_inr_per_min}"
        )
    await credit_service.lock_tenant_credits(session, tenant_id)
    lot_id = uuid7()
    await session.execute(
        text(_INSERT_LOT),
        {
            "id": lot_id,
            "tid": tenant_id,
            "source": source,
            "pack_id": pack_id,
            "override_of_pack_id": override_of_pack_id,
            "credits": _money(credits_inr),
            "sarvam": _money(sarvam_inr_per_min),
            "cartesia": _money(cartesia_inr_per_min),
            "ledger_entry_id": ledger_entry_id,
            "opened_at": opened_at,
        },
    )
    return lot_id


async def close_lot(session: AsyncSession, *, lot_id: UUID, seen_remaining: Decimal) -> bool:
    """Close a lot WITHOUT spending it, and say whether the CAS held.

    The first half of a re-price (`service.reprice_lot`): the credit on this lot is about
    to be re-opened at another pack's rates on a replacement row, because
    `credit_lots_terms_frozen` refuses an UPDATE that touches the rates and that refusal is
    the promise the client was sold. `False` means another writer moved or closed this lot
    between the caller's read and this write — the caller must not open a replacement for a
    figure that is no longer there.
    """
    result = await session.execute(text(_CLOSE_LOT), {"id": lot_id, "seen": _money(seen_remaining)})
    return rowcount_of(result) == 1


async def _take(session: AsyncSession, *, lot_id: UUID, seen: Decimal, take: Decimal) -> bool:
    """The compare-and-swap. `False` = another writer moved this lot under us."""
    result = await session.execute(text(_TAKE_FROM_LOT), {"id": lot_id, "seen": seen, "take": take})
    return rowcount_of(result) == 1


def _portion_for_call(
    lot: OpenLot, *, minutes_left: Decimal, voice_tier: VoiceTier
) -> tuple[Decimal, Decimal, Decimal]:
    """How much of `lot` one call takes: `(credits, minutes_reported, minutes_used)`.

    `minutes_used` is the EXACT quantity taken out of the demand and `minutes_reported` is
    the same number quantised down for the split. They differ by less than a hundredth of a
    paisa's worth of talk time, and keeping them apart is what stops the residue of one
    lot's division from being charged twice at the next lot's rate.
    """
    rate = lot.rate_for(voice_tier)
    covered = lot.credits_remaining / rate
    if minutes_left <= covered:
        # The lot pays for the whole call. `min(...)` guards the one rounding direction
        # that could exceed it: half-up on the minutes-by-rate product can land a
        # hundredth of a paisa above `credits_remaining`, which the CHECK would refuse.
        return min(_money(minutes_left * rate), lot.credits_remaining), minutes_left, minutes_left
    return lot.credits_remaining, _minutes(covered), covered


async def consume(session: AsyncSession, *, tenant_id: UUID, demand: LotDemand) -> list[LotSplit]:
    """Draw a debit out of the wallet's lots, oldest first, and say where it came from.

    Returns the splits (never `None`, possibly empty when nothing was demanded). It does
    NOT touch `credit_ledger`: the caller appends the one `usage` row, with
    `credits_of(splits)` as the negative delta and `split_meta(splits)` in `meta.lots`, so
    that a replay guarded by `(tenant_id, 'usage', call_id)` cannot consume twice.

    WHAT HAPPENS WHEN THE LOTS RUN OUT. The remainder is returned as ONE overdraft split
    with no `lot_id`, priced at the rate of the LAST lot consumed (plan §0 Q5 — telecom
    prepaid does exactly this, and it needs no new state beyond the signed balance we
    already keep), or at the demand's own fallback rate when there were no lots at all.
    The wallet goes negative, `credits_exhausted` stops the next outbound dial, and the
    next credit-adding entry repays the overdraft before opening its lot (Phase B2 §4.B.5).
    """
    await credit_service.lock_tenant_credits(session, tenant_id)
    lots = await read_open_lots(session, tenant_id=tenant_id)
    if isinstance(demand, CallDemand):
        return await _consume_call(session, lots=lots, demand=demand)
    return await _consume_ai_assist(session, lots=lots, demand=demand)


async def _consume_call(
    session: AsyncSession, *, lots: list[OpenLot], demand: CallDemand
) -> list[LotSplit]:
    splits: list[LotSplit] = []
    minutes_left = demand.minutes
    # Plan §0 Q5: the overdraft is priced at the rate of the lot that RAN OUT — so this
    # moves only on a successful take, never merely because a lot was looked at.
    priced_at = demand.fallback_inr_per_min
    index = 0
    attempts = 0
    while minutes_left > 0 and index < len(lots):
        lot = lots[index]
        rate = lot.rate_for(demand.voice_tier)
        taken, reported, used = _portion_for_call(
            lot, minutes_left=minutes_left, voice_tier=demand.voice_tier
        )
        if await _take(session, lot_id=lot.lot_id, seen=lot.credits_remaining, take=taken):
            splits.append(
                CallSplit(
                    lot_id=lot.lot_id,
                    credits=taken,
                    minutes=reported,
                    inr_per_min=rate,
                    voice_tier=demand.voice_tier,
                )
            )
            priced_at = rate
            minutes_left -= used
            if taken == lot.credits_remaining:
                index += 1
            continue
        index, attempts = await _after_lost_race(session, lots, index=index, attempts=attempts)
    if minutes_left > 0:
        splits.append(
            CallSplit(
                lot_id=None,
                credits=_money(minutes_left * priced_at),
                minutes=_minutes(minutes_left),
                inr_per_min=priced_at,
                voice_tier=demand.voice_tier,
            )
        )
    return splits


async def _consume_ai_assist(
    session: AsyncSession, *, lots: list[OpenLot], demand: AiAssistDemand
) -> list[LotSplit]:
    splits: list[LotSplit] = []
    credits_left = _money(demand.credits)
    index = 0
    attempts = 0
    while credits_left > 0 and index < len(lots):
        lot = lots[index]
        take = min(credits_left, lot.credits_remaining)
        if await _take(session, lot_id=lot.lot_id, seen=lot.credits_remaining, take=take):
            splits.append(AiAssistSplit(lot_id=lot.lot_id, credits=take))
            credits_left -= take
            if take == lot.credits_remaining:
                index += 1
            continue
        index, attempts = await _after_lost_race(session, lots, index=index, attempts=attempts)
    if credits_left > 0:
        splits.append(AiAssistSplit(lot_id=None, credits=credits_left))
    return splits


async def _after_lost_race(
    session: AsyncSession, lots: list[OpenLot], *, index: int, attempts: int
) -> tuple[int, int]:
    """Recover from a CAS that matched no row: re-read the lot and try it again, or step
    past it when another writer has closed it. Returns the new `(index, attempts)`."""
    attempts += 1
    if attempts > _MAX_CAS_ATTEMPTS:
        # Not a client's problem and not retryable by them: something is writing this
        # tenant's lots in a loop, or a caller is running outside the advisory lock. It
        # raises rather than spinning so an operator sees the cause instead of a hang.
        raise ProblemError.conflict(
            "credit_lots_contended",
            "We could not record that charge because this account's credit is being "
            "changed by something else.",
            remediation="Try again in a moment. If it keeps happening, contact support.",
        )
    fresh = await _read_open_lot(session, lot_id=lots[index].lot_id)
    if fresh is None:
        return index + 1, attempts
    lots[index] = fresh
    return index, attempts


async def adjust_lot_for_restatement(
    session: AsyncSession, *, lot_id: UUID, delta: Decimal
) -> LotRestatement:
    """Correct how much a lot was sold — an operator restating a mis-recorded payment.

    ADDENDUM 2 §2.2 IS THE SPEC HERE, not §3.4's original "adjust both by the same delta",
    which is a production stop: a lot of 5,000 with 1,000 left, restated down by 2,000,
    would need `credits_remaining = -1,000` and the CHECK refuses it. So a restatement of
    `-D` on a lot with `R` remaining and `T` total sets `credits_total = T - D` and
    `credits_remaining = max(R - D, 0)`, closes the lot if the remainder is nil, and hands
    back `shortfall = max(D - R, 0)` — which the CALLER books as wallet overdraft, exactly
    where the balance already carries it. Upward is the ordinary case: both rise, and a
    lot that had closed reopens.

    The RATES are untouched in either direction, and the `credit_lots_terms_frozen` trigger
    is what makes that a fact rather than an intention.
    """
    if delta == 0:
        raise ValueError("a restatement of zero changes nothing; do not write one")
    lot = await read_lot(session, lot_id=lot_id)
    if lot is None:
        raise ProblemError.not_found("credit lot")
    await credit_service.lock_tenant_credits(session, lot.tenant_id)
    if lot.credits_total + delta <= 0:
        # `credits_total > 0` is a CHECK, and a lot of nothing is not a correction — it is
        # a lot that should never have been opened. The operator's remedy is to restate to
        # the real amount, or to refund and let the refund path close it.
        raise ProblemError.business_rule(
            "restatement_empties_lot",
            "That correction would leave this purchase with no credit at all.",
            remediation=(
                "Restate it to the amount that actually arrived, or refund the payment instead."
            ),
        )
    changed = await session.execute(
        text(_RESTATE_LOT),
        {
            "id": lot_id,
            "delta": _money(delta),
            "seen_total": lot.credits_total,
            "seen_remaining": lot.credits_remaining,
        },
    )
    if rowcount_of(changed) != 1:
        raise ProblemError.conflict(
            "credit_lots_contended",
            "This purchase changed while we were correcting it.",
            remediation="Reload the account and try the correction again.",
        )
    remaining = max(lot.credits_remaining + delta, Decimal("0"))
    return LotRestatement(
        lot_id=lot_id,
        credits_total=_money(lot.credits_total + delta),
        credits_remaining=_money(remaining),
        closed=remaining == 0,
        shortfall=_money(max(-delta - lot.credits_remaining, Decimal("0"))),
    )


@dataclass(frozen=True, slots=True)
class TierRate:
    """What ONE voice tier costs this wallet right now, and how much is queued behind it.

    The number a voice PICKER has to show: not the card's rate — the client may have
    bought at a rate the card no longer offers — but the rate frozen on the lot the next
    minute will actually be drawn from. `inr_per_min` is `None` when there is no open lot
    to answer from, which is a real state (an empty or overdrawn wallet) and is why the
    field is nullable rather than defaulted to a card figure that would be a guess about
    what the client's next purchase will cost.

    `further_open_lots` is what stops that single rate being read as the whole truth: two
    lots behind it at other rates means the quoted minute price changes partway through
    the wallet, and the picker says so rather than quoting one number for a queue.
    """

    provider: VoiceTier
    inr_per_min: Decimal | None
    further_open_lots: int


async def voice_tier_rates(session: AsyncSession, *, tenant_id: UUID) -> list[TierRate]:
    """Both voice tiers, each priced at the OLDEST OPEN LOT — the picker's read.

    One walk of the same FIFO queue `consume` draws from and `runway` sums, so the rate a
    client is shown before choosing a voice is the rate their next call is charged. Both
    tiers are always returned, in catalogue order, because a picker that omitted the
    dearer one would present a choice the client cannot see the price of.
    """
    lots = await read_open_lots(session, tenant_id=tenant_id)
    behind = max(len(lots) - 1, 0)
    return [
        TierRate(
            provider=tier,
            inr_per_min=lots[0].rate_for(tier) if lots else None,
            further_open_lots=behind,
        )
        for tier in ("sarvam", "cartesia")
    ]


async def runway(session: AsyncSession, *, tenant_id: UUID) -> dict[str, Decimal]:
    """How many minutes the wallet still holds, per voice (plan §0 Q7).

    Summed LOT BY LOT at each lot's own rate, because one balance divided by one rate is
    the thing lots exist to stop being true: 3,200 credits at ₹4.70 and 2,000 at ₹5.00 are
    1,080.85 minutes, not 5,200 ÷ either number.

    Quantised DOWN, for `prepaid_minutes_left`'s reason: a minute quoted that the wallet
    cannot cover is discovered mid-call. This REPLACES nothing yet — `prepaid_minutes_left`
    is still the runway on the screens until Phase B2 re-points them.
    """
    lots = await read_open_lots(session, tenant_id=tenant_id)
    sarvam = sum((lot.credits_remaining / lot.sarvam_inr_per_min for lot in lots), Decimal("0"))
    cartesia = sum((lot.credits_remaining / lot.cartesia_inr_per_min for lot in lots), Decimal("0"))
    return {"sarvam_minutes": _minutes(sarvam), "cartesia_minutes": _minutes(cartesia)}
