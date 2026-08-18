"""Prepaid credits (D-34/D-39, DATA-MODEL §8).

The ledger ships in M1 and the top-up UI does not, which looks odd until you read D-12:
metering is not retrofittable. A balance reconstructed later from usage rows is a
reconstruction; the first time a client disputes a charge, the difference between a
ledger and a reconstruction is the entire argument.

Two rules the whole module turns on:

- **Append-only** (hard rule 4). A refund is a new entry. `record_entry` is the only
  writer and it never updates.
- **Concurrent writes for one tenant are serialized by an advisory lock.** The obvious
  implementation — `SELECT … ORDER BY occurred_at DESC LIMIT 1 FOR UPDATE` — does NOT
  work, and the test suite proved it: under READ COMMITTED, two charges both block on
  the same newest row, and when the first commits the second re-checks only the row it
  locked, not the query. It never sees the row that was just inserted, so both compute
  from the same starting balance and a ₹100 wallet pays for two ₹80 calls.
  `pg_advisory_xact_lock` on the tenant serializes the whole read-decide-write instead,
  and releases at transaction end. It is scoped to credit writes, so it does not block
  unrelated work on the tenant.

  The lock has to be taken BEFORE any read the write then depends on — including an
  idempotency lookup. `lock_tenant_credits` is that one function, so every writer takes
  the same lock on the same key and nobody re-derives it.

Money is NUMERIC INR throughout (hard rule 7). No floats reach this file, and every
rupee amount is rounded in exactly one function, `to_paise`, with one explicit mode.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.caps import (
    EFFECTIVE_CAP_MIN_SQL,
    EFFECTIVE_CAP_SPEND_SQL,
    read_spend_counters,
)
from apps.api.billing.models import AI_ASSIST_UNIT_TYPES
from apps.api.billing.plans import (
    ist_billing_month,
    ist_month_window,
    month_pricing_instant,
    parse_billing_month,
    plan_in_effect_sql,
    warn_no_plan_in_effect,
)
from apps.api.billing.rates import (
    PREPAID_TIERS,
    ROUNDING,
    TtsTier,
    tier_correction_inr,
)
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7

log = get_logger(__name__)

CreditReason = Literal["topup", "usage", "adjustment", "refund"]

# Below this the wallet is "low" — surfaced in the UI, not enforced. Enforcement is
# `balance > 0`; a warning band exists so a client is told before calls start failing.
LOW_BALANCE_INR = Decimal("200.00")

# --- rounding (hard rule 7) ----------------------------------------------------
#
# NUMERIC(12,4) is the storage precision; a rupee amount shown to a human is two
# decimals. That conversion is a ROUNDING DECISION and it is made here, once:
#
# - ROUND_HALF_UP, the convention Indian tax invoices are checked against. Bare
#   `Decimal.quantize()` uses the ambient `decimal` context, whose default is
#   ROUND_HALF_EVEN (banker's rounding) — so ₹18.045 of GST becomes ₹18.04, and a
#   client adding it up by hand gets ₹18.05 and a support ticket.
# - passed EXPLICITLY, never inherited. `decimal.getcontext()` is process-global and
#   mutable by any library in the image; a rupee that changes because someone else
#   changed a global is not an amount we can defend.
#
# The MODE is `billing.rates.ROUNDING`, imported rather than restated: this module used
# to define its own `ROUND_HALF_UP` beside `rates`' identical one, which is two homes for
# one decision and the place drift starts. `PAISE` stays here because it is a different
# fact — the DISPLAY quantum, two decimals, not the four `MONEY_Q` stores at.
PAISE = Decimal("0.01")

# Zero, AT THE PAISE SCALE, and the scale is the whole reason it is named.
#
# Every money and minute figure in a billing response crosses the wire as the digits
# `str(Decimal)` produces, so `Decimal("0")` serializes as `"0"` where `Decimal("0.00")`
# serializes as `"0.00"` — the same number and a different string, on a field a browser
# renders verbatim. `max(Decimal("0"), x)` returns the FIRST argument when the two are
# equal, so a bare zero in a floor expression silently changes the shape of a field that
# is two decimals everywhere else. Nothing rounds; the literal simply carries the scale.
_ZERO_PAISE = Decimal("0.00")


def to_paise(value: Decimal) -> Decimal:
    """The ONE place a rupee amount is rounded. Every money field in every billing
    response goes through it, so no two surfaces can round the same number differently."""
    return value.quantize(PAISE, rounding=ROUNDING)


def allocate_paise(parts: Sequence[Decimal], total: Decimal) -> tuple[Decimal, ...]:
    """Quantize `parts` to two decimals so they add up to EXACTLY `total`.

    **The defect this exists for.** `to_paise` applied to each part independently does
    not sum to `to_paise` of the whole: two rungs of 5.005 and 4.995 minutes are a total
    of 10.00, and rounding each gives 5.01 + 5.00 = 10.01. Every surface in this module
    publishes both a breakdown and its total, and every one of them promised in a
    docstring that the parts add up. They did not, and the paisa came out on the client's
    invoice as a line reading "5.00 min at ₹3.75/min" beside an amount of ₹18.69.

    **The method is LARGEST REMAINDER** (the Hare-quota apportionment rule, and what
    every invoicing system that has to split a total across lines ends up using): floor
    every part to paise, then hand the paise still owed to the parts with the biggest
    discarded fraction, one each, ties by position. Two properties follow and both are
    what the callers need — the parts sum to `total` exactly, and no part is more than
    one paisa away from its own exact value.

    `ROUND_FLOOR` here is not a second money-rounding decision competing with
    `ROUNDING`: nothing is left rounded down. The floor is the first half of an
    allocation whose remainder is distributed in full, so the OUTPUT is exact and the
    mode is an implementation detail of getting there. It is passed explicitly for the
    reason every quantize in this repo is (`billing/rates.ROUNDING`) — the ambient
    `decimal` context is process-global and mutable.

    Rejected: deriving the last part by subtraction, which is the idiom `split_overage`
    already uses for TWO parts and which is correct there. It does not survive three:
    three buckets of 0.005 minutes total 0.01, and `total - to_paise(a) - to_paise(b)`
    is **-0.01** — a negative minute count on a panel.

    Raises when `total` is not the parts' own total (a caller pairing a breakdown with a
    figure summed from somewhere else), because the alternative is to silently return
    parts that do not add up — the exact failure this function was written to end.
    """
    if not parts:
        return ()
    floors = [part.quantize(PAISE, rounding=ROUND_FLOOR) for part in parts]
    owed = int((total - sum(floors, Decimal("0"))) / PAISE)
    if not 0 <= owed <= len(parts):
        raise ValueError(
            f"allocate_paise: {total} is not the total of the {len(parts)} parts given "
            f"(it differs from their sum by more than rounding can explain)"
        )
    # Biggest discarded fraction first; `index` breaks ties so the result depends on the
    # caller's own order and never on set/dict iteration.
    order = sorted(range(len(parts)), key=lambda index: (floors[index] - parts[index], index))
    allocated = list(floors)
    for index in order[:owed]:
        allocated[index] += PAISE
    return tuple(allocated)


def rate_to_display(rate: Decimal) -> Decimal:
    """A RATE is not a rupee amount and must not be rounded like one.

    `overage_rate` is NUMERIC(12,4), so a plan may legitimately quote ₹7.1250/min.
    Quantizing that to ₹7.13 for display while billing the unrounded rate makes the
    invoice line fail the only arithmetic a client ever does on it — qty * unit = amount
    — by ₹0.10 on twenty minutes. So: paise when the rate IS a whole number of paise
    (the normal case, and ₹8.00 reads better than ₹8.0000), full precision otherwise.
    """
    paise = to_paise(rate)
    return paise if paise == rate else rate.normalize()


@dataclass(frozen=True, slots=True)
class Balance:
    amount_inr: Decimal
    is_low: bool

    @property
    def is_exhausted(self) -> bool:
        return self.amount_inr <= Decimal("0")


async def lock_tenant_credits(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize every credit write for this tenant for the rest of the transaction.

    Take it BEFORE any read the write depends on — the balance read, and equally the
    idempotency lookup that decides whether to write at all. A dedupe check outside the
    lock is the same check-then-write hole as a stale balance read: two runs both see
    "not charged yet" and both append.

    A row lock on the newest entry is NOT a substitute (module docstring): under READ
    COMMITTED a second writer blocked on it re-checks the row it locked, not the query,
    so it never sees the row that was just inserted. Released at transaction end.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"credit:{tenant_id}"},
    )


async def _newest_balance(session: AsyncSession, tenant_id: UUID) -> Decimal:
    """The newest entry's `balance_after` — one indexed row read, not an aggregate,
    which is exactly why `balance_after` is stored. `get_balance` and `record_entry`
    share it so the definition of "newest" can never drift between the two."""
    amount = (
        await session.execute(
            text(
                "SELECT balance_after FROM credit_ledger WHERE tenant_id = :tid "
                "ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id},
        )
    ).scalar()
    # `Decimal(str(...))`, never `Decimal(...)` — the one convention every other NUMERIC
    # read in this tree keeps, and this was the single site that did not. psycopg maps
    # `numeric` to `Decimal` today, so the two agree; the day a driver, a pool wrapper or
    # a type adapter hands back a float instead, `Decimal(2500.10)` is
    # 2500.0999999999999090505298227071762084960937500 and the wallet balance carries the
    # binary error for ever, while `Decimal(str(2500.10))` is the amount. One character
    # of insurance on the hottest money read in the product (hard rule 7).
    return Decimal(str(amount)) if amount is not None else Decimal("0")


async def get_balance(session: AsyncSession, *, tenant_id: UUID) -> Balance:
    """The newest entry's `balance_after`."""
    balance = await _newest_balance(session, tenant_id)
    return Balance(amount_inr=balance, is_low=balance < LOW_BALANCE_INR)


async def record_entry(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    delta: Decimal,
    reason: CreditReason,
    ref: str | None = None,
    meta: dict[str, Any] | None = None,
    allow_negative: bool = False,
) -> Balance:
    """Append one entry and return the new balance.

    `allow_negative=False` refuses a charge that would overdraw. The exception is
    deliberate: usage recorded AFTER a call completes must always land, because the
    call already happened and refusing to record it would hide a real cost. Prevention
    belongs at the pre-dispatch gate, not at the accounting layer.

    The read-decide-write runs under a per-tenant advisory lock (see the module
    docstring for why a row lock on the newest entry is not enough), so two concurrent
    charges cannot both compute from the same starting balance.
    """
    if delta == 0:
        return await get_balance(session, tenant_id=tenant_id)

    await lock_tenant_credits(session, tenant_id)
    current = await _newest_balance(session, tenant_id)
    new_balance = current + delta

    if new_balance < 0 and not allow_negative:
        raise ProblemError.business_rule(
            "insufficient_credits",
            "This account does not have enough credit for that.",
            remediation="Top up the credit balance and try again.",
        )

    # `clock_timestamp()`, NOT `now()`. `now()` is TRANSACTION-start time, so a
    # transaction that did other work first (the post-call pipeline does plenty before
    # it charges) stamps its entry EARLIER than a top-up that started later and
    # committed first — even though the advisory lock correctly serialized them. The
    # ledger then reads back out of write order and `_newest_balance` returns a balance
    # that is missing a real entry. `clock_timestamp()` is the moment of the INSERT,
    # and because the lock is held across read-decide-write it is strictly increasing
    # per tenant.
    await session.execute(
        text(
            "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :delta, :reason, :ref, "
            ":balance, clock_timestamp(), CAST(:meta AS jsonb), clock_timestamp())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "delta": delta,
            "reason": reason,
            "ref": ref,
            "balance": new_balance,
            "meta": json.dumps(meta) if meta else None,
        },
    )
    log.info(
        "credit_entry",
        extra={"tenant_id": str(tenant_id), "reason": reason, "balance_after": str(new_balance)},
    )
    return Balance(amount_inr=new_balance, is_low=new_balance < LOW_BALANCE_INR)


class LedgerEntryRef(NamedTuple):
    """One ledger entry, located by its `ref`. A NamedTuple because the callers of the
    lookup read it differently — some by name, one positionally — and one shape that
    answers all of them beats a second dataclass that has to be kept in step."""

    entry_id: UUID
    amount_inr: Decimal


async def find_entry_by_ref(
    session: AsyncSession, *, tenant_id: UUID, reason: CreditReason, ref: str
) -> LedgerEntryRef | None:
    """THE idempotency lookup for every keyed writer on this ledger.

    **It takes the lock itself, and that is the point.** The call sites used to carry
    their own copy of this query and rely on their author remembering to call
    `lock_tenant_credits` first; a check-then-write outside that lock is precisely how
    duplicate pairs got onto this ledger, because two concurrent runs both read "not
    credited yet" and both append. Making the lookup acquire the lock means the
    ordering is not something a future caller can get wrong: there is no way to reach
    this read from outside the critical section. `pg_advisory_xact_lock` is re-entrant
    within a transaction and released at its end, so a caller that also takes the lock
    explicitly (they do, at the top of their transaction, to cover the writes around
    this read as well) costs nothing and deadlocks nothing.

    **`reason` IS PART OF THE KEY, never an afterthought.** `ref` is not one namespace:
    a `usage` row carries a call id, a `topup` row carries whatever the bank printed,
    and an `adjustment` row carries a reference this module derives. The system
    TOLERATES the collision rather than preventing it, in exactly the same three places
    `ux_credit_ledger_tenant_reason_ref` does (migration f9c2b41a8e57), so a lookup that
    dropped the reason would answer for the wrong entry.
    """
    await lock_tenant_credits(session, tenant_id)
    row = (
        await session.execute(
            text(
                "SELECT id, delta FROM credit_ledger WHERE tenant_id = :tid "
                "AND reason = :reason AND ref = :ref ORDER BY occurred_at DESC, id DESC LIMIT 1"
            ),
            {"tid": tenant_id, "reason": reason, "ref": ref},
        )
    ).first()
    if row is None:
        return None
    return LedgerEntryRef(entry_id=UUID(str(row[0])), amount_inr=Decimal(str(row[1])))


async def find_topup(session: AsyncSession, *, tenant_id: UUID, ref: str) -> LedgerEntryRef | None:
    """Has this payment reference already been credited?

    The manual UTR route and the Razorpay receiver both call this one function, so the
    two cannot drift apart on the next fix. It keeps its own name rather than every
    caller spelling `reason="topup"` because the SCOPE is the contract: a payment
    reference must never collide with the call id a usage row carries in the same
    column, and a name says that where an argument only implies it.
    """
    return await find_entry_by_ref(session, tenant_id=tenant_id, reason="topup", ref=ref)


# --- compensating adjustments (SURFACES §1) ------------------------------------
#
# Hard rule 4 in the one place it costs an operator something: an entry written to the
# wrong wallet, or for the wrong amount, cannot be edited or deleted. It is corrected by
# APPENDING a new entry with the opposite sign, and these three primitives are what the
# admin route appends with. `scripts/reconcile_credit_ledger.py` does the same thing for
# the one failure it can detect on its own (a duplicated `(ref, reason)` group); this is
# the same repair for the failures only a human can see.

ADJUSTMENT_REF_PREFIX: Final = "adjust"

# The `meta.kind` every operator-issued adjustment carries. `reason` is constrained to
# four values by `ck_credit_ledger_reason_enum`, so WHAT an adjustment is lives in the
# ref prefix and in `meta.kind` rather than in a fifth reason — the same choice the
# reconciler made for `duplicate_ledger_entry`.
ADJUSTMENT_META_KIND: Final = "operator_adjustment"


def adjustment_ref(*, entry_id: UUID, amount_inr: Decimal) -> str:
    """The compensating entry's own reference — traceable, distinct, and THE idempotency
    key, enforced by `ux_credit_ledger_tenant_reason_ref` rather than by a reader's `if`
    (D-63's argument, applied to the writer that has no bank reference of its own).

    Three jobs, each of which constrains the shape:

    1. **Traceability.** It names the entry it corrects, so a reader who finds this row
       on the ledger can go straight to the row that caused it without opening `meta`.
    2. **It must not be the corrected entry's own ref.** Reusing `UTR-900011` would put
       two rows on one `(tenant_id, reason, ref)` key for `topup`… and none at all for a
       correction of a `usage` row, which shares the column with call ids.
    3. **It is content-addressed over (entry, amount), so a double submission is a
       no-op.** An adjustment has no UTR — nothing external identifies it — so the key
       has to be derived from what the operator is asking for. The same request twice
       derives the same ref, the unique index refuses the second insert, and the route
       returns the entry that already exists. A caller-minted key was rejected for
       precisely the failure this must survive: a second CLICK, which mints a second
       key and would deduct twice.

    The cost is stated rather than hidden: two GENUINELY distinct corrections of the
    same amount against the same entry collapse onto one key, and the second is reported
    as an already-recorded replay. That is visible (the route names the existing entry
    and says nothing moved), it is the safe direction on money leaving a client's
    wallet, and the operator's remedy — a different amount, or the entry the second
    error actually belongs to — is one field away.

    The amount is quantized through `to_paise` so `50000.0` and `50000.00` are one key
    and not two.
    """
    return f"{ADJUSTMENT_REF_PREFIX}:{entry_id}:{to_paise(amount_inr)}"


@dataclass(frozen=True, slots=True)
class CorrectableEntry:
    """A ledger entry as a correction target: what it moved, and what is left to undo."""

    entry_id: UUID
    delta: Decimal
    reason: str
    #: The magnitude already taken back by adjustments naming this entry.
    reversed_inr: Decimal

    @property
    def reversible_inr(self) -> Decimal:
        """How much of this entry can still be compensated.

        Clamped at zero rather than allowed to go negative: a fully reversed entry has
        nothing left to give, and a negative "remaining" would read as a licence to
        reverse in the other direction.

        **ONE LEVEL, and the residual is deliberate.** An adjustment is itself a ledger
        entry and may itself be corrected ("I corrected the wrong line"), which is why
        `read_correctable_entry` accepts one as a target. This figure does NOT net that
        second correction back out of the FIRST entry's ceiling: reverse a ₹1,000 top-up
        and then reverse the reversal, and the top-up still reads ₹0.00 left even though
        the money is back on the wallet.

        Netting it out properly is an alternating sum over the whole correction chain
        (`|A| minus |B| plus |C| ...`), which is a recursive walk with a cycle guard on the money
        path — and it would buy nothing an operator needs, because the correction chain
        does not dead-end: the entry to correct next is the NEWEST one, which carries its
        own full ceiling and is the row at the top of the ledger they are looking at.
        Erring SHORT is also the safe direction — this ceiling exists to catch a typo, and
        a ceiling that is occasionally too tight refuses a correction, while one that is
        occasionally too loose lets somebody take back more than an entry ever put in.
        """
        return max(Decimal("0"), abs(self.delta) - self.reversed_inr)

    def compensating_delta(self, amount_inr: Decimal) -> Decimal:
        """The signed delta that takes `amount_inr` of this entry back.

        **The sign is derived from the entry, never from the operator.** Reversing a
        top-up is a debit and reversing a usage charge is a credit; asking a human to
        get that right on a form is asking for the one mistake that cannot be undone by
        another form. The API therefore takes a positive magnitude and this decides the
        direction.
        """
        return -amount_inr if self.delta > 0 else amount_inr


async def reversed_amounts(
    session: AsyncSession, *, tenant_id: UUID, entry_ids: Sequence[UUID]
) -> dict[UUID, Decimal]:
    """How much of each of these entries adjustments have already taken back.

    Keyed on `meta.corrects_entry_id` ALONE, deliberately — not on `meta.kind` as well.
    Any adjustment that claims to correct an entry counts against what is left of it; a
    filter on our own `kind` would understate the total the moment a second writer
    appears, and understating it is what would let one entry be reversed twice over.

    Bounded by the ids asked about rather than scanning the wallet's whole history, so
    the ledger read that calls this stays proportional to the page it is rendering.
    """
    if not entry_ids:
        return {}
    rows = (
        await session.execute(
            text(
                "SELECT meta->>'corrects_entry_id', COALESCE(SUM(abs(delta)), 0) "
                "FROM credit_ledger WHERE tenant_id = :tid AND reason = 'adjustment' "
                "AND meta->>'corrects_entry_id' = ANY(CAST(:ids AS text[])) "
                "GROUP BY 1"
            ),
            {"tid": tenant_id, "ids": [str(entry_id) for entry_id in entry_ids]},
        )
    ).all()
    return {UUID(str(row[0])): Decimal(str(row[1])) for row in rows}


async def read_correctable_entry(
    session: AsyncSession, *, tenant_id: UUID, entry_id: UUID
) -> CorrectableEntry | None:
    """One entry of this wallet, with the arithmetic a correction needs. None = absent.

    `tenant_id` is in the predicate as well as in RLS, for the reason `charge_for_call`
    gives: RLS fails the query closed either way, and naming it makes the answer depend
    on the argument rather than on which session happened to be handed in.

    MUST be called with `lock_tenant_credits` held when a write depends on it — the
    remaining-reversible figure is the check half of a check-then-write.
    """
    row = (
        await session.execute(
            text(
                "SELECT id, delta, reason FROM credit_ledger WHERE tenant_id = :tid AND id = :eid"
            ),
            {"tid": tenant_id, "eid": entry_id},
        )
    ).first()
    if row is None:
        return None
    already = await reversed_amounts(session, tenant_id=tenant_id, entry_ids=[entry_id])
    return CorrectableEntry(
        entry_id=UUID(str(row[0])),
        delta=Decimal(str(row[1])),
        reason=str(row[2]),
        reversed_inr=already.get(entry_id, Decimal("0")),
    )


# --- restating an UNDER-credited payment (D-89) --------------------------------
#
# The adjustment above answers ONE of the two ways a recorded payment can be wrong. It
# takes credit back off a NAMED ENTRY, bounded by what that entry moved — so it closes
# over-crediting and cannot touch the opposite mistake: ₹5,000 recorded against a UTR
# the bank actually moved ₹50,000 on. Re-posting the reference with the right amount is
# a 409 (deliberately — that refusal is the only thing stopping one bank transfer being
# credited twice), and there is nothing on the ledger to take back.
#
# The repair is a SECOND `topup` row for the SAME bank transfer, and the whole design
# turns on the pair still reading as one payment:
#
#     ref  = restated:<payment_ref>:<the corrected TOTAL>
#     meta = {"kind": "topup_restatement", "payment_ref": <payment_ref>, …}
#
# The workaround this replaces was a second top-up under an ANNOTATED reference
# (`UTR-123-part2`). That is not a smaller version of the same thing: it puts a string
# on the ledger that the bank never printed, so the wallet carries two payment
# references for one transfer and a reconciliation keyed on the reference — the entire
# reason the reference is the idempotency key — silently stops balancing. Here the
# reference is never re-invented; the second row NAMES it.

# WHICH BANK TRANSFER a ledger row belongs to, as SQL. NULL for every row that is not a
# payment: `ref` is three namespaces sharing one column (a call id on `usage`, a key we
# derive on `adjustment`, whatever the bank printed on `topup` — migration f9c2b41a8e57
# argues this at length), so a grouping that dropped the reason would fold a call id in
# beside a UTR.
#
# `COALESCE(meta->>'payment_ref', ref)` rather than a column of its own, and that is a
# decision rather than a shortcut. The ANCHOR row's `ref` IS the payment reference —
# `find_topup` and `ux_credit_ledger_tenant_reason_ref` both depend on that and neither
# may change — so a restatement CANNOT reuse it and carries the reference in `meta`
# instead. Reading both makes the pairing true for every row ever written, including the
# Razorpay receiver's and everything that predates this feature, with no backfill and no
# migration. Adding `payment_ref` to the anchor row as well was rejected: it would create
# two columns that must agree for ever on the hottest path in this module, with nothing
# able to bring them back into step once they did not.
PAYMENT_REF_SQL: Final = "CASE WHEN reason = 'topup' THEN COALESCE(meta->>'payment_ref', ref) END"

RESTATEMENT_REF_PREFIX: Final = "restated"

# The `meta.kind` every restating entry carries, for the reason `ADJUSTMENT_META_KIND`
# exists: `reason` is constrained to four values by `ck_credit_ledger_reason_enum`, and
# this row's reason is `topup` because the money genuinely IS a top-up — it is part of a
# bank transfer that arrived. Filing it as an `adjustment` would understate "payments
# received this month" by the difference and overstate corrections by the same figure,
# and `runbooks/topup-payments.md` §5 — whose first query is `WHERE reason = 'topup'` —
# would stop showing the row that answers "the payment went through and the wallet did
# not move".
RESTATEMENT_META_KIND: Final = "topup_restatement"


def restatement_ref(*, payment_ref: str, credited_total_inr: Decimal) -> str:
    """The restating entry's own reference — THE idempotency key, enforced by
    `ux_credit_ledger_tenant_reason_ref` rather than by a reader's `if` (D-63).

    Content-addressed like `adjustment_ref`, and over the CORRECTED TOTAL rather than
    over the difference it happens to credit. That single choice is what makes this key
    strictly better than the adjustment's, and it is worth spelling out because the
    adjustment had to state a real cost:

    - `adjustment_ref` keys on a MAGNITUDE TO MOVE. Two genuinely distinct partial
      corrections of the same size against one entry therefore collapse onto one key,
      and the second is reported as an already-recorded replay — a real act lost, in the
      safe direction.
    - This keys on a STATE TO REACH. Two assertions that this UTR moved ₹50,000 are not
      two acts colliding; they are one assertion made twice, and the second time it is
      already true. There is no distinct act left to lose, so the collision has no cost
      at all.

    It is also why a second click is safe with no reader involved: the key is a function
    of what the operator asserts, never of when they asserted it. A double submission
    derives one ref, the index refuses the second insert, and the route hands back the
    row the first click wrote. A caller-minted key was rejected for the same failure
    D-87 rejected it for — a second click mints a second key.

    It names the payment it restates, so a reader who finds this row on the ledger can
    pair it with the bank transfer without opening `meta`. Quantized through `to_paise`,
    so `50000.0` and `50000.00` are one key and not two.
    """
    return f"{RESTATEMENT_REF_PREFIX}:{payment_ref}:{to_paise(credited_total_inr)}"


@dataclass(frozen=True, slots=True)
class RecordedPayment:
    """One bank transfer, as this wallet holds it — however many rows that took."""

    payment_ref: str
    #: EVERYTHING this reference has credited: the anchor entry plus every restatement of
    #: it. Deliberately NOT reduced by adjustments — an adjustment is a separate,
    #: explained layer with its own row and its own reason, and this figure answers "what
    #: have we credited against this UTR", which is the question a bank statement asks.
    credited_inr: Decimal
    #: How many ledger rows make up the payment. 1 = it has never been restated.
    rows: int
    #: When the payment first landed on the ledger. The anchor's instant, not the newest
    #: restatement's — a payment is dated by when it arrived.
    first_at: datetime


async def recorded_payments(
    session: AsyncSession, *, tenant_id: UUID, payment_refs: Sequence[str]
) -> dict[str, RecordedPayment]:
    """What each of these bank transfers has credited, in ONE grouped read.

    Bounded by the references asked about rather than scanning a wallet's whole history
    — the shape `reversed_amounts` uses, for the same reason. But each total is summed
    over ALL of that payment's rows, on or off the page that asked: a figure that
    silently omitted an older row would be a lie about money, which costs more than a
    slower query ever does.

    The empty case returns without touching the database, for the reason
    `reversed_amounts` does: a wallet with no payments is the first thing every new
    tenant has, and `= ANY('{}')` is a degenerate predicate to build on the commonest
    path in the product.
    """
    if not payment_refs:
        return {}
    rows = (
        await session.execute(
            text(
                # `reason = 'topup'` is in the predicate as well as inside PAYMENT_REF_SQL
                # because it is what keeps this an index-eligible scan of one tenant's
                # payments rather than an evaluation of the CASE over every row they own.
                f"SELECT {PAYMENT_REF_SQL} AS payment_ref, COALESCE(SUM(delta), 0), "
                "COUNT(*), MIN(occurred_at) FROM credit_ledger "
                "WHERE tenant_id = :tid AND reason = 'topup' "
                f"AND {PAYMENT_REF_SQL} = ANY(CAST(:refs AS text[])) "
                "GROUP BY 1"
            ),
            {"tid": tenant_id, "refs": list(payment_refs)},
        )
    ).all()
    return {
        str(row[0]): RecordedPayment(
            payment_ref=str(row[0]),
            credited_inr=Decimal(str(row[1])),
            rows=int(row[2]),
            first_at=row[3],
        )
        for row in rows
    }


async def read_recorded_payment(
    session: AsyncSession, *, tenant_id: UUID, payment_ref: str
) -> RecordedPayment | None:
    """This one bank transfer, or None when nothing on this wallet carries the reference.

    MUST be called with `lock_tenant_credits` held when a write depends on it: the
    credited total is the check half of a check-then-write, exactly as
    `read_correctable_entry`'s remaining-reversible figure is. Two operators restating
    one payment at the same moment would otherwise both read the same starting total and
    both credit the difference.
    """
    found = await recorded_payments(session, tenant_id=tenant_id, payment_refs=[payment_ref])
    return found.get(payment_ref)


async def charge_for_call(
    session: AsyncSession, *, tenant_id: UUID, call_id: UUID, amount_inr: Decimal
) -> None:
    """Debit a completed call. Idempotent by `ref` — the post-call pipeline is
    re-runnable, and a ledger that double-charges on a replay is worse than no ledger.

    The dedupe lookup runs UNDER the per-tenant advisory lock, taken before it. A
    re-run is not only a sequential replay: ARQ retries and the reconciliation poller
    can put two runs of one call in flight at the same moment, and a check-then-write
    outside the lock lets both read "not charged yet" and both append. That is the same
    hole the top-up route takes the lock early to close.

    `allow_negative=True`: the call already happened. A cost we refuse to record is a
    cost we later cannot explain.
    """
    if amount_inr <= 0:
        return
    await lock_tenant_credits(session, tenant_id)
    already = (
        await session.execute(
            # `tenant_id` is in the predicate as well as in RLS: it is what makes this
            # an index scan, and it stops a call id ever being read across a scope this
            # session was not supposed to be answering for.
            text(
                "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = :ref "
                "AND reason = 'usage' LIMIT 1"
            ),
            {"tid": tenant_id, "ref": str(call_id)},
        )
    ).first()
    if already:
        return
    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-amount_inr,
        reason="usage",
        ref=str(call_id),
        allow_negative=True,
    )


async def plan_tier_of(session: AsyncSession, tenant_id: UUID) -> str:
    tier = (
        await session.execute(
            text("SELECT plan_tier FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    return str(tier or "managed")


# --- reporting -----------------------------------------------------------------
#
# Two audiences, two panels, one ledger. The CLIENT sees what they used and what it
# will cost them. WE see what it cost us next to that, which is D-12's whole reason
# for putting `unit_cost_paid` on every usage row: margin is a query, not a monthly
# spreadsheet exercise.
#
# The client panel never shows `unit_cost_paid`. Our supplier pricing is commercially
# ours, and a client who can see it is a client negotiating against it.

# Billing months are IST (conventions: UTC in the DB, IST at the edge). A month that
# rolls over at 05:30 IST would put an evening call in the wrong month and make a
# client's invoice disagree with their own diary.
#
# **`AT TIME ZONE`, NOT `+ interval '5 hours 30 minutes'`, AND THAT IS A CORRECTNESS FIX.**
# `to_char` on a `timestamptz` renders the instant in the SESSION's `TimeZone`
# (postgresql.org/docs/16/functions-formatting.html), so adding the offset first and
# formatting second is the IST month only while that setting happens to be UTC. It is UTC
# on this database and nothing in `apps/` sets it — but that made a money expression
# depend on an environment variable, and the failure is silent. Measured against this
# pg16, one instant, three session zones:
#
#     occurred_at = 2026-08-31 17:30:00+00   (= 23:00 IST on the 31st, an AUGUST call)
#       TimeZone=UTC             + interval -> 2026-08   AT TIME ZONE -> 2026-08
#       TimeZone=Asia/Kolkata    + interval -> 2026-09   AT TIME ZONE -> 2026-08
#       TimeZone=America/New_York+ interval -> 2026-08   AT TIME ZONE -> 2026-08
#
# `timestamptz AT TIME ZONE 'Asia/Kolkata'` converts to a `timestamp` whose fields ARE
# the IST wall clock, so `to_char` has nothing left to interpret and the session cannot
# change the answer. The named zone rather than a literal `+05:30` for the same reason the
# Python side uses a fixed offset with a comment: India has no DST today, and if that ever
# changed the zone would follow it and a hardcoded offset would not.
#
# TWO SPELLINGS, AND THE SPLIT IS BY WHAT THE SQL DOES WITH THE MONTH, not by taste.
# `_IST_MONTH` RENDERS a row's own month and is the only form that can: it is what
# `ai_quota._INSERT_USAGE` returns out of `RETURNING`, so the counter the platform brake
# reads is stamped by the database's clock rather than the API process's. Nothing filters
# with it any more — see `_IST_MONTH_WINDOW` below for why it cannot.
_IST_MONTH = "to_char(occurred_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM')"

# WHY FILTERING IS A RANGE AND NOT THAT STRING COMPARISON. Every sentence above stays
# true and `plans.ist_month_window` is where it now lives: it builds the same IST month from the
# same NAMED zone, in Python, and hands SQL two `timestamptz` bounds — so the session's
# `TimeZone` still cannot reach the answer, which is the property the paragraph above
# exists to protect.
#
# What the rendered form ALSO was is unindexable. `to_char` is STABLE rather than
# IMMUTABLE (its output depends on `DateStyle`/`lc_time`), so PostgreSQL will use it
# neither as an index condition nor as an index EXPRESSION, and every money rollup
# filtered the tenant's whole metering history one row at a time. Measured on 225,000
# `usage_events` for one tenant, PG16: 84.0 ms / 3,829 buffers rendered, 2.2 ms / 76
# buffers as this range against `ix_usage_events_tenant_occurred` (migration
# `c9e2a7b41d63`).
#
# HALF-OPEN, `>= :month_from AND < :month_to`, the same SQL:2011 application-time reading
# `plan_in_effect_sql` uses: no instant lands in two months and none lands in neither.
_IST_MONTH_WINDOW = "occurred_at >= :month_from AND occurred_at < :month_to"


def _month_bounds(month: str) -> dict[str, datetime]:
    """The two binds `_IST_MONTH_WINDOW` reads, so a caller cannot name the window and
    then supply half of it."""
    start, end = ist_month_window(month)
    return {"month_from": start, "month_to": end}


# "…and it is a CALL row", for the cost query that prices minutes. Spelled NEGATIVELY
# rather than as a positive list of call unit types, and that is deliberate: a positive
# list would silently drop `number_rental` and any unit added tomorrow out of the client's
# own cost, which is the direction that costs a client money. Excluding the two units
# whose whole point is that WE pay for them is the narrow, checkable statement. Derived
# from the one constant in `billing/models.py`, never retyped, so a third AI unit type
# cannot appear in a client's spend by omission.
_NOT_AI_UNITS = "unit_type <> ALL(ARRAY[" + ", ".join(f"'{u}'" for u in AI_ASSIST_UNIT_TYPES) + "])"

# `telephony_s` is metered in SECONDS and every client-facing figure is in MINUTES. The
# divisor is a `Decimal` and named, so the conversion happens in exactly one place and
# cannot be spelled `60.0` (a float) by the next person to need it.
_SECONDS_PER_MINUTE = Decimal("60")


def current_billing_month() -> str:
    """Now, as an IST billing month. The offset lives in `plans.ist_billing_month` so
    that the tenant's onboarding month (`billing/charges.py`) and this one cannot be
    computed two different ways."""
    return ist_billing_month(datetime.now(UTC))


def split_overage(
    *,
    overage_min: Decimal,
    billable_premium: Decimal,
    billable_value: Decimal,
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> tuple[Decimal, Decimal]:
    """Divide the month's overage minutes between the two TTS rungs.

    Returns `(premium_overage, value_overage)`, which ALWAYS add to `overage_min`
    exactly — the second is derived by subtraction rather than computed independently,
    so the two published figures cannot drift by a paisa from the total the client is
    charged on. That matters more than it sounds: the invoice promises that every line
    multiplies out and that the lines sum to the subtotal.

    **The inputs are already paise-quantized** (`_tier_totals` allocates them, and
    `overage_min` is derived from their sum), so this arithmetic neither rounds nor
    needs to: subtraction of two-decimal Decimals is exact and the outputs are the
    figures the invoice prints and prices. That was NOT true when the tier minutes
    arrived unquantized — the caller rounded the pair for display AFTER this function
    had guaranteed their sum, which is precisely how a guaranteed identity stopped
    holding on the surface that publishes it.

    **A plan with no value rate puts everything on the single rate.** `rate_value is
    None` returns `(overage_min, 0)`, which reproduces the pre-`b1d5c8e73f04` arithmetic
    bit for bit — that is what makes the column safe to add to every existing plan.

    **The included allowance is spent on the DEARER rung first.** A plan with 500
    included minutes and a mix of premium and value calls could allocate the free
    minutes either way, and the allocation decides the bill. Consuming the expensive
    rung first leaves the CHEAPER minutes to be charged for, which is the client's
    favour — the same asymmetry `billing/rates.py` applies when it bills an unprovable
    tier as `value`. It is written as "the dearer rung" rather than "the premium rung"
    so it stays client-favourable even if a founder ever quotes a value rate ABOVE the
    premium one; the rule is about price, not about the label.
    """
    if rate_value is None:
        return overage_min, _ZERO_PAISE

    dearer_is_premium = rate >= rate_value
    dearer = billable_premium if dearer_is_premium else billable_value
    covered = min(included_min, dearer)
    dearer_overage = max(_ZERO_PAISE, dearer - covered)
    # Clamped into [0, overage_min]. It cannot bind on the path `usage_summary` takes —
    # the rungs are allocated FROM the same total `overage_min` is derived from, so the
    # dearer rung's overage is bounded by construction — and it is kept anyway because
    # this function is exported and takes its three quantities as arguments: a caller
    # that pairs a breakdown with a total from somewhere else must still get two
    # non-negative figures that add up, not a negative minute count. That is a PROVED
    # guard rather than an unreachable one — `tests/value_tier_rate_test.py::
    # test_the_two_rungs_always_add_to_the_overage_total` hands it exactly such a pair,
    # which is the shape `models.assert_units_are_disjoint` argues for.
    dearer_overage = min(dearer_overage, overage_min)
    cheaper_overage = overage_min - dearer_overage
    if dearer_is_premium:
        return dearer_overage, cheaper_overage
    return cheaper_overage, dearer_overage


@dataclass(frozen=True, slots=True)
class OverageRung:
    """One rung of the overage, priced: what it charges for, at what rate, for how much.

    `label` is the rung's identity (`premium` / `value`), not its wording — the invoice
    supplies the words, because "value voice" is a phrase on a client's document and
    this module has no business choosing it.
    """

    label: TtsTier
    minutes: Decimal
    rate_inr: Decimal
    amount_inr: Decimal


def overage_rungs(
    *,
    premium_min: Decimal,
    value_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> tuple[OverageRung, ...]:
    """THE one place a rung's money is computed. Both surfaces that state it call this.

    `usage_summary` sums these into `overage_cost_inr` and `build_invoice` prints them
    as lines, so **the panel's total is the sum of the printed lines by construction** —
    it is the same numbers added in the same order, not two computations reconciled
    afterwards.

    What that replaces is worth naming, because the replaced version looked correct.
    The panel priced the whole overage in ONE quantization (`to_paise(premium * rate +
    value * value_rate)`) while the invoice quantized each line, so the two disagreed by
    a paisa and `invoice._reconcile_overage` bent the LAST LINE to close the gap. On
    round rates that hid; on `_tier_totals`' unquantized minutes it did not, and a real
    invoice printed "5.00 min at ₹3.75/min ... ₹18.69". A line that does not multiply
    out is the first thing an accountant checks, and no amount of internal consistency
    survives it.

    A plan with no value rate has ONE rung carrying every overage minute, which is the
    shape every invoice had before `plans.overage_rate_value` existed — and `rate_value
    is None` is "this plan quotes no separate value rate", never "the value rung is
    free".
    """
    if rate_value is None:
        both = premium_min + value_min
        return (OverageRung("premium", both, rate, to_paise(both * rate)),)
    return (
        OverageRung("premium", premium_min, rate, to_paise(premium_min * rate)),
        OverageRung("value", value_min, rate_value, to_paise(value_min * rate_value)),
    )


#: The rungs, in the order every map in this module lists them. `""` is the third and it
#: is not a tier: it is a row written before tier attribution existed, or by a path that
#: could not attribute one. Reporting keeps the distinction; PRICING folds it into
#: `value`, because a call we cannot prove got the premium voice is never charged the
#: premium rate (SURFACES §2b).
_RUNGS: Final = ("premium", "value", "")


async def rung_seconds(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(SECONDS, our cost) per TTS rung for one billing month. THE query.

    Split out of `_tier_totals` when the meter needed the same month's rungs to price a
    call's increment against (`month_increment`). It returns SECONDS rather than
    minutes deliberately: seconds are what the ledger stores and they are exact, so a
    caller that has to reconstruct "the month before this call" can subtract there and
    quantize afterwards. Subtracting from the QUANTIZED minutes instead would not
    reproduce the state the previous call priced against — `allocate_paise` distributes
    a remainder across the whole set, so it is not linear in any one bucket — and the
    increments would stop telescoping to the month's own total.
    """
    rows = (
        await session.execute(
            # NUMERIC end to end — a SUM of NUMERIC columns and a SUM of their products.
            # Nothing on this path becomes a float (hard rule 7).
            text(
                "SELECT COALESCE(meta->>'tts_tier', ''), "
                "  COALESCE(SUM(qty) FILTER (WHERE unit_type = 'telephony_s'), 0), "
                "  COALESCE(SUM(qty * COALESCE(unit_cost_paid, 0)), 0) "
                f"FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH_WINDOW} "
                f"AND {_NOT_AI_UNITS} "
                "GROUP BY 1"
            ),
            {"tid": tenant_id, **_month_bounds(month)},
        )
    ).all()

    seconds = dict.fromkeys(_RUNGS, Decimal("0"))
    cost = dict.fromkeys(_RUNGS, Decimal("0"))
    for label, secs, spent in rows:
        # An unrecognised label is treated as unattributed rather than trusted: a tier
        # this module does not know is not a tier it can price.
        key = str(label) if str(label) in ("premium", "value") else ""
        seconds[key] += Decimal(str(secs or 0))
        cost[key] += Decimal(str(spent or 0))
    return seconds, cost


def rung_minutes(seconds: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Per-rung SECONDS -> per-rung MINUTES, paise-exact and summing to the month's total.

    The division happens here, once per bucket, rather than in SQL: `SUM(a)/60 + SUM(b)/60`
    and `SUM(a+b)/60` are two roundings of one number and Postgres picks the result scale,
    so dividing per bucket in the query would put the parts and the total a hair apart
    before `allocate_paise` could even see them.
    """
    exact = [seconds[key] / _SECONDS_PER_MINUTE for key in _RUNGS]
    total = to_paise(sum(seconds.values(), Decimal("0")) / _SECONDS_PER_MINUTE)
    return dict(zip(_RUNGS, allocate_paise(exact, total), strict=True))


async def _tier_totals(
    session: AsyncSession, *, tenant_id: UUID, month: str
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """(minutes, our cost) per TTS rung for one billing month.

    THE one definition of "how many minutes ran on which rung". `tier_usage` presents
    it to two panels and `usage_summary` prices against it; a second query would let the
    panel and the bill disagree about the same month, which is the exact defect
    `billing/rates.py` exists to prevent one layer down.

    **THE MINUTES COME BACK ALREADY QUANTIZED TO PAISE, AND SUMMING TO THE MONTH'S
    TOTAL EXACTLY** (`allocate_paise`). They used to come back unquantized and every
    caller rounded its own copy, which meant the three rungs added to a minute count
    one paisa away from the one `usage_summary` published — and, once the overage was
    priced off those rounded rungs, to an invoice line that did not multiply out. There
    is now ONE set of minute figures in the system: these. Everything downstream is
    paise-exact arithmetic on them, so nothing below this function rounds a minute
    again.

    The SQL sums SECONDS and the division happens here, once per bucket, for the same
    reason: `SUM(a)/60 + SUM(b)/60` and `SUM(a+b)/60` are two roundings of one number
    and Postgres picks the result scale, so dividing per bucket in SQL would put the
    parts and the total a hair apart before the allocation could even see them. The cost
    side stays a NUMERIC sum in SQL — it is already exact there, being a sum of
    products rather than a quotient.

    The keys are `premium`, `value` and `""` — the third being rows written before tier
    attribution existed, or by a path that could not attribute one. Reporting keeps that
    distinction; pricing folds it into `value`, because a call we cannot prove got the
    premium voice is never charged the premium rate.

    IT IS ABOUT CALLS, and `_NOT_AI_UNITS` is what keeps it that way. `usage_events` grew
    a second kind of row with D-127: a dashboard assist, which has no call, no TTS rung
    and — per G-3 — no bearing on what the CLIENT pays, because Calevate absorbs it. Left
    unfiltered those rows would land in the `""` bucket and do three wrong things at
    once: inflate `tier_usage.cost_unattributed_inr`, which an operator reads as "calls
    we could not attribute a voice to"; put our absorbed AI cost into a closed month's
    `spend_used_inr` on the CLIENT's panel (`_spend_used` sums this map); and add it to
    `margin_for_tenant`'s cost side without the matching revenue. The AI ledger has its
    own reader (`billing/ai_quota.py::read_ai_quota`) and this one stays about minutes.
    """
    seconds, cost = await rung_seconds(session, tenant_id=tenant_id, month=month)
    return rung_minutes(seconds), cost


@dataclass(frozen=True, slots=True)
class PricedOverage:
    """A whole month's overage, split across the rungs and priced. What an invoice is."""

    #: Minutes past the included allowance. The two rung figures add to this EXACTLY.
    overage_min: Decimal
    premium_min: Decimal
    value_min: Decimal
    rungs: tuple[OverageRung, ...]
    #: The sum of the rungs' amounts — the invoice's overage subtotal, by construction.
    total_inr: Decimal


def priced_overage(
    *,
    minutes_by_rung: Mapping[str, Decimal],
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> PricedOverage:
    """THE one pricing of a month's calling. Every reader of "what does this month's
    overage cost" comes here — the client panel, the invoice's lines, and the live spend
    counter the cap is enforced against.

    **THE DEFECT THIS EXISTS FOR.** There used to be two rules. This one — allowance on
    the DEARER rung first (`split_overage` argues why: the allocation decides the bill and
    consuming the expensive minutes first leaves the cheap ones to be charged for, which
    is the client's favour) — priced the panel and the invoice. The METER priced
    `spend_state.billed_inr` with a different one: the allowance was spent in ARRIVAL
    order and each call's marginal minutes were charged at that call's own rung. The two
    agree whenever a plan quotes ONE rate (`sum of  (over(before+m) - over(before)) x rate` is
    `max(0, total - included) x rate`), which is every plan in the database today because
    `plans.overage_rate_value` is an open founder decision and is NULL everywhere. They
    disagree the moment one is quoted — measured at ₹880.00 against ₹520.00 on a
    two-rung month whose cheap minutes arrived first — and the disagreement lands in two
    places at once: `/c/<slug>/usage` prints both figures, in adjacent cards, for one
    month; and the client's own spend cap is compared against the larger, so their stop
    button stops their outbound calling before their bill justifies it.

    So the meter no longer has a rule. It asks this function what the month costs with
    the call and without it, and charges the difference (`month_increment`).

    **AN UNPRICED PLAN ACCRUES NOTHING**, and that is the same deliberate refusal
    `b1d5c8e73f04` settled and `client_billed_inr` used to carry: `usage_summary` passes
    `Decimal("0")` for a NULL `overage_rate`, `overage_rungs` multiplies by it, and the
    month costs ₹0.00 on the panel, on the counter and on the invoice alike. This
    repository does not invent a price a plan does not quote, and a counter accruing
    ₹6/min beside an invoice charging ₹0 would be two documents about one month.

    `rate_value is None` means "this plan quotes no separate value rate" — one rung
    carrying every overage minute — and never "the value rung is free".
    """
    minutes = sum(minutes_by_rung.values(), _ZERO_PAISE)
    overage_min = max(_ZERO_PAISE, minutes - included_min)
    premium_min, value_min = split_overage(
        overage_min=overage_min,
        billable_premium=minutes_by_rung["premium"],
        # Unattributed folds in with value: SURFACES §2b's rule is that a call we cannot
        # prove got the premium voice is never charged the premium rate.
        billable_value=minutes_by_rung["value"] + minutes_by_rung[""],
        included_min=included_min,
        rate=rate,
        rate_value=rate_value,
    )
    rungs = overage_rungs(
        premium_min=premium_min, value_min=value_min, rate=rate, rate_value=rate_value
    )
    return PricedOverage(
        overage_min=overage_min,
        premium_min=premium_min,
        value_min=value_min,
        rungs=rungs,
        # Summed rather than quantized again: `overage_rungs` already priced each rung to
        # paise and `build_invoice` prints exactly these, so the total IS the sum of the
        # printed lines and there is nothing left to reconcile.
        total_inr=sum((rung.amount_inr for rung in rungs), _ZERO_PAISE),
    )


@dataclass(frozen=True, slots=True)
class MonthIncrement:
    """What ONE call adds to the two month totals `spend_state` counts.

    Both are DIFFERENCES of the same month's ledger read with and without this call, so
    both telescope: whatever order the month's calls meter in, the running totals are
    exactly the figures `usage_summary` publishes for that month. That is the property
    that makes the cap and the client's own panel about the same month.
    """

    #: What this call adds to `usage_summary.minutes_used`. Paise-exact, because that is
    #: the quantum `_tier_totals` allocates the whole month at.
    minutes: Decimal
    #: What this call adds to a MANAGED month's overage bill. Meaningless for a prepaid
    #: tenant, whose every minute is charged at the list price with no allowance in
    #: front of it (`rates.prepaid_billed_inr` is that tier's answer) — the field is
    #: still computed rather than branched on here, because the read it comes from is
    #: the same one `minutes` needs and a second query is what the caller would pay.
    overage_inr: Decimal


async def month_increment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    month: str,
    tier: str,
    seconds: Decimal,
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
) -> MonthIncrement:
    """What one call ADDS to a month's minutes and to its overage bill — the panel's and
    the invoice's own arithmetic, in the currency of a counter.

    **WHY MINUTES ARE HERE AND NOT COMPUTED BY THE CALLER, which is where they were.**
    The meter used to pass its own `duration_s / 60` straight into
    `spend_state.minutes_used`, so the counter accumulated a per-call quotient at the
    column's NUMERIC(14,4) scale while `usage_summary.minutes_used` was the month's total
    seconds divided once and allocated to paise. Two spellings of "how many minutes has
    this tenant used this month", and the cap (`over_cap_sql` compares `minutes_used`) was
    enforced against one while the client's own "minutes left" was published from the
    other. Measured on this tree, four calls of 3847 / 2913 / 611 / 137 seconds:

        spend_state.minutes_used   125.1333   <- the ceiling was judged against this
        usage_summary              125.13     <- and the client was shown this

    The drift is the sum of the per-call rounding errors and it only ever grows within a
    month, so on a busy tenant the two land either side of an integer ceiling and the
    panel says there are minutes left while the gate has already stopped the dialling.
    Deriving the increment from the LEDGER makes the counter equal to the published
    figure exactly rather than approximately: `rung_minutes` guarantees its parts sum to
    `to_paise(total_seconds / 60)`, so the increments telescope to precisely the number
    `usage_summary` prints, and every increment is a two-decimal value the column stores
    without rounding at all.

    `after - before`, where both are `priced_overage` over the month's per-rung SECONDS
    and `before` is the ledger with this call's seconds taken back off its own rung. Two
    properties follow, and they are the whole reason it is a difference rather than a
    formula:

    * **the increments telescope.** Each call's `before` is the previous call's `after`
      (both are computed from the same raw-seconds state by the same function), so the
      running total is EXACTLY the month's own overage cost however many calls there are
      and in whatever order they meter. That is the identity `spend_state.billed_inr`
      has to hold for the cap and the invoice to be about the same rupees.
    * **it can legitimately be NEGATIVE for a rung and still be right overall.** Adding
      premium minutes moves the included allowance onto the premium rung, which increases
      the value rung's overage; only the month total is a meaningful quantity, and only
      the difference of two month totals is a meaningful increment. Pricing the rungs'
      deltas separately would have had to drop or clamp the negative one.

    **MUST be called with `lock_tenant_spend_state` held** and AFTER this call's
    `usage_events` rows are written in the same transaction: the read is the check half
    of a check-then-write over money, and the rows are what makes `after` the after.

    `seconds` is this call's own `telephony_s` quantity and `tier` the rung it was metered
    on — the two values the caller has just written to the ledger.
    """
    after_seconds, _cost = await rung_seconds(session, tenant_id=tenant_id, month=month)
    before_seconds = dict(after_seconds)
    # `max(0, …)` cannot bind on the meter's path — the rows for `seconds` are in this
    # transaction and in this month, so they are in the sum we just read. It is kept
    # because a negative bucket would make `allocate_paise` refuse rather than answer,
    # and a caller that passed seconds the ledger does not hold should get the honest
    # "this call added nothing" instead of an exception on a metered call.
    before_seconds[tier] = max(Decimal("0"), before_seconds[tier] - seconds)
    after_minutes = rung_minutes(after_seconds)
    before_minutes = rung_minutes(before_seconds)
    after = priced_overage(
        minutes_by_rung=after_minutes,
        included_min=included_min,
        rate=rate,
        rate_value=rate_value,
    )
    before = priced_overage(
        minutes_by_rung=before_minutes,
        included_min=included_min,
        rate=rate,
        rate_value=rate_value,
    )
    return MonthIncrement(
        # Summed over the rungs rather than re-divided: `rung_minutes` allocates the
        # month's paise so that its three parts add to `to_paise(seconds / 60)` exactly,
        # which is `usage_summary.minutes_used`. Summing the parts IS that figure; a
        # second division would be a fourth spelling of it.
        minutes=sum(after_minutes.values(), _ZERO_PAISE)
        - sum(before_minutes.values(), _ZERO_PAISE),
        overage_inr=after.total_inr - before.total_inr,
    )


async def usage_summary(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """What the client used this billing month, in their terms.

    Minutes come from `telephony_s`, which is the unit we bill on; the other unit types
    are inputs to OUR cost and are deliberately not shown as separate line items,
    because a client cannot act on "llm_tok_out" and does not buy tokens from us.
    """
    # WHICH MONTH IS "NOW", read ONCE and then handed to everything that needs it.
    #
    # Three places below ask whether the month on screen is the open one — the default
    # for `period`, the staleness test on `spend_state`, and `_spend_used`'s choice
    # between the live counter and the ledger — and each used to take its own reading of
    # the clock. Across 00:00:00 IST on the 1st those readings straddle the roll: the
    # counter row is judged stale against September while `_spend_used` still believes
    # August is open, so it reports the (now zeroed) live counter and August's statement
    # shows ₹0.00 spent beside minutes read correctly from the ledger. The window is one
    # instant a month and the answer is wrong by the whole month, which is the trade
    # that makes a single reading worth passing around.
    today = current_billing_month()
    period = month or today
    # WHICH INSTANT THIS MONTH IS PRICED AT, resolved (and the month validated) BEFORE
    # any query runs — a month we cannot parse is a month we cannot pick a plan for, and
    # a 422 up front beats a ₹0.00 statement for `?month=july`.
    priced_at = month_pricing_instant(period)
    # THE MINUTES AND THE RUNGS COME FROM ONE READ, and it is `_tier_totals`.
    #
    # This function used to sum `telephony_s` itself, in its own query, and then read the
    # per-rung split from `_tier_totals` — two aggregates over the same rows, each
    # rounded on its own. That is how `minutes_used` and the three rungs beside it ended
    # up a paisa apart on one panel. `_tier_totals` now returns paise-exact minutes that
    # sum to the month's total, so the total IS their sum and there is nothing left to
    # disagree.
    # The COST half is deliberately dropped here now: this panel is the client's, and
    # `_tier_totals`' second return is `unit_cost_paid` — our supplier cost, which
    # `_spend_used` used to publish for a closed month (P1.3). `tier_usage` still reads
    # both for the ADMIN margin panel, which is what that number is for.
    tier_minutes, _tier_cost = await _tier_totals(session, tenant_id=tenant_id, month=period)
    minutes = sum(tier_minutes.values(), _ZERO_PAISE)
    row = (
        await session.execute(
            # `tenant_id` is named in the predicate, not left to RLS alone: the plan,
            # the org and the spend state below are all read BY tenant_id, so a session
            # scoped to someone else would otherwise pair this tenant's plan with that
            # tenant's minutes. RLS still fails the query closed; this makes the answer
            # depend on the argument rather than on which session it was handed.
            #
            # Deliberately NOT filtered to call rows: a dashboard-assist row carries no
            # `call_id` and `COUNT(DISTINCT)` ignores NULLs, so the AI ledger cannot
            # inflate a client's call count and does not need a predicate to say so.
            text(
                "SELECT COUNT(DISTINCT call_id) "
                f"FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH_WINDOW}"
            ),
            {"tid": tenant_id, **_month_bounds(period)},
        )
    ).first()
    calls = int(row[0] or 0) if row else 0

    # WHICH PLAN PRICES THIS MONTH. Not the newest row — the row whose valid-time
    # window contains `priced_at` (`billing/plans.py`). For a closed month that instant
    # is the month's last, so a re-rendered July invoice quotes July's terms however
    # many times a plan has changed since; for the current month it is now, so terms
    # dated to start later this month do not price today.
    plan = (
        await session.execute(
            text(
                # The caps read here are the EFFECTIVE ones — `LEAST(admin, client)`,
                # `billing/caps.py` — so the panel reports the ceiling that actually
                # binds. Reporting the admin's while the client's is stricter would show
                # a client headroom the gate will refuse them.
                plan_in_effect_sql(
                    "monthly_fee, included_min, overage_rate, "
                    f"{EFFECTIVE_CAP_MIN_SQL}, {EFFECTIVE_CAP_SPEND_SQL}, overage_rate_value"
                )
            ),
            {"tid": tenant_id, "at": priced_at},
        )
    ).first()
    if plan is None:
        # Distinguishes "this tenant has no plan" (normal — nothing creates one) from
        # "this tenant HAS plans and none covers the month we are pricing", which is an
        # operator error that would otherwise show up only as a mysteriously free month.
        await warn_no_plan_in_effect(session, tenant_id=tenant_id, at=priced_at)
    included = int(plan[1] or 0) if plan else 0
    overage_rate = Decimal(str(plan[2])) if plan and plan[2] is not None else Decimal("0")
    # NULL is not zero: "this plan quotes no separate value rate" (bill everything at
    # `overage_rate`) and "the value rung is free" are different plans.
    value_rate = Decimal(str(plan[5])) if plan and plan[5] is not None else None
    # PRICED THROUGH THE ONE MONTH-PRICING FUNCTION, which `build_invoice` prints the
    # lines of and which the METER now charges each call the difference in
    # (`month_increment`). This panel's total is literally the sum of the lines
    # that will be printed — the identity the invoice promises, held by construction
    # instead of by a reconciliation that bent the last line to fit — and it is now the
    # same identity the live counter holds.
    #
    # The rates go in UNROUNDED because they are the plan terms; `rate_to_display`
    # publishes numbers equal to them (paise when the rate is a whole number of paise,
    # full precision otherwise — never a rounded rate), which is what lets the invoice
    # re-price from the published figures and land on the same paisa.
    priced = priced_overage(
        minutes_by_rung=tier_minutes,
        included_min=Decimal(included),
        rate=overage_rate,
        rate_value=value_rate,
    )
    overage_min = priced.overage_min
    overage_premium = priced.premium_min
    overage_value = priced.value_min
    overage_cost = priced.total_inr

    # THE LIVE COUNTERS, through the one month-aware reader (`billing/caps.py`) that the
    # compliance gate, the admin directory and the health panel already read. The month
    # is part of the answer, for the same reason it is in `compliance.service
    # .spend_capped`: the flag is only written when a call completes, so a capped
    # tenant's row can sit at last month's cap indefinitely. Reporting that as a live cap
    # would show "capped, 0 minutes left" to a client the gate is now letting dial — the
    # panel contradicting the system.
    #
    # This function used to check the month for `capped` and then read `spend_used` out
    # of the same row WITHOUT it — one predicate, applied to one of the two columns it
    # was written for. That is why the shared reader exists rather than a shared
    # `if`: it returns the counters TOGETHER, so a caller cannot take half the check.
    counters = await read_spend_counters(session, tenant_id=tenant_id, month=today)
    # Deliberately the LIVE flag even when an older `?month=` is being viewed: "outgoing
    # calls are paused" is a fact about the account right now, not about the month on
    # screen, and it is what `minutes_left` below has to respect.
    capped = counters.capped

    # Runway framing (teardown adopt #8): "about N minutes left" is what an owner can
    # actually plan around; a rupee balance makes them do the division at the counter.
    # Managed: what remains of the cap. Self-serve: wallet ÷ the list price — priced
    # from the SAME config number the top-up flow uses, so the two can never disagree.
    # `plan_tier_of`, not a fourth hand-rolled `SELECT plan_tier`: `billing/ai_quota.py`
    # already describes that function as "the one reader of `organizations.plan_tier` —
    # the same one `usage_summary` and `charge_for_call` use", which was true of two of
    # the three. It is also the function that supplies the default, so a NULL column
    # cannot read as one tier here and as `managed` everywhere else.
    tier = await plan_tier_of(session, tenant_id)
    minutes_left: int | None = None
    # `PREPAID_TIERS`, never the literal pair. The constant's own docstring names three
    # places that branch on it and warns that "a fourth tier added to one of them and not
    # the others is a wallet that stops draining" — and this function was spelling the
    # set BOTH ways, four lines apart: the literal here and the constant in
    # `spend_used_inr` below.
    if tier in PREPAID_TIERS:
        # Credits gate the self-serve motion ONLY, exactly as the compliance gate does
        # (compliance/service.py §2b): a managed client is invoiced against a retainer,
        # so their wallet must not shorten their runway any more than it blocks a dial.
        balance = await get_balance(session, tenant_id=tenant_id)
        rate = get_settings().self_serve_inr_per_min
        if rate > 0 and balance.amount_inr > 0:
            minutes_left = int(balance.amount_inr / rate)
        elif balance.amount_inr <= 0:
            # `Balance.is_exhausted` is `<= 0`, which is the gate's own condition.
            minutes_left = 0
    elif plan and plan[3] is not None:
        minutes_left = max(0, int(Decimal(str(plan[3])) - minutes))

    if capped:
        # `spend_state.capped` is the ONLY cap the gate enforces, and it refuses every
        # outbound call regardless of tier. Offering runway on top of that is a promise
        # the platform will not keep. (Inbound is unaffected by the cap — the gate is
        # outbound-only — but inbound is not something an owner "has minutes left" to
        # spend, so the outbound answer is the honest one for a planning number.)
        minutes_left = 0

    return {
        "month": period,
        "minutes_used": minutes,
        "calls": calls,
        "included_minutes": included,
        "overage_minutes": overage_min,
        # The two rungs the overage was actually split across. They add to
        # `overage_minutes` exactly, and PUBLISHED AS THEY WERE PRICED — not re-rounded
        # here, which is what used to break the identity this comment claims: the pair
        # summed exactly inside `split_overage` and then `to_paise` on each half turned
        # 5.005 + 4.995 into 5.01 + 5.00 on the way out. Nothing on this path rounds a
        # minute; `_tier_totals` did it once, for all of them, so that they add up.
        "overage_minutes_premium": overage_premium,
        "overage_minutes_value": overage_value,
        "overage_cost_inr": overage_cost,
        # The rate the overage was priced at, published so the invoice does not have to
        # re-read `plans` and risk picking a different row than this computation did.
        "overage_rate_inr": rate_to_display(overage_rate),
        # None when this plan quotes no separate value rate — in which case BOTH rungs
        # above were priced at `overage_rate_inr`, and saying None rather than repeating
        # the premium rate is what tells a reader which of those two worlds they are in.
        "overage_rate_value_inr": (rate_to_display(value_rate) if value_rate is not None else None),
        # Quantized to paise like every other money field: NUMERIC(12,4) is the
        # storage precision, two decimals is what a rupee amount means to a reader.
        "monthly_fee_inr": (
            to_paise(Decimal(str(plan[0]))) if plan and plan[0] is not None else None
        ),
        "cap_minutes": int(plan[3]) if plan and plan[3] is not None else None,
        "minutes_left": minutes_left,
        "capped": capped,
        # THE CLIENT'S OWN SPEND, in the client's own currency (P1.3). See `_spend_used`
        # for what each branch reads and why neither of them is `spend_used` any more.
        "spend_used_inr": to_paise(
            _spend_used(
                period,
                today,
                counters.billed_inr,
                closed_month_billed=calling_revenue_inr(
                    plan_tier=tier, minutes=minutes, overage_cost_inr=overage_cost
                ),
            )
        ),
    }


def calling_revenue_inr(
    *, plan_tier: str | None, minutes: Decimal, overage_cost_inr: Decimal
) -> Decimal:
    """What the CLIENT owes for a whole billing period's CALLING, at their own rate.

    **THE DEFECT THIS EXISTS FOR.** `margin_for_tenant` computed revenue as
    `monthly_fee_inr + overage_cost_inr`, which is the entire bill for a MANAGED tenant
    (a retainer plus overage — literally the invoice's subtotal) and is ZERO for a
    prepaid one. D-34's other motion has no `plans` row at all: no monthly fee, no
    included allowance, no `overage_rate`. So the one screen whose whole purpose is "is
    this client making us money" reported ₹0.00 revenue against a real supplier cost for
    every self-serve client — a negative margin, with `margin_pct` suppressed to `None`
    because that branch reads `revenue > 0`. P1.1's shape, one layer up: the panel was
    still deriving what a client owes from two plan columns a prepaid client does not
    have, four lines away from a branch that already knew better.

    So the two readers of "this period's calling, priced to the client" — the client's
    own `spend_used_inr` on a closed month, and the admin margin panel's revenue — come
    HERE rather than each carrying the rule. `_spend_used`'s prepaid branch was the one
    that was right, and it is what moved into this function unchanged.

    **NOT `prepaid_billed_inr`, and the difference is the quantum.** That function prices
    ONE CALL for a ledger row and quantizes at `MONEY_Q` (the NUMERIC(12,4) storage
    scale). This is a PERIOD total whose reader quantizes it once to paise, so returning
    a pre-rounded figure here would round the same amount twice and could move a paisa.
    Both nevertheless read the list price from the one config value the runway framing and
    the top-up flow read, which is the property that actually has to hold.

    **A MANAGED tenant's answer is the overage the caller already priced**, passed in
    rather than recomputed, because `usage_summary` derived it from `overage_rungs` — the
    same function `build_invoice` prints its lines from. Re-deriving it here would be the
    second computation that lets a panel and a statement disagree.

    The retainer is deliberately NOT included: it is published as its own figure on both
    surfaces, and adding it here would double it wherever both are shown.

    **A MEASURED RESIDUAL ON THE PREPAID BRANCH, recorded here so the next reader
    inherits the evidence rather than re-deriving it (D-254).** This figure and the money
    actually taken off a prepaid wallet are not the same arithmetic and cannot both be:

    * the WALLET is debited per call, `to_paise`-scale-4 of `rate x (this call's seconds
      / 60)` (`rates.prepaid_billed_inr`, through `charge_for_call`). A call is charged
      for its own length, which is the only rule a client can be shown per entry;
    * this is `rate x the month's PUBLISHED minute count`, which is paise-rounded once
      by `_tier_totals`. It multiplies out against the `minutes_used` printed beside it
      — the arithmetic a client actually does on a panel.

    Measured on this tree, ten calls of 7/7/7/13/41/59/101/137/211/307 seconds at ₹6.00:

        wallet debited (sum of `usage` entries)   ₹89.0000
        spend_state.billed_inr                   ₹89.0000   <- equals the wallet, by
                                                                construction (the meter
                                                                hands both the same
                                                                figure from the same
                                                                function)
        this function, on the closed month        ₹88.98    <- 14.83 min x ₹6.00

    The gap is bounded by half a paisa of minutes times the rate — under ₹0.05 at any
    rate this product would quote — and it is systematic rather than random: the panel
    prices the ROUNDED minute count. Feeding it the exact seconds instead would close it
    against the wallet and open it against the panel, because ₹89.00 is not
    `14.83 x ₹6.00` and a figure a client cannot multiply out is the defect
    `billing/invoice.py` spent a whole slice removing.

    **So there is no engineering-only answer, and the one that closes it is already named
    as a founder decision**: `docs/evidence/deepdive-money.md` N-2 — what a prepaid
    statement IS (a receipt for top-ups received, a statement of consumption, or both).
    If the WALLET is the statement, this branch reads the ledger and the question of
    re-derivation disappears; if the panel is, the wallet's per-call rule is what has to
    move. Neither is ours to pick.
    """
    if plan_tier in PREPAID_TIERS:
        return get_settings().self_serve_inr_per_min * minutes
    return overage_cost_inr


def _spend_used(period: str, today: str, live: Decimal, *, closed_month_billed: Decimal) -> Decimal:
    """What this tenant spent in `period` — from the counter while it is live, from the
    ledger once it is not.

    **BOTH BRANCHES ARE THE CLIENT'S PRICE, and neither used to be** (P1.3). The live one
    read `spend_state.spend_used` — the engine's charge to US — and the closed one summed
    `tier_cost`, which is the same supplier cost re-derived from `usage_events
    .unit_cost_paid`. So this panel published our supplier pricing to the client, on a
    screen three functions below the comment stating that it never does. The margin panel
    still reads both sides; nothing was removed, the two just stopped being one number.

    The closed-month figure is computed by the caller because the caller has already done
    the arithmetic: for a PREPAID tier it is the list rate times the month's minutes, and
    for a MANAGED tier it is `overage_cost` — the sum of the very rungs the invoice will
    print, so the statement and the panel cannot disagree by a paisa. The retainer is
    deliberately not in it: `monthly_fee_inr` is published as its own field and adding it
    here would double it on any screen that shows both.

    `spend_state` is ONE row per tenant (PK `tenant_id`), stamped with the month it is
    counting and reset by the meter on rollover. It has no history whatsoever, so it can
    only answer for the current billing month — and `usage_summary` is reachable with
    `?month=2026-07`, where it was reporting the live row's rupees on a closed month's
    statement, beside a `minutes` figure correctly read from `usage_events` for the month
    actually asked about. Two numbers, two months, one panel.

    OPEN month → the live counter, because that is the exact column the cap is enforced
    against (`caps.over_cap_sql` compares `billed_inr`), so the panel and the gate can
    never tell a client two different stories about the same rupees.

    CLOSED month → the caller's figure, priced from the ledger's minutes at the client's
    own rate. `spend_state` keeps no history whatsoever — it is ONE row per tenant, reset
    by the meter on rollover — so it can only answer for the current billing month, and
    `usage_summary` is reachable with `?month=2026-07`, where the live row's rupees were
    being reported on a closed month's statement beside minutes correctly read from
    `usage_events`. Two numbers, two months, one panel.

    `today` is passed in rather than read from the clock here, and it is the SAME
    reading `read_spend_counters` was given. Taking a second reading is what makes the
    IST month roll a data bug rather than a scheduling curiosity: the counter is judged
    stale against the new month (so `live` is zero) while this test still believes the
    old month is open (so it returns `live`), and the closed month's statement prints
    ₹0.00 spent. Both halves must be asked at one instant or neither answer is about the
    same month.
    """
    if period == today:
        return live
    return closed_month_billed


# --- the TTS tier ladder (SURFACES §2b, D-36) ----------------------------------
#
# `usage_events.meta.tts_tier` is written by the post-call pipeline from the voice the
# agent was CONFIGURED with — the engine reports no synthesizer model, so it is an
# assumption carrying its own provenance (`billing/rates.py` has the vendor question in
# full). Everything below reads that one field, so the client panel and the margin panel
# cannot end up telling two different stories about the same call.


async def tier_usage(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Minutes and OUR cost, split by the TTS rung each call was metered on.

    Three buckets, not two, and the third is the honest one: rows written before tier
    attribution existed — or by a path that could not attribute one — carry no tier at
    all. They are reported as `unattributed` rather than folded silently into a rung,
    because "we know this ran on v2" and "we never knew" are different facts.

    For BILLING they are not different: `minutes_billable_value` folds unattributed in
    with value, because SURFACES §2b's rule is that a call we cannot prove got the
    premium voice is never charged the premium rate. Reporting keeps the distinction;
    pricing resolves it in the client's favour.

    Minutes come from `telephony_s` — the same unit `usage_summary` bills on — and they
    are the SAME allocated figures that panel publishes, so the three buckets add up to
    its `minutes_used` for the same month exactly. That sentence was here before
    `_tier_totals` allocated them and it was false: each bucket was rounded on its own,
    so two buckets of 5.005 and 4.995 minutes reported 10.01 against a usage panel
    reading 10.00. Nothing is rounded here now — `to_paise` on these would be a no-op
    and its absence is the point.

    Read by ONE caller: `GET /v1/admin/tenants/{id}/margin`, which nests it under
    `tiers` so the rungs sit beside the `cost_inr` they partition. Admin realm only, for
    the same reason the margin card is — these are OUR supplier costs. It had no caller
    at all for two waves, which is what the note here used to record; a reporting surface
    nobody mounts is a defect that looks like progress, so it was mounted rather than
    re-noted. `usage_summary` and `margin_for_tenant` consume `_tier_totals` directly,
    so the arithmetic below is also exercised through them.
    """
    period = month or current_billing_month()
    # Validated for the same reason `usage_summary` validates it, and by the same
    # function: two panels reading one ledger must not disagree about what a month is.
    parse_billing_month(period)
    minutes, cost = await _tier_totals(session, tenant_id=tenant_id, month=period)

    return {
        "month": period,
        "minutes_premium": minutes["premium"],
        "minutes_value": minutes["value"],
        "minutes_unattributed": minutes[""],
        # What a bill may charge at each rung: unproven never reaches the premium side.
        "minutes_billable_premium": minutes["premium"],
        "minutes_billable_value": minutes["value"] + minutes[""],
        "cost_premium_inr": to_paise(cost["premium"]),
        "cost_value_inr": to_paise(cost["value"]),
        "cost_unattributed_inr": to_paise(cost[""]),
    }


async def record_tier_correction(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    chars: int,
    billed_tier: TtsTier,
    actual_tier: TtsTier,
    ref: str,
    note: str | None = None,
) -> Decimal | None:
    """Correct a call metered on the wrong TTS rung — by APPENDING, never by editing.

    `usage_events` is INSERT-only (hard rule 4), so the wrong row stays exactly where it
    is and a new row carries the difference. `margin_for_tenant` sums
    `qty * unit_cost_paid`, so a `qty` of 1 priced at the delta corrects the month by
    construction, with no reader needing to know a correction happened.

    It is stamped at the ORIGINAL call's `occurred_at`, not at now(): a July call that
    was billed at the wrong rate was wrong in July, and dropping the fix into August
    would leave both months lying. The moment the correction was issued is recorded in
    `meta.issued_at` instead, which is the audit question a date on the row cannot
    answer anyway.

    A CHARACTER COUNT IS REQUIRED — `rates.tts_cost_inr` refuses to invent one, so a
    correction can only be made by someone who actually knows how much speech was
    synthesized (today: from the model vendor's own usage export).

    Returns the delta written, or None when there was nothing to correct — the tiers
    agreed, or this `ref` has already been applied to THIS call. Idempotent under a
    per-tenant advisory lock, because a replayed ops script must not credit twice.

    BOTH LEDGERS ARE KEYED ON (tenant, call, ref). One ops reference may legitimately
    cover a batch of calls, so keying the wallet entry on the reference alone made the
    second and every later call in a batch a correction that was recorded and never
    refunded — the client's cost ledger said "put right" while their balance did not
    move. A correction that only half-happens is worse than one that fails, because
    nothing reads as wrong afterwards.
    """
    delta = tier_correction_inr(chars=chars, billed_tier=billed_tier, actual_tier=actual_tier)
    if delta == 0:
        return None

    # Same lock the credit ledger uses, so the usage correction and the wallet
    # adjustment below are decided inside ONE critical section per tenant.
    await lock_tenant_credits(session, tenant_id)
    already = (
        await session.execute(
            text(
                "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                "AND meta->>'correction_ref' = :ref LIMIT 1"
            ),
            {"tid": tenant_id, "cid": call_id, "ref": ref},
        )
    ).first()
    if already:
        return None

    occurred_at = (
        await session.execute(
            text(
                "SELECT MIN(occurred_at) FROM usage_events "
                "WHERE tenant_id = :tid AND call_id = :cid"
            ),
            {"tid": tenant_id, "cid": call_id},
        )
    ).scalar()

    meta = {
        "kind": "tts_tier_correction",
        "correction_ref": ref,
        "billed_tier": billed_tier,
        "actual_tier": actual_tier,
        # The row asserts the tier that RAN, so `tier_usage` counts its money on the
        # rung the call actually used rather than the one it was mis-billed on.
        "tts_tier": actual_tier,
        "tts_tier_source": "correction",
        "chars": chars,
        "issued_at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :cid, 'other', 1, :cost, "
            "COALESCE(:at, now()), CAST(:meta AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call_id,
            "cost": delta,
            "at": occurred_at,
            "meta": json.dumps(meta),
        },
    )

    # For a self-serve client the wallet IS the bill (D-39): the call was debited at
    # metered cost, so a corrected cost has to move the balance too — as a new entry.
    # Managed clients are invoiced against a retainer and their wallet is not part of
    # the charge, so nothing is written for them.
    if await plan_tier_of(session, tenant_id) in PREPAID_TIERS:
        # KEYED ON THE CALL AS WELL AS THE REF, and this is a fix rather than a detail.
        # The cost-ledger dedupe above is `(tenant, call_id, correction_ref)` while this
        # one used the ref alone, so a single ops reference covering a BATCH of calls
        # produced one cost correction per call and exactly ONE wallet refund — every
        # call after the first was corrected on paper and never refunded. The two keys
        # now agree, which is the property that makes "corrected" and "refunded" the
        # same set. (`ux_credit_ledger_tenant_reason_ref` is the second line of defence:
        # a duplicate is a UniqueViolation rather than a double credit — a 500 instead
        # of a wrong balance, which is the safe direction but not an answer.)
        wallet_ref = f"tier-correction:{call_id}:{ref}"
        # NO SECOND REPLAY CHECK HERE, and its removal is part of the same fix. This
        # block used to re-ask "has this wallet ref been used?" because its key differed
        # from the cost ledger's; now that both are (tenant, call, ref), the `already`
        # guard at the top of this function returns before control can reach here on a
        # replay, so the check could never fire. A reader's `if` that cannot fire is not
        # defence in depth, it is a second way to answer one question — and the real
        # enforcement was never the SELECT anyway: `ux_credit_ledger_tenant_reason_ref`
        # makes a duplicate a UniqueViolation rather than a double credit (D-63: the
        # index is the guarantee, not the reader).
        await record_entry(
            session,
            tenant_id=tenant_id,
            # The ledger's sign convention is the wallet's, not the cost ledger's:
            # a NEGATIVE cost correction (we overbilled) is a POSITIVE credit back.
            delta=-delta,
            reason="adjustment",
            ref=wallet_ref,
            meta={"call_id": str(call_id), "billed_tier": billed_tier, "actual": actual_tier},
            # The call already happened; a correction that refuses to record is a
            # correction that leaves the client overcharged.
            allow_negative=True,
        )

    log.info(
        "tts_tier_correction",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "billed_tier": billed_tier,
            "actual_tier": actual_tier,
        },
    )
    return delta


async def margin_for_tenant(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Admin-only: revenue vs OUR cost for one client (D-12).

    Revenue is the plan's monthly fee plus overage — the invoice, not an estimate. Cost
    is the sum of `unit_cost_paid`, which the pipeline stamps per usage row at capture
    time with the fx rate it used, so a later rate move cannot rewrite history.
    """
    usage = await usage_summary(session, tenant_id=tenant_id, month=month)
    # OUR COST HAS ONE DEFINITION AND THIS IS IT. This function used to carry its own
    # `SUM(qty * COALESCE(unit_cost_paid, 0))` — the same expression `_tier_totals`
    # already spells, in a second SQL string with a second predicate, for a number that
    # must agree with `_spend_used`'s closed-month figure to a paisa or the margin panel
    # and the usage panel contradict each other about one month. Summing the rungs is
    # exactly the ungrouped total (a GROUP BY partitions the rows), so this is the same
    # arithmetic with one fewer place for a filter to be added to only one of them.
    # NUMERIC throughout — no float anywhere on the path from `unit_cost_paid` to the
    # rupee an operator reads (hard rule 7).
    _, tier_cost = await _tier_totals(session, tenant_id=tenant_id, month=str(usage["month"]))
    cost_inr = to_paise(sum(tier_cost.values(), Decimal("0")))
    # REVENUE IS THE CLIENT'S PRICE FOR THIS PERIOD, AND WHICH PRICE THAT IS DEPENDS ON
    # THE MOTION. `monthly_fee + overage_cost` is the managed tenant's bill (it is the
    # invoice's subtotal) and it is ₹0.00 for a prepaid one, whose minutes are charged at
    # the list price and taken out of the wallet — so this panel reported the whole
    # self-serve motion as a pure loss until `calling_revenue_inr` existed. The retainer
    # stays here because a prepaid tenant has none; the CALLING half is the part that
    # differs, and it has one home now.
    tier = await plan_tier_of(session, tenant_id)
    revenue = (usage["monthly_fee_inr"] or Decimal("0")) + calling_revenue_inr(
        plan_tier=tier,
        minutes=usage["minutes_used"],
        overage_cost_inr=usage["overage_cost_inr"],
    )
    margin = to_paise(revenue - cost_inr)
    # Percent is reported as None rather than 0 when there is no revenue: "0% margin"
    # and "nothing billed yet" are different facts and an operator acts differently.
    pct = (
        (margin / revenue * 100).quantize(Decimal("0.1"), rounding=ROUNDING)
        if revenue > 0
        else None
    )
    return {
        "month": usage["month"],
        "minutes_used": usage["minutes_used"],
        "calls": usage["calls"],
        "revenue_inr": to_paise(revenue),
        "cost_inr": cost_inr,
        "margin_inr": margin,
        "margin_pct": pct,
    }


__all__ = [
    "ADJUSTMENT_META_KIND",
    "ADJUSTMENT_REF_PREFIX",
    "LOW_BALANCE_INR",
    "PAISE",
    "PAYMENT_REF_SQL",
    "RESTATEMENT_META_KIND",
    "RESTATEMENT_REF_PREFIX",
    "ROUNDING",
    "Balance",
    "CorrectableEntry",
    "CreditReason",
    "LedgerEntryRef",
    "OverageRung",
    "RecordedPayment",
    "adjustment_ref",
    "allocate_paise",
    "calling_revenue_inr",
    "charge_for_call",
    "current_billing_month",
    "find_entry_by_ref",
    "find_topup",
    "get_balance",
    "lock_tenant_credits",
    "margin_for_tenant",
    "overage_rungs",
    "plan_tier_of",
    "rate_to_display",
    "read_correctable_entry",
    "read_recorded_payment",
    "record_entry",
    "record_tier_correction",
    "recorded_payments",
    "restatement_ref",
    "reversed_amounts",
    "split_overage",
    "tier_usage",
    "to_paise",
    "usage_summary",
]
