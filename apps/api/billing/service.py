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

from calevate_shared.engine import LLM_MODELS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# THE MODULE, not its symbols — the same import `billing/lots.py` makes of this file
# and for the same reason: the two are mutually dependent by design (a lot is opened in
# the transaction of the ledger row that bought it), and a `from ... import name` on
# either side resolves at import time against a half-initialised module. Attribute
# access on the module object does not.
from apps.api.billing import lots as credit_lots
from apps.api.billing.caps import (
    EFFECTIVE_CAP_MIN_SQL,
    EFFECTIVE_CAP_SPEND_SQL,
    read_spend_counters,
)
from apps.api.billing.credit_packs import PACK_CATALOGUE, CreditPack, pack_by_id
from apps.api.billing.list_rates import card_at, self_serve_rate_at
from apps.api.billing.models import (
    AI_ASSIST_UNIT_TYPES,
    GRANTED_CREDIT_REASONS,
    PAID_CREDIT_REASONS,
)
from apps.api.billing.plans import (
    OVERAGE_RATE_SECOND_SQL,
    ist_billing_month,
    ist_month_window,
    month_pricing_instant,
    parse_billing_month,
    plan_in_effect_sql,
    warn_no_plan_in_effect,
)
from apps.api.billing.rates import (
    CLIENT_CHOSEN_LLM_SOURCES,
    MONEY_Q,
    PREPAID_TIERS,
    ROUNDING,
    VOICE_TIER_LABELS,
    VoiceTier,
    is_surchargeable_llm_model,
)
from apps.api.billing.trials import counter_epoch, read_trial
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.models import DEFAULT_PLAN_TIER

log = get_logger(__name__)

# Spelled as a Literal rather than derived from `models.CREDIT_REASONS`, because a
# `Literal[*tuple]` is not a static type mypy can check and the point of this alias is that
# `record_entry("granted")` is a TYPE ERROR rather than a CHECK violation at 2am.
# `tests/credits_test.py` holds the two in step.
CreditReason = Literal["topup", "usage", "adjustment", "refund", "bonus", "grant"]

# Below this the wallet is "low" — surfaced in the UI, not enforced. Enforcement is
# `balance > 0`; a warning band exists so a client is told before calls start failing.
LOW_BALANCE_INR = Decimal("200.00")

#: The job the ledger publishes when a debit takes a wallet ACROSS a warning line
#: (`apps/workers/wallet_alerts.py`). Registered in `apps/workers/settings.FUNCTIONS`;
#: `scripts/check_job_wiring.py` is the gate that the name here, the function there and
#: the registration agree.
LOW_BALANCE_JOB = "notify_low_balance"

#: The job the ledger publishes when a movement takes a wallet across ZERO, in EITHER
#: direction (`apps/workers/inbound_cutover.py`). Down, it is what stops a client's agents
#: answering calls they have no credit to pay for; up, it is the ONLY thing that brings
#: them back — a client who tops up at 9pm must not find their phone still dead in the
#: morning, and there is no cron sweeping for them.
#:
#: THE NAME LIVES HERE, BESIDE `LOW_BALANCE_JOB`, for that constant's reason: the publisher
#: owns the name so every enqueue site and the registration in `apps/workers/settings
#: .FUNCTIONS` resolve to ONE string, which is what `scripts/check_job_wiring.py` checks.
#: `apps/api` must not import `apps/workers` (the dependency runs the other way), so the
#: worker module and `workers/pipeline.py`'s backstop both import it from here.
INBOUND_CUTOVER_JOB = "apply_inbound_credit_state"

#: The two lines a falling balance can cross, most severe first. `empty` is the one the
#: dial gate acts on (`compliance.service.credits_exhausted` — `balance <= 0`); `low` is
#: the warning band above it, which enforces nothing.
WALLET_LEVEL_EMPTY = "empty"
WALLET_LEVEL_LOW = "low"


def crossed_zero(before: Decimal, after: Decimal) -> str | None:
    """`"empty"`, `"funded"`, or None: which way this movement took the wallet across ZERO.

    THE SYMMETRIC HALF OF `crossed_downwards`, and it is a separate function rather than a
    third return value of that one because the two answer different questions and only one
    of them is a warning: `crossed_downwards` decides what to TELL a client (it has a `low`
    band above zero that enforces nothing), and this decides what to DO to their phone.

    A CROSSING AND NOT A STATE, for `crossed_downwards`' reason and with the same payoff:
    the entry that takes a wallet from +10 to -2 is the only entry that will ever report
    `empty` for that episode and the top-up is the only one that will ever report `funded`,
    so "act once per episode" needs no stored flag, no cron sweep and no clock.

    `> 0 >=` and `<= 0 <` are the same boundary read from the two sides, and the boundary is
    `Balance.is_exhausted` — `balance <= 0`, the dial gate's own condition. A wallet sitting
    at exactly zero is EXHAUSTED, so a movement that leaves it there is not a recovery.
    """
    if before > 0 >= after:
        return WALLET_LEVEL_EMPTY
    if before <= 0 < after:
        return "funded"
    return None


def crossed_downwards(before: Decimal, after: Decimal) -> str | None:
    """Which warning line, if any, this movement took the wallet ACROSS, going down.

    A CROSSING and not a state, and that is the whole design of the low-balance alert:
    the entry that takes a wallet from ₹250 to ₹150 is the only entry that will ever
    report `low` for that episode, so "warn once per episode" needs no stored flag, no
    cron sweep and no clock. Top up and fall again and it is a new crossing, which is
    also a new thing to be told about.

    `>` on the way in and `<=` on the way out for `empty`, because `<= 0` is the dial
    gate's own condition (`Balance.is_exhausted`) and the sentence this sends is "your
    outgoing calls have stopped". Reporting `empty` for a wallet that was already at
    zero would mail a client every time a call metered them further into the red.
    """
    if before > 0 >= after:
        return WALLET_LEVEL_EMPTY
    if before >= LOW_BALANCE_INR > after >= 0:
        return WALLET_LEVEL_LOW
    return None


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
    allow_zero: bool = False,
) -> Balance:
    """Append one entry and return the new balance.

    `allow_negative=False` refuses a charge that would overdraw. The exception is
    deliberate: usage recorded AFTER a call completes must always land, because the
    call already happened and refusing to record it would hide a real cost. Prevention
    belongs at the pre-dispatch gate, not at the accounting layer.

    The read-decide-write runs under a per-tenant advisory lock (see the module
    docstring for why a row lock on the newest entry is not enough), so two concurrent
    charges cannot both compute from the same starting balance.

    `allow_zero` writes a MARKER: a real ledger row that moves no money. The default
    refuses one, and that default is right for every money writer — a zero delta reaching
    this function from an amount that was computed is arithmetic that went wrong, and a
    row recording it would be noise on the one artefact a client's bill is re-derived
    from. It is opened for the one case that has a marker to write and nowhere else to
    write it: `credit_lots.ledger_entry_id` is NOT NULL and UNIQUE, so a lot that opens
    without money arriving — the replacement a re-price mints (`reprice_lot`) — still
    needs an entry to name. Migration `c9f3a71e58d2` set that precedent for exactly this
    reason and by exactly this device: a zero-delta `adjustment` row carrying a
    `meta.kind`, with `balance_after` unchanged, so the ledger records where a lot came
    from and no wallet moves in either direction.
    """
    if delta == 0 and not allow_zero:
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
    # THE WARNING, PUBLISHED IN THE SAME TRANSACTION AS THE ENTRY THAT EARNED IT.
    #
    # It sits here rather than in `charge_for_call` because a call is not the only thing
    # that empties a wallet: a compensating adjustment and a refund both take credit off
    # through this function, and a client whose calling stops because an operator
    # corrected an over-credit has exactly as much right to be told. One writer, one
    # place — the alternative is three callers each remembering.
    #
    # Through the OUTBOX and not a direct enqueue, so the promise to warn cannot outlive
    # a rolled-back ledger row (BACKEND-PATTERNS §4). Whether this tenant HAS a wallet
    # worth warning about, and whether anyone has agreed to be emailed, is the worker's
    # question — deciding it here would put a tier read on the hottest money write in the
    # product to answer a question that is still true a minute later.
    # THE PHONE, ON THE SAME TERMS AS THE WARNING ABOVE AND FOR A STRONGER REASON.
    # Crossing zero going DOWN is what stops this client's agents answering calls they
    # cannot pay for (8 Sep 2026); crossing it going UP is the ONLY automatic path back,
    # so the two are published by the one writer that sees both. Through the OUTBOX, in
    # this transaction, because a promise to bring a phone line back must not be able to
    # outlive a rolled-back top-up — nor, more to the point, be lost by one that committed.
    #
    # The payload carries the tenant and nothing else: the job RE-READS `credits_exhausted`
    # rather than trusting a verdict that was true when it was queued (see the job).
    if crossed_zero(current, new_balance) is not None:
        await enqueue_outbox(
            session,
            job=INBOUND_CUTOVER_JOB,
            payload={"tenant_id": str(tenant_id)},
        )
    level = crossed_downwards(current, new_balance)
    if level is not None:
        await enqueue_outbox(
            session,
            job=LOW_BALANCE_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "level": level,
                # DIGITS, never a float (hard rule 7): this crosses JSONB and comes back
                # through `json.loads`, where a JSON number would be a binary double by
                # the time the email renders it.
                "balance_inr": str(new_balance),
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


# --- credit GRANTED out of nothing (D-535) -------------------------------------
#
# The founder: *"the admin should be able to add any no.of credits without any payments
# record to any client but it is audited"*. The adjustment above cannot do it — it must
# name a wrong entry and is bounded by that entry's magnitude, which is what makes it a
# CORRECTION — and the top-up cannot do it without the ledger claiming a bank moved money
# nobody moved. So `grant` is a sixth reason (`billing/models.CREDIT_REASONS` argues which
# of the five it is not, and why), and this is what carries it.

GRANT_REF_PREFIX: Final = "grant"

#: The `meta.kind` every operator grant carries, the shape `ADJUSTMENT_META_KIND` and
#: `RESTATEMENT_META_KIND` established: `reason` is the coarse enum, `meta.kind` says which
#: writer wrote the row.
GRANT_META_KIND: Final = "operator_grant"

#: THE CEILING ON ONE GRANT, and it is the founder's own guardrail: *"a ceiling per grant,
#: so a fat-finger (₹5,00,000 instead of ₹5,000) is refused rather than posted"*.
#:
#: ₹50,000 is an order of magnitude above the goodwill grant the founder described and an
#: order of magnitude below the slip it has to catch, which is the property that makes a
#: ceiling worth having at all — one set at the top of the plausible range refuses honest
#: work, and one set above the typo stops nobody. It is deliberately NOT `MAX_TOPUP_INR`
#: (₹1,00,000): that number bounds what a client may PAY US in one transfer, which is a
#: fact about a payment rail, and reusing it here would tie the size of a gift to the size
#: of a card transaction. A genuinely larger gift is two grants under two references, each
#: separately confirmed and separately audited — which is the trail we want for one anyway.
MAX_GRANT_INR: Final = Decimal("50000.00")

#: The floor. A grant below one rupee is a typo or a test, and the ledger is not the place
#: to find out which.
MIN_GRANT_INR: Final = Decimal("1.00")


def grant_ref(*, reference: str) -> str:
    """A grant's own ledger reference — its idempotency key, enforced by
    `ux_credit_ledger_grant_ref` rather than by a reader's `if` (D-63's argument).

    **THE REFERENCE IS THE OPERATOR'S, NOT DERIVED**, and that is the one place this
    departs from `adjustment_ref`. An adjustment is content-addressed over (entry, amount)
    because it HAS a natural key — the row it corrects — and because two genuinely distinct
    corrections of one entry for one amount are a coincidence worth collapsing. A grant has
    neither property: nothing outside this act identifies it, and two goodwill grants of
    ₹5,000 to one client two months apart are ORDINARY, not a double click. Content-
    addressing over (amount, reason) would silently refuse the second of them and report it
    as a replay of the first — a gift the client never received, reported as delivered.

    So the caller supplies the key, which is exactly what `TopUpIn.payment_ref` does with a
    UTR, and the console mints one per opened form so that a second CLICK converges while a
    second DECISION does not. The prefix keeps the string out of the namespaces `ref` shares
    (a call id on `usage`, whatever the bank printed on `topup`), so a grant can never be
    mistaken for either by a reader that forgets to scope by reason.
    """
    return f"{GRANT_REF_PREFIX}:{reference}"


@dataclass(frozen=True, slots=True)
class CreditTotals:
    """What a wallet has been given, split by WHERE IT CAME FROM (D-535).

    The founder's first guardrail: *"shown separately from paid credit — a client's
    statement must distinguish credit they BOUGHT from credit we GAVE"*. It is not only a
    presentation rule. Granted credit that reads as paid inflates the revenue side of our
    own margin figures, which is the same defect D-39 refused when it declined to seed
    opening balances — every `reason` would have been a lie about money nobody paid.

    LIFETIME totals, not a window: "how much of this wallet did we fund" is a fact about the
    relationship, and a client comparing a statement against their own books is adding up
    every payment they ever made, not the last thirty days of them.
    """

    paid_inr: Decimal
    granted_inr: Decimal


async def credit_totals(session: AsyncSession, *, tenant_id: UUID) -> CreditTotals:
    """Bought versus given, over the whole wallet. Summed in SQL over NUMERIC.

    ONE query and ONE definition of each side, read by the operator's wallet panel and by
    the client's own statement — two screens showing one wallet must not be able to
    disagree about how much of it we funded. The reason sets come from
    `billing/models.PAID_CREDIT_REASONS` / `GRANTED_CREDIT_REASONS` rather than from
    literals here, so a seventh reason has to be argued onto one side or the other instead
    of quietly landing on neither.

    `delta > 0` on both sides: a `grant` is only ever positive (the route refuses anything
    else) and a `topup` likewise, but the filter says so rather than assuming it — the row
    that takes a wrong grant back is an `adjustment`, which belongs to NEITHER total and
    must not be able to subtract from what a client was given. What a wallet HOLDS is
    `get_balance`; this answers where it came from.
    """
    row = (
        await session.execute(
            # `tenant_id` in the predicate as well as in RLS: it is what makes this an index
            # scan on `ix_credit_ledger_tenant_recent`, the argument `read_credits` records.
            text(
                "SELECT "
                "COALESCE(SUM(delta) FILTER ("
                "  WHERE delta > 0 AND reason = ANY(CAST(:paid AS text[]))), 0), "
                "COALESCE(SUM(delta) FILTER ("
                "  WHERE delta > 0 AND reason = ANY(CAST(:granted AS text[]))), 0) "
                "FROM credit_ledger WHERE tenant_id = :tid"
            ),
            {
                "tid": tenant_id,
                "paid": list(PAID_CREDIT_REASONS),
                "granted": list(GRANTED_CREDIT_REASONS),
            },
        )
    ).one()
    # `.one()`, not `.first()` plus a `row is None` guard, for `ops/secret_service.py`'s
    # reason: a SUM over no rows is one row of zeroes (the `COALESCE` above is what makes
    # them zeroes rather than NULLs), so a wallet with no ledger at all still returns a
    # row and the guard was unreachable. An unreachable branch on a money path is one
    # nobody will ever see fail; if the impossible ever happens, SQLAlchemy raises
    # `NoResultFound` here and the traceback points at this line rather than at a pair of
    # zeroes we invented for a query that answered nothing.
    # `Decimal(str(...))` on every NUMERIC read — `_newest_balance` argues the one character.
    return CreditTotals(paid_inr=Decimal(str(row[0])), granted_inr=Decimal(str(row[1])))


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
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    demand: credit_lots.CallDemand,
    extra_inr: Decimal = Decimal("0"),
) -> Decimal:
    """Debit a completed call from the wallet's LOTS, and return what it came to.

    Idempotent by `ref` — the post-call pipeline is re-runnable, and a ledger that
    double-charges on a replay is worse than no ledger. A replay returns ₹0.00 and
    consumes nothing: `record_usage_from_lots` finds the row before it walks a lot.

    **IT TAKES MINUTES, NOT RUPEES, AND THAT IS THE WHOLE OF D-547 AT THIS SEAM.** The
    price of a call is no longer knowable at the call site: it is a property of the LOTS
    the wallet still holds, each frozen at the two rates it was sold at, spent oldest
    first. `CallDemand` carries the minutes, the voice tier that decides which of a lot's
    two rates applies, and the fallback rate for a wallet with no lots left at all
    (`billing/lots.py::consume`).

    `extra_inr` is money owed for this call that is NOT minutes — today only the D-455
    language-model surcharge. It is consumed at face value and lands on the row as an
    `ai_assist` split rather than a `call` one, because its minutes are already counted by
    the call splits and a reader totalling `kind == "call"` minutes would otherwise count
    them twice (plan ADDENDUM 2 §2.1 is the rule; this is the case it was written for).

    `allow_negative=True` throughout: the call already happened. A cost we refuse to
    record is a cost we later cannot explain, and the overdraft it leaves is priced at the
    rate of the lot that ran out (plan §0 Q5) and repaid by the next top-up.
    """
    if demand.minutes <= 0 and extra_inr <= 0:
        return Decimal("0")
    debit = await record_usage_from_lots(
        session, tenant_id=tenant_id, ref=str(call_id), demand=demand, extra_inr=extra_inr
    )
    return debit.credits_inr


# --- credit lots: the seam between the FIFO engine and the ledger (D-547) --------
#
# `billing/lots.py` owns the walk, the CAS and the split vocabulary. THIS section owns
# the pairing: a lot is opened in the same transaction as the `credit_ledger` row that
# paid for it, and a debit's splits are written onto the `usage` row that records it. The
# two live apart because `record_entry` is the only writer of that row and it is here.


@dataclass(frozen=True, slots=True)
class LotRates:
    """The two per-minute rates a lot freezes at the moment it opens.

    A pair rather than two loose arguments so a caller cannot hand the Cartesia rate to
    the Sarvam column: they are ordered the same way in every constructor in this file,
    and `lots.open_lot` refuses the inversion a layer down (plan §2.3 invariant 6).
    """

    sarvam_inr_per_min: Decimal
    cartesia_inr_per_min: Decimal

    def rate_for(self, voice_tier: VoiceTier) -> Decimal:
        """What a minute of `voice_tier` costs at these rates.

        `lots.OpenLot.rate_for`'s twin, deliberately spelled the same way and existing for
        the same reason: the pair and the voice must be resolved TOGETHER or they can
        disagree. They did — `workers/pipeline` handed `lots.CallDemand` a single figure
        (the Sarvam list rate) as the fallback for BOTH voices, so a Studio call on a
        wallet with no open lot was debited at ₹5.00 against a card that sells that minute
        at ₹8.00 and a cost floor of ₹4.36. A pair plus this accessor is what makes the
        two unable to come apart.
        """
        if voice_tier == "sarvam":
            return self.sarvam_inr_per_min
        return self.cartesia_inr_per_min


def _smallest_pack() -> CreditPack:
    """The cheapest rung of the card — the LIST rates, and the floor of every rule below."""
    return min(PACK_CATALOGUE, key=lambda pack: pack.amount_inr)


@dataclass(frozen=True, slots=True)
class RateCard:
    """THE PACK CARD IN FORCE AT ONE INSTANT — the one door every lot opener asks.

    **THIS REPLACES FOUR MODULE FUNCTIONS THAT READ THE STATIC CATALOGUE**
    (`lot_rates_of_pack`, `lot_rates_for_amount`, `lot_rates_for_purchase`,
    `granted_lot_rates`), and the replacement is the whole point rather than a tidy-up.
    `list_rates.record_card` writes a dated card on every ops-console price change and
    `card_at` resolves it, but NOTHING READ IT: every lot took its rates from the
    `PACK_CATALOGUE` constant, so a card recorded in the console was inert and "raise
    prices later by recording a new card" was false. One reader, and the promise holds.

    **THE PACK LADDER IS STILL THE CATALOGUE, AND ONLY THE RATES ARE DATED.** Which pack a
    free amount reaches is decided by `amount_inr` — what a pack COSTS — and that figure is
    not in `platform_list_rates`, which dates ₹/min cells and nothing else. So the ladder
    is picked from the catalogue and then priced from the card, which is also the only
    reading under which `card_at`'s per-cell catalogue fallback means what it says.

    Held as a resolved mapping rather than a session, so the four questions below are
    answered from ONE read: they are asked inside a per-tenant advisory lock on the path
    that opens a lot, and four round trips there would be four times the lock hold for one
    answer (`card_at`'s own argument, one layer up).
    """

    #: `{pack_id: {voice: ₹/min}}` exactly as `list_rates.card_at` resolved it — every
    #: pack this build sells is present, with the catalogue's own figure for any cell the
    #: card never recorded.
    cells: Mapping[str, Mapping[VoiceTier, Decimal]]

    def of_pack(self, pack: CreditPack) -> LotRates:
        """One pack's rates as published at this card's instant."""
        cell = self.cells[pack.pack_id]
        return LotRates(sarvam_inr_per_min=cell["sarvam"], cartesia_inr_per_min=cell["cartesia"])

    def list_rates(self) -> LotRates:
        """THE LIST RATES: the smallest pack's, which is what the card's own floor is.

        What a GIFT is spent at (plan §0 Q4) — a grant, a trial credit, a compensating
        credit-back — because a gift is spent at the standard price, or a ₹50,000 grant
        would buy a cheaper minute than a ₹50,000 purchase. It is also what prices a
        minute for a wallet holding no lot at all (`lots.CallDemand.fallback_rates`): the
        rates a lot opened at this instant would freeze.
        """
        return self.of_pack(_smallest_pack())

    def for_amount(self, amount_inr: Decimal) -> LotRates:
        """The rates a FREE-AMOUNT top-up freezes (plan §0 Q3).

        The largest pack whose price is at or below the amount paid, and the smallest
        pack's rates for anything under the first rung. Monotone by construction: topping
        up ₹4,999 can never be dearer per minute than topping up ₹4,000, and it can never
        be cheaper than the pack the client did not quite buy. Removing free amounts was
        the alternative and it breaks a documented flow (`MIN_TOPUP_INR` is ₹100), so the
        rule has to exist either way; this is the one that punishes nobody.
        """
        afforded = [pack for pack in PACK_CATALOGUE if pack.amount_inr <= amount_inr]
        if not afforded:
            return self.list_rates()
        return self.of_pack(max(afforded, key=lambda pack: pack.amount_inr))

    def for_purchase(self, *, pack_id: str | None, amount_inr: Decimal) -> LotRates:
        """The rates one PURCHASE freezes: its pack's, or the free-amount rule's.

        A pack id this build no longer offers falls to the amount rule rather than failing
        — the same reading `credit_captured_payment` already takes of an unknown pack, and
        the money has arrived either way.
        """
        pack = pack_by_id(pack_id) if pack_id is not None else None
        if pack is None:
            return self.for_amount(amount_inr)
        return self.of_pack(pack)


async def rate_card_at(session: AsyncSession, *, at: datetime) -> RateCard:
    """The card in force at `at`. ONE query; see `RateCard`.

    `at` is the CALLER's fact and has no default, for `list_rates.self_serve_rate_at`'s
    reason: money arriving now freezes the card in force now, and a figure being re-derived
    for a closed month asks at that month's own pricing instant. A default of `now()` is
    how a closed month silently acquires today's terms, which is the whole defect D-492
    exists for.
    """
    return RateCard(cells=await card_at(session, at=at))


@dataclass(frozen=True, slots=True)
class CreditedLot:
    """What a credit-adding entry did once the overdraft was settled (plan §0 Q5)."""

    #: The lot that opened, or `None` when the whole credit went to repaying an overdraft.
    lot_id: UUID | None
    #: What actually went ONTO the lot.
    credits_inr: Decimal
    #: What went to clearing a negative balance instead, and bought no minutes.
    repaid_overdraft_inr: Decimal


async def apply_credit_to_lots(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    credits_inr: Decimal,
    balance_after: Decimal,
    rates: LotRates,
    source: credit_lots.LotSource,
    pack_id: str | None,
    ledger_entry_id: UUID,
    restate_lot_id: UUID | None = None,
    override_of_pack_id: str | None = None,
) -> CreditedLot:
    """Put a credit-adding ledger row onto the lots — AFTER it has repaid any overdraft.

    THE ONE DOOR every credit writer uses, so the overdraft rule below is written once.
    `restate_lot_id` is the correction case: money that arrived against a payment already
    on the wallet belongs on THAT purchase's lot at THAT purchase's rates, so it restates
    it upward (reopening it if it had been spent to nothing) rather than opening a second
    lot behind it, which would sell the same bank transfer at two prices. A payment with
    no lot — one that predates them — opens one instead, which is the only answer that
    keeps invariant §2.3.1 true."

    Called in the same transaction as the row it names, by every writer that puts credit
    on a wallet. `balance_after` is `record_entry`'s own answer, so the balance BEFORE is
    a subtraction rather than a second read: two reads of one balance across one
    transaction is the drift this whole module takes an advisory lock to prevent.

    **THE REPAYMENT COMES FIRST AND BUYS NO MINUTES (plan §0 Q5).** A wallet driven
    negative already spent those minutes, at the rate of the lot that ran out; a new
    purchase settles that debt before it opens its own lot, exactly as telecom prepaid
    does. So ₹2,000 onto a wallet at -₹500 opens a lot of ₹1,500 and the client's runway
    reflects it. It needs no new state: the signed balance already carries the debt.
    """
    overdraft = max(-(balance_after - credits_inr), Decimal("0"))
    repaid = min(credits_inr, overdraft)
    remainder = (credits_inr - repaid).quantize(MONEY_Q, rounding=ROUNDING)
    if remainder <= 0:
        return CreditedLot(lot_id=None, credits_inr=Decimal("0"), repaid_overdraft_inr=repaid)
    if restate_lot_id is not None:
        await credit_lots.adjust_lot_for_restatement(
            session, lot_id=restate_lot_id, delta=remainder
        )
        return CreditedLot(
            lot_id=restate_lot_id, credits_inr=remainder, repaid_overdraft_inr=repaid
        )
    lot_id = await credit_lots.open_lot(
        session,
        tenant_id=tenant_id,
        credits_inr=remainder,
        sarvam_inr_per_min=rates.sarvam_inr_per_min,
        cartesia_inr_per_min=rates.cartesia_inr_per_min,
        source=source,
        pack_id=pack_id,
        ledger_entry_id=ledger_entry_id,
        override_of_pack_id=override_of_pack_id,
    )
    return CreditedLot(lot_id=lot_id, credits_inr=remainder, repaid_overdraft_inr=repaid)


@dataclass(frozen=True, slots=True)
class EntryLot:
    """The lot one ledger row opened, and how much that purchase was ever worth."""

    lot_id: UUID
    #: What the lot was SOLD as — not what is left on it. A correction is bounded by this
    #: (`remove_credit_from_lots`), because a lot's `credits_total` may never reach zero.
    credits_total: Decimal


async def lot_of_entry(session: AsyncSession, *, ledger_entry_id: UUID) -> EntryLot | None:
    """The lot one credit-adding ledger row opened, if it opened one.

    `ledger_entry_id` is UNIQUE on `credit_lots`, so this is at most one row. `None` for
    a row that opened none: a purchase entirely absorbed by an overdraft, or any credit
    written before lots existed.
    """
    found = (
        await session.execute(
            text("SELECT id, credits_total FROM credit_lots WHERE ledger_entry_id = :eid"),
            {"eid": ledger_entry_id},
        )
    ).first()
    if found is None:
        return None
    return EntryLot(lot_id=UUID(str(found[0])), credits_total=Decimal(str(found[1])))


@dataclass(frozen=True, slots=True)
class LotDebit:
    """One debit as the lots answered it."""

    #: False = a replay found the ledger row already there, and NOTHING was consumed.
    charged: bool
    #: The rupees taken off the wallet — the sum of every split, whatever its kind.
    credits_inr: Decimal
    #: The splits, already serialised into the row's `meta.lots`.
    splits: list[credit_lots.LotSplit]


async def record_usage_from_lots(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    ref: str,
    demand: credit_lots.LotDemand,
    extra_inr: Decimal = Decimal("0"),
    meta: dict[str, Any] | None = None,
    allow_negative: bool = True,
) -> LotDebit:
    """Consume the wallet's lots for one debit and append the ONE `usage` row that records it.

    `record_entry` is untouched and is still the only writer (hard rule 4); this wraps it
    so that the rupee delta is the SUM OF THE SPLITS rather than a figure computed beside
    them. That is the invariant §2.3.5 holds — `SUM(meta.lots[].credits)` equals the row's
    own `delta` — and it is what makes a month's statement and the margin panel
    re-derivable from the ledger alone.

    ORDER, and each step is load-bearing:

    1. the advisory lock, before the lookup that decides whether to write at all — a
       dedupe check outside it is the check-then-write hole two ARQ retries walk through;
    2. the replay lookup on `(tenant_id, 'usage', ref)`, so a re-run consumes NOTHING.
       This is the guard that makes the whole seam idempotent: a second consumption would
       be silent, permanent and invisible on an append-only ledger;
    3. the walk (`lots.consume`), which mutates lots;
    4. `record_entry`, which is the only thing that can still refuse. On
       `allow_negative=False` it raises and the caller's transaction rolls back — the
       lot decrements with it, because they are one transaction by construction.
    """
    await lock_tenant_credits(session, tenant_id)
    already = (
        await session.execute(
            # `tenant_id` in the predicate as well as in RLS: it is what makes this an
            # index scan, and it stops a ref ever being read across a scope this session
            # was not supposed to be answering for.
            text(
                "SELECT 1 FROM credit_ledger WHERE tenant_id = :tid AND ref = :ref "
                "AND reason = 'usage' LIMIT 1"
            ),
            {"tid": tenant_id, "ref": ref},
        )
    ).first()
    if already:
        return LotDebit(charged=False, credits_inr=Decimal("0"), splits=[])
    splits = await credit_lots.consume(session, tenant_id=tenant_id, demand=demand)
    if extra_inr > 0:
        # Face value, and NOT a `call` split — its minutes are the call's own and are
        # already carried above. See `charge_for_call`.
        splits += await credit_lots.consume(
            session, tenant_id=tenant_id, demand=credit_lots.AiAssistDemand(credits=extra_inr)
        )
    debited = credit_lots.credits_of(splits)
    if debited <= 0:
        return LotDebit(charged=False, credits_inr=Decimal("0"), splits=[])
    row_meta = dict(meta or {})
    row_meta["lots"] = credit_lots.split_meta(splits)
    await record_entry(
        session,
        tenant_id=tenant_id,
        delta=-debited,
        reason="usage",
        ref=ref,
        meta=row_meta,
        allow_negative=allow_negative,
    )
    return LotDebit(charged=True, credits_inr=debited, splits=splits)


@dataclass(frozen=True, slots=True)
class CreditRemoval:
    """What taking credit back off the lots actually did.

    `overdraft_inr` is the part of the correction NO LOT COULD ABSORB, because the credit
    had already been spoken: it becomes wallet overdraft, which the signed balance carries
    and the next purchase repays before opening its own lot. It is returned rather than
    discarded because an operator who reduces a client's credit past what their lots hold
    has created that overdraft, and until this field existed nothing told them — the
    console showed a successful correction and the client discovered it when their
    dialling stopped.

    **ONE DEFINITION FOR BOTH SHAPES, AND IT IS THE SPLITS.** It is deliberately NOT
    `LotRestatement.shortfall` on the restatement path: what that lot could not absorb is
    taken off the REST of the queue first (see below), so a shortfall of ₹2,000 met by a
    second open lot leaves no overdraft at all. The overdraft is the portion that reached
    no lot in either shape — the splits with no `lot_id` — and it is the only figure the
    balance actually goes negative by.
    """

    splits: list[credit_lots.LotSplit]
    overdraft_inr: Decimal


def _overdraft_of(splits: Sequence[credit_lots.LotSplit]) -> Decimal:
    """The portion of a debit that came out of no lot — plan §0 Q5's overdraft.

    `lot_id is None` is the marker (`lots.CallSplit`/`AiAssistSplit`), and it is the same
    test `split_meta` uses to decide the key is absent, so what an operator is told and
    what the ledger row records cannot come apart.
    """
    return to_paise(sum((split.credits for split in splits if split.lot_id is None), Decimal("0")))


async def remove_credit_from_lots(
    session: AsyncSession, *, tenant_id: UUID, corrected_entry_id: UUID, amount_inr: Decimal
) -> CreditRemoval:
    """Take credit back off the lots when an operator corrects an entry that ADDED it.

    Two shapes, and the branch is which of them the corrected row is:

    * **it opened a lot and the correction is smaller than that lot's total** — the
      purchase was mis-recorded, so the LOT is restated downwards (ADDENDUM 2 §2.2):
      `credits_total` falls to what actually arrived and `credits_remaining` floors at
      zero. The rates never move, which is the promise the client was sold;
    * **anything else** — the entry opened no lot at all (a credit that predates lots, or
      one entirely absorbed by an overdraft), or the correction takes back the WHOLE
      purchase, which a restatement cannot express because `credits_total > 0` is a CHECK
      and a lot of nothing is not a correction. Then the credit is spent off the FIFO
      queue at face value, exactly as a dashboard-AI debit is, and the splits say which
      lots it came out of.

    **THE SHORTFALL IS CONSUMED, NOT DISCARDED, AND THAT IS INVARIANT §2.3.1.** A
    restatement floors the corrected lot at zero and hands back what it could not absorb.
    That figure used to be dropped while the caller wrote the FULL correction to the
    ledger, so the balance fell by more than the lots did and `SUM(credits_remaining)`
    stayed permanently above it: lot A 5,000/1,000 left beside lot B of 5,000 on a balance
    of 6,000, corrected by -2,000, left a balance of 4,000 against lots reading 5,000. The
    wallet, the runway and the voice picker all overstated by ₹1,000 for ever; when B
    drained, the balance reached -1,000 while the lots still read +1,000, `credits_exhausted`
    fired a thousand rupees early, and the next top-up repaid an overdraft the lots had
    never seen. So the shortfall is taken off the REST of the queue, oldest first, and only
    what no lot can cover becomes overdraft — which is exactly what the second shape does
    with the whole amount.

    Returns the splits, which the caller writes onto the adjustment row exactly as a debit
    does, and — in BOTH shapes — how much of the correction reached no lot.
    """
    lot = await lot_of_entry(session, ledger_entry_id=corrected_entry_id)
    if lot is not None and amount_inr < lot.credits_total:
        restated = await credit_lots.adjust_lot_for_restatement(
            session, lot_id=lot.lot_id, delta=-amount_inr
        )
        if restated.shortfall <= 0:
            return CreditRemoval(splits=[], overdraft_inr=_ZERO_PAISE)
        # `AiAssistDemand` and not a call: this is rupees off a wallet with no minutes and
        # no voice behind them, which is precisely what that demand means (ADDENDUM 2
        # §2.1). The splits land in the adjustment row's `meta.lots` beside the second
        # shape's, so one reader totals both.
        shortfall_splits = await credit_lots.consume(
            session,
            tenant_id=tenant_id,
            demand=credit_lots.AiAssistDemand(credits=restated.shortfall),
        )
        return CreditRemoval(splits=shortfall_splits, overdraft_inr=_overdraft_of(shortfall_splits))
    splits = await credit_lots.consume(
        session, tenant_id=tenant_id, demand=credit_lots.AiAssistDemand(credits=amount_inr)
    )
    return CreditRemoval(splits=splits, overdraft_inr=_overdraft_of(splits))


#: The `meta.kind` a re-price marker carries, the shape `ADJUSTMENT_META_KIND` and
#: `RESTATEMENT_META_KIND` established. It is also what `c9f3a71e58d2`'s `lot_migration`
#: marker is: a zero-delta `adjustment` row whose whole job is to give a lot an entry to
#: name.
LOT_REPRICE_META_KIND: Final = "lot_rate_override"

#: The marker's ledger reference, and therefore THE idempotency key for a re-price —
#: enforced by `ux_credit_ledger_tenant_reason_ref` rather than by a reader's `if`, which
#: is `adjustment_ref`'s argument applied to the writer with no external reference of its
#: own. Content-addressed over (lot, pack) so a double-clicked Save converges: the second
#: click derives the same ref, finds the row and re-prices nothing. It cannot collapse two
#: genuinely distinct acts, because the first one CLOSES the lot it names — a second
#: re-price is a re-price of the REPLACEMENT, under the replacement's id.
LOT_REPRICE_REF_PREFIX: Final = "lot_rates"


def lot_reprice_ref(*, lot_id: UUID, pack_id: str) -> str:
    return f"{LOT_REPRICE_REF_PREFIX}:{lot_id}:{pack_id}"


@dataclass(frozen=True, slots=True)
class RepricedLot:
    """What a re-price did: one lot closed, one opened, and no money moved."""

    #: The lot that was closed. Its rates, source and pack are untouched — it stays on the
    #: table as the truthful record of what was originally sold.
    closed_lot_id: UUID
    #: The lot now carrying that credit, at the chosen pack's rates. It INHERITS the
    #: closed lot's `opened_at`, so the client's spend order does not move.
    replacement_lot_id: UUID
    #: What moved across: the closed lot's `credits_remaining`.
    credits_inr: Decimal
    #: The zero-delta marker row the replacement names.
    ledger_entry_id: UUID
    #: What the credit was priced at before, and what it is priced at now.
    previous_rates: LotRates
    rates: LotRates


async def reprice_lot(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    lot_id: UUID,
    pack: CreditPack,
    reason: str,
    operator_id: UUID | None,
) -> RepricedLot | None:
    """Sell credit a client ALREADY HOLDS at another pack's rates — close and replace.

    THE QUESTION THIS ANSWERS IS NOT `apply_credit_to_lots`' `override_of_pack_id`. That
    one prices credit AS IT ARRIVES: an operator recording a payment says "open this at the
    ₹25,000 pack's rates", and the decision is made once, at the instant money is booked.
    This one CORRECTS a decision already made, on credit the client is holding — the
    promotion nobody applied at the till, the negotiated rate agreed after the transfer
    landed. Two acts, two audiences, two audit actions; neither substitutes for the other.

    **IT IS NOT AN UPDATE, AND MUST NEVER BECOME ONE.** `credit_lots_terms_frozen`
    (migration `c9f3a71e58d2`) refuses any UPDATE touching a lot's rates, its source or its
    pack, because "the rates of a purchase are frozen for the life of its credit" is what
    the client was sold. So the original lot is CLOSED at its own terms and a replacement
    opens carrying its `credits_remaining` at the new ones. Both rows survive: the closed
    one says what was sold, the open one says what is now promised.

    **THE REPLACEMENT INHERITS `opened_at`** — see `lots.open_lot`. Consumption is FIFO by
    that column, so a replacement stamped now would move re-priced credit to the back of
    the queue and change the spend order the client was promised.

    **NO MONEY MOVES.** `SUM(credits_remaining)` is unchanged across the pair (invariant
    §2.3.1): what leaves the closed lot arrives on the replacement in the same transaction.
    The ledger nonetheless gets a row, because `credit_lots.ledger_entry_id` is NOT NULL
    and UNIQUE and the replacement must name one — a ZERO-DELTA `adjustment` marker, the
    device migration `c9f3a71e58d2` used for the opening lots and for the same reason.

    `None` = this re-price is already on the ledger and nothing moved; the caller answers
    from the marker's own lot rather than writing a second one.
    """
    await lock_tenant_credits(session, tenant_id)
    # THE REPLAY CHECK COMES FIRST, and the order is load-bearing rather than tidy. This
    # re-price's own first act CLOSES the lot it names, so a second click would meet the
    # `lot_is_spent` refusal below and be told its own success was a failure. `record_topup`
    # takes the same order for the same reason: idempotency before business rules, because
    # a replay is not a new decision to judge.
    ref = lot_reprice_ref(lot_id=lot_id, pack_id=pack.pack_id)
    if await find_entry_by_ref(session, tenant_id=tenant_id, reason="adjustment", ref=ref):
        return None
    lot = await credit_lots.read_lot(session, lot_id=lot_id)
    if lot is None:
        # Under RLS "no such lot" and "another tenant's lot" are one answer, deliberately.
        raise ProblemError.not_found("credit lot")
    if lot.closed_at is not None:
        raise ProblemError.business_rule(
            "lot_is_spent",
            "That credit has all been spent, so there is nothing left to re-price.",
            remediation=(
                "Re-pricing changes what the credit a client still holds costs per minute; "
                "it cannot repay minutes already made. To give this client something back, "
                "grant credit instead — it opens a lot of its own."
            ),
        )
    # THE CARD IN FORCE NOW, not the static catalogue: an operator saying "sell this at
    # the pro pack's rates" means the pro pack as it is published today, and a card
    # recorded in the ops console is what publishes it (`RateCard`).
    rates = (await rate_card_at(session, at=datetime.now(UTC))).of_pack(pack)
    previous = LotRates(
        sarvam_inr_per_min=lot.sarvam_inr_per_min,
        cartesia_inr_per_min=lot.cartesia_inr_per_min,
    )
    if rates == previous:
        # Refused rather than performed. It would be a valid close-and-replace producing
        # an identical lot, a marker row and an audit entry recording a decision nobody
        # made — and it is what an operator sees when they have picked the wrong lot.
        raise ProblemError.business_rule(
            "lot_already_at_those_rates",
            (
                f"That credit is already priced at ₹{rate_to_display(rates.sarvam_inr_per_min)} "
                f"and ₹{rate_to_display(rates.cartesia_inr_per_min)} a minute."
            ),
            remediation="Choose a different pack, or a different lot.",
        )

    balance = await record_entry(
        session,
        tenant_id=tenant_id,
        delta=Decimal("0"),
        reason="adjustment",
        ref=ref,
        meta={
            "kind": LOT_REPRICE_META_KIND,
            "lot_id": str(lot_id),
            "reason": reason,
            # BOTH pack ids and BOTH rate pairs, as strings (hard rule 7 — a rate a reader
            # parsed into a float is a rate nobody can reconcile). Written out rather than
            # left to be looked up from today's card: the card moves and this decision does
            # not, and an audit trail that has to be re-joined to a catalogue is one nobody
            # reads.
            "previous_pack_id": lot.override_of_pack_id or lot.pack_id,
            "rates_of_pack_id": pack.pack_id,
            "previous_sarvam_inr_per_min": str(previous.sarvam_inr_per_min),
            "previous_cartesia_inr_per_min": str(previous.cartesia_inr_per_min),
            "sarvam_inr_per_min": str(rates.sarvam_inr_per_min),
            "cartesia_inr_per_min": str(rates.cartesia_inr_per_min),
            "credits_inr": str(lot.credits_remaining),
            **({"repriced_by": str(operator_id)} if operator_id else {}),
        },
        # A wallet in overdraft may still hold an open lot (a partial repayment), and a
        # marker that moves nothing must not be the write that refuses on a negative
        # balance it did not cause.
        allow_negative=True,
        allow_zero=True,
    )
    marker = await find_entry_by_ref(session, tenant_id=tenant_id, reason="adjustment", ref=ref)
    assert marker is not None, "the marker was inserted in this transaction"

    if not await credit_lots.close_lot(
        session, lot_id=lot_id, seen_remaining=lot.credits_remaining
    ):
        # A call spent part of this lot between the read above and this write. Refused
        # rather than retried: the figure the operator was shown, and confirmed against, is
        # no longer what the lot holds.
        raise ProblemError.conflict(
            "credit_lots_contended",
            "This client's credit changed while we were re-pricing it.",
            remediation="Reload the wallet and re-price the lot again.",
        )
    replacement = await credit_lots.open_lot(
        session,
        tenant_id=tenant_id,
        credits_inr=lot.credits_remaining,
        sarvam_inr_per_min=rates.sarvam_inr_per_min,
        cartesia_inr_per_min=rates.cartesia_inr_per_min,
        source="override",
        # NULL for the same reason the purchase-time override leaves it NULL: the client
        # did not buy this pack, they were given its terms, and stamping `pack_id` would
        # report a purchase that never happened. `override_of_pack_id` is where the
        # borrowing is recorded.
        pack_id=None,
        ledger_entry_id=marker.entry_id,
        override_of_pack_id=pack.pack_id,
        opened_at=lot.opened_at,
    )
    log.info(
        "credit_lot_repriced",
        extra={
            "tenant_id": str(tenant_id),
            "lot_id": str(lot_id),
            "replacement_lot_id": str(replacement),
            "balance_after": str(balance.amount_inr),
        },
    )
    return RepricedLot(
        closed_lot_id=lot_id,
        replacement_lot_id=replacement,
        credits_inr=lot.credits_remaining,
        ledger_entry_id=marker.entry_id,
        previous_rates=previous,
        rates=rates,
    )


async def plan_tier_of(session: AsyncSession, tenant_id: UUID) -> str:
    """The one reader of `organizations.plan_tier`, and the answer for a row it cannot see.

    THE FALLBACK IS THE PLATFORM DEFAULT, AND IT USED TO BE THE LITERAL `"managed"`
    (D-521). No row comes back when the id names nobody OR — the case that matters —
    when the session is scoped to a different tenant and RLS hides it. Under D-34 the
    literal was harmless because it WAS the default: the invisible row almost certainly
    said `managed` too. D-521 inverted that, and a stale literal would have answered
    "invoiced" for an account that is credit-gated, which every caller reads as a
    permission: `credits_exhausted` returns False (dial anyway, empty wallet and all),
    `read_wallet_summary` reports no wallet, and `purchase_ai_overage` refuses a client
    who may buy. Spelled from `DEFAULT_PLAN_TIER` so it moves with the column's own
    server default rather than being a second opinion about it.
    """
    tier = (
        await session.execute(
            text("SELECT plan_tier FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar()
    return str(tier or DEFAULT_PLAN_TIER)


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


def _month_bounds(month: str, *, since: datetime | None = None) -> dict[str, datetime]:
    """The two binds `_IST_MONTH_WINDOW` reads, so a caller cannot name the window and
    then supply half of it.

    `since` RAISES THE FLOOR AND NEVER LOWERS IT (D-536). A trial's start or end is a
    counting-period boundary (`billing/trials.counter_epoch`), and the client's own usage
    figures are counted from it rather than from the 1st — "when the trial is over the
    numbers should start from 0 again". `max` rather than replacement is the whole safety
    property: a boundary in a PREVIOUS month must not widen a month's window backwards,
    and a boundary in a FUTURE month cannot reach a month that is already closed.

    Passed only by the CLIENT-facing reads. Our own cost and margin reads
    (`billing/attribution.py`, `tier_usage`, `margin_for_tenant`, the invoice) deliberately
    never pass it: what a trial cost us must stay true and countable for ever, which is the
    only way anybody can say what a trial was worth.
    """
    start, end = ist_month_window(month)
    return {"month_from": max(start, since) if since is not None else start, "month_to": end}


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


# ─── THE OVERAGE RUNGS, AND THE LEDGER TOKENS THAT NAME THEM ────────────────────
#
# A rung is one of the PLAN's two overage-rate slots — `plans.overage_rate` and
# `plans.overage_rate_second` — plus a third bucket that is not a rung at all. They are a
# founder PRICING LEVER and **NOT voice-quality tiers**: there is one voice quality now
# (the single-tier voice decision), nothing about which voice spoke chooses a rung, and
# which voice DID speak is a different fact on a different key (`meta.voice_tier`,
# `agents/voices.py`).
#
# ⚠ **THE FOUR STRINGS BELOW ARE LEDGER TOKENS AND THEY ARE FROZEN FOREVER (D-558).**
# They are not vocabulary and no reader may re-spell them. `usage_events` is in
# `db/registry.APPEND_ONLY_TABLES` and a database trigger enforces it: there is no UPDATE,
# ever, so every row already written carries the key `tts_tier` and the value `premium`
# and always will. Writing a new token instead would oblige every reader of a money figure
# to accept BOTH for the rest of the product's life — and the first reader that ever
# stopped would silently re-file every closed month's minutes into `unattributed`, which
# `tier_usage` bills at the CHEAPER rung. That moves settled invoices and the margin card
# for months a client has already paid. Renaming them buys nothing to set against that:
# the token reaches no human. What a client reads is `invoice._RUNG_WORDING`, what an
# operator reads is the admin screen's own labels, and D-558 corrected both.
#
# So the CONSTANTS carry the meaning and the strings stay put. Nothing in this module
# spells a rung inline; every use goes through a name that says which rate it is.

#: The `usage_events.meta` key the post-call pipeline stamps the rung on. Frozen: see
#: above. Spelled once so the writer (`pipeline._meter`) and the reader (`_ROW_TIER_SQL`)
#: cannot drift apart, which is the failure this key has no way to survive.
LEDGER_RUNG_KEY: Final = "tts_tier"

#: The rung every call is metered on: the plan's BASE overage rate, `plans.overage_rate`.
#: With one voice quality this is a single constant rather than a per-call choice —
#: `pipeline._meter` stamps it on every metered call, and no path stamps anything else.
BASE_OVERAGE_RUNG: Final = "premium"

#: The plan's SECOND overage rate, `plans.overage_rate_second`. No live path stamps it;
#: rows in the archive carry it, and `split_overage`/`overage_rungs` still price it,
#: because a founder setting a second rate is one column away.
SECOND_OVERAGE_RUNG: Final = "value"

#: NOT A RUNG — a row written before rung attribution existed, or by a path that could not
#: attribute one. Reporting keeps the distinction (`tier_usage.minutes_unattributed`);
#: PRICING folds it into the cheaper slot, because a call we cannot attribute is never
#: charged the dearer rate (SURFACES §2b).
UNATTRIBUTED_RUNG: Final = ""

#: The rungs, in the order every map in this module lists them. The ORDER is load-bearing:
#: `allocate_paise` breaks ties by position, so a set that iterated differently between two
#: renders of one closed month would move a paisa between two buckets for no reason.
OVERAGE_RUNGS: Final = (BASE_OVERAGE_RUNG, SECOND_OVERAGE_RUNG, UNATTRIBUTED_RUNG)

#: The two rungs a row may actually NAME. `UNATTRIBUTED_RUNG` is what a row that names
#: none of these falls to, so it is deliberately not in here.
_NAMED_RUNGS: Final = (BASE_OVERAGE_RUNG, SECOND_OVERAGE_RUNG)


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

    These rungs are the PLAN'S two overage-rate slots (`overage_rate` /
    `overage_rate_second`), which are a founder pricing lever independent of the single
    voice quality — the second rate is NULL on every plan, so today only the base
    rung ever carries minutes. The label is a plain `str` (it was the voice `TtsTier`,
    removed by the single-tier voice decision) because that is all `invoice._RUNG_WORDING`
    and this module need of it.
    """

    label: str
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
    shape every invoice had before a second rate could be quoted — and `rate_value
    is None` is "this plan quotes no separate value rate", never "the value rung is
    free".
    """
    if rate_value is None:
        both = premium_min + value_min
        return (OverageRung(BASE_OVERAGE_RUNG, both, rate, to_paise(both * rate)),)
    return (
        OverageRung(BASE_OVERAGE_RUNG, premium_min, rate, to_paise(premium_min * rate)),
        OverageRung(SECOND_OVERAGE_RUNG, value_min, rate_value, to_paise(value_min * rate_value)),
    )


# --- THE cost expression, and the rung a row's money is counted on ----------------
#
# **WHY A ZERO-`qty` ROW IS A WHOLE-LEG ROW (D-370).** `unit_cost_paid` is a price PER
# UNIT OF `qty` and every reader multiplies the two. `pipeline._unit_price` cannot divide
# by a zero duration, so for a call the engine reports as zero-length it keeps the LEG
# COST whole on the row — and `qty * unit_cost_paid` then evaluates that leg at ₹0.00.
# Measured on a zero-duration call the engine charged ₹1.0000 for (₹0.20 network,
# ₹0.50 platform, ₹0.30 synthesizer): `margin_for_tenant` reported our cost as ₹0.30 —
# 70% light — while `spend_state.spend_used`, which takes `cost.total_inr` from the
# adapter and never touches these rows, recorded the full rupee. Two accounts of one
# call, which is the one thing two readers of the same money may never be. (The CLIENT's
# closed-month `spend_used` is NOT among the affected readers and has not been since
# P1.3: `calling_revenue_inr` prices it off MINUTES at the client's own rate, not off
# `unit_cost_paid`. The blast radius is the admin margin card and `tier_usage`, which is
# where our supplier cost is published and nowhere else.) `_unit_price`'s own
# docstring named this and named the fix ("the closable half is a reader that treats a
# zero-qty row as a whole-leg row, and that lives in `apps/api/billing`"); this is that
# reader. Writing `qty = 1` instead would bill the client a second that never happened.
#
# A NEGATIVE `qty` cannot reach here — `pipeline._billable_seconds` floors a duration at
# zero — so `qty = 0` is the only case the branch has to name.
#
# Spelled ONCE, here, because two readers of one money fact is the D-103 shape this
# module has already paid for twice.
_ROW_COST_SQL: Final = (
    "CASE WHEN qty = 0 THEN COALESCE(unit_cost_paid, 0) ELSE qty * COALESCE(unit_cost_paid, 0) END"
)

# **THE RUNG A CALL IS COUNTED ON IS THE ONE `pipeline._meter` STAMPED.** It reads
# `meta.tts_tier` off the row directly. There used to be a window-function re-attribution
# here (D-372) that let a cross-rung TTS-tier correction move a call's minutes to the rung
# that actually ran; the single-tier voice decision removed that correction — with one
# voice quality a call can never be metered on the wrong rung — so the reader reads the
# stamp and nothing re-writes it.
_ROW_TIER_SQL: Final = f"COALESCE(meta->>'{LEDGER_RUNG_KEY}', '{UNATTRIBUTED_RUNG}')"


#: WHICH LANGUAGE MODEL A ROW'S MINUTES CARRY A SURCHARGE FOR — the model's own name when
#: the plan's `llm_model_surcharge` applies to it, and `''` when it does not (D-455).
#:
#: **THE SQL TWIN OF `rates.llm_surcharge_applies`, and the two are held together by a
#: test rather than by care** (`tests/llm_model_surcharge_test.py` evaluates this
#: expression against every model x source pair and compares it with the Python predicate).
#: There has to be a twin: this reader groups a whole month in the database, while
#: `pipeline._meter` has to place ONE call in the same buckets in Python before the month
#: is re-read. Both spellings are built from the same two constants in `billing/rates.py`,
#: so neither can be edited into a different rule without the other noticing.
#:
#: Both halves of the D-454 stamp are read and each refuses on its own — a row that names
#: no model, names the base-rate model, or was chosen by the PLATFORM rather than by the
#: client carries no surcharge. A row written before the stamp existed has neither key,
#: `->>` yields NULL, and the row falls to `''`: the same "an unproven row is never billed
#: the dearer thing" asymmetry the rung reader applies to a call with no stamped rung.
#: THE VALUES ARE BOUND, NOT SPLICED, and that is not only a `check_raw_sql` rule.
#: They are VALUES rather than identifiers, so a bind is what they wanted all along; the
#: first spelling built them with `", ".join(...)` over `sorted(...)`, which the guard
#: refused because it cannot follow a comprehension variable through a call — correctly,
#: since "every character was typed in this repo" is exactly what it cannot prove there.
#: `_NOT_AI_UNITS` below uses the same join idiom and passes only because it has no
#: `sorted()`; matching it would have been the smaller change and the worse one, leaving a
#: value interpolated into SQL for no reason but provability.
#:
#: ⚠ **IT USED TO SPELL THE RULE "NOT THE BASE MODEL", AND THAT INVERTED ON A CHEAPER ONE.**
#: `NOT IN ('', :base_rate_llm_model)` was an exact twin of the Python predicate for as long
#: as every choosable model was dearer than `gpt-4o-mini`. The multi-provider catalogue broke
#: that — `gemini-2.5-flash-lite` lists at $0.10/$0.40 against the base model's $0.15/$0.60 —
#: so both spellings would have surcharged a client **for saving us money**, and would have
#: gone on agreeing with each other while doing it. **Two twins that share a BUG are worse
#: than no twin**, which is why the fix is not a second `NOT IN` list typed here: the SET is
#: computed by `rates.is_surchargeable_llm_model` and bound, so the SQL and the Python are
#: now one predicate expressed twice rather than two rules that happen to match.
_SURCHARGED_MODEL_SQL: Final = (
    "CASE WHEN meta->>'llm_model_source' = ANY(:llm_client_sources) "
    "AND COALESCE(meta->>'llm_model', '') = ANY(:surcharged_llm_models) "
    "THEN meta->>'llm_model' ELSE '' END"
)


def _surcharge_binds() -> dict[str, object]:
    """The two binds `_SURCHARGED_MODEL_SQL` reads, for the same reason `_month_bounds`
    exists: a caller that names the fragment cannot then supply half of what it needs.

    **`surcharged_llm_models` IS DERIVED FROM THE PYTHON PREDICATE, NEVER RETYPED**, which is
    what makes the twin a twin. It is stated over the whole CATALOGUE rather than the
    selectable set because this reader groups a HISTORICAL month: a row can name a model that
    has since been withdrawn, and how it was bucketed when it was metered must not change
    because a picker did. A model the catalogue has forgotten entirely is absent from the
    list and therefore unsurcharged — the same "an unproven row is never billed the dearer
    thing" asymmetry the predicate itself applies.

    Sorted so the parameter is stable across processes — a frozenset's iteration order is
    not, and an unstable bind makes two identical queries look different in a slow-query
    log for no reason.
    """
    return {
        "llm_client_sources": sorted(CLIENT_CHOSEN_LLM_SOURCES),
        "surcharged_llm_models": sorted(
            model for model in LLM_MODELS if is_surchargeable_llm_model(model)
        ),
    }


#: The bucket key for minutes that carry NO model surcharge. Named because three readers
#: compare against it and an empty-string literal in a pricing branch reads like an
#: oversight rather than like the decision it is.
UNSURCHARGED_MODEL: Final = ""


@dataclass(frozen=True, slots=True)
class MonthSeconds:
    """One month's ledger, read ONCE and partitioned TWO ways over the same seconds.

    **WHY ONE READ AND NOT TWO.** The TTS rung and the language model are independent
    facts about the same `telephony_s` rows, and the two partitions must add to the same
    monthly total to the second — `rung_minutes` and `llm_model_minutes` both allocate the
    month's paise against `to_paise(total seconds / 60)`, so a second aggregate taken at a
    second instant (a concurrent `_meter` commits between them) would publish a minute
    count that the surcharge line and the overage lines disagreed about. `_tier_totals`
    already carries the same argument one layer up, and `attribution.py` was written
    because ignoring it turned an ordinary concurrent write into a 500.
    """

    #: Per TTS rung (`premium` / `value` / `''`), the D-372-corrected attribution.
    by_rung: dict[str, Decimal]
    #: Per rung, OUR supplier cost — `unit_cost_paid`, never a client price.
    cost_by_rung: dict[str, Decimal]
    #: Per SURCHARGED language model, with everything else under `UNSURCHARGED_MODEL`.
    by_llm_model: dict[str, Decimal]


async def rung_seconds(
    session: AsyncSession, *, tenant_id: UUID, month: str, since: datetime | None = None
) -> MonthSeconds:
    """(SECONDS, our cost) per TTS rung — and per surcharged model — for one month. THE query.

    Split out of `_tier_totals` when the meter needed the same month's rungs to price a
    call's increment against (`month_increment`). It returns SECONDS rather than
    minutes deliberately: seconds are what the ledger stores and they are exact, so a
    caller that has to reconstruct "the month before this call" can subtract there and
    quantize afterwards. Subtracting from the QUANTIZED minutes instead would not
    reproduce the state the previous call priced against — `allocate_paise` distributes
    a remainder across the whole set, so it is not linear in any one bucket — and the
    increments would stop telescoping to the month's own total.

    One thing is decided by an expression above rather than inline, and it is a money fix
    rather than tidying: `_ROW_COST_SQL` (a zero-`qty` row carries its WHOLE leg cost,
    D-370). The rung comes straight off `meta.tts_tier` (`_ROW_TIER_SQL`). The subquery
    exists so the month predicate stays INSIDE it and the range still drives
    `ix_usage_events_tenant_occurred`.

    **THE SECOND GROUPING COLUMN IS FREE** (D-455). `_SURCHARGED_MODEL_SQL` reads two more
    `meta` keys off rows already being scanned and adds them to the `GROUP BY`; the
    cardinality is (rungs x models a client has chosen this month), which is at most a
    handful. Adding a second STATEMENT instead would have been the defect: the two
    partitions must add to the same monthly seconds, and two aggregates at two instants
    cannot promise that while the meter is writing.
    """
    rows = (
        await session.execute(
            # NUMERIC end to end — a SUM of NUMERIC columns and a SUM of their products.
            # Nothing on this path becomes a float (hard rule 7).
            text(
                "SELECT tier, llm_model, COALESCE(SUM(secs), 0), COALESCE(SUM(cost), 0) FROM ("
                f"  SELECT {_ROW_TIER_SQL} AS tier, "
                f"   {_SURCHARGED_MODEL_SQL} AS llm_model, "
                "    CASE WHEN unit_type = 'telephony_s' THEN qty ELSE 0 END AS secs, "
                f"   {_ROW_COST_SQL} AS cost "
                f"  FROM usage_events WHERE tenant_id = :tid AND {_IST_MONTH_WINDOW} "
                f"  AND {_NOT_AI_UNITS}"
                ") attributed GROUP BY tier, llm_model"
            ),
            {"tid": tenant_id, **_month_bounds(month, since=since), **_surcharge_binds()},
        )
    ).all()

    seconds = dict.fromkeys(OVERAGE_RUNGS, Decimal("0"))
    cost = dict.fromkeys(OVERAGE_RUNGS, Decimal("0"))
    by_model: dict[str, Decimal] = {UNSURCHARGED_MODEL: Decimal("0")}
    for label, model, secs, spent in rows:
        # An unrecognised label is treated as unattributed rather than trusted: a tier
        # this module does not know is not a tier it can price.
        key = str(label) if str(label) in _NAMED_RUNGS else UNATTRIBUTED_RUNG
        secs_d = Decimal(str(secs or 0))
        seconds[key] += secs_d
        cost[key] += Decimal(str(spent or 0))
        # The model bucket is whatever the SQL decided, verbatim: `''` is the
        # no-surcharge bucket and anything else is a model identifier the client chose.
        # No re-validation here — a second Python opinion about which models are
        # surchargeable is precisely the twin this expression exists to avoid.
        bucket = str(model or UNSURCHARGED_MODEL)
        by_model[bucket] = by_model.get(bucket, Decimal("0")) + secs_d
    return MonthSeconds(by_rung=seconds, cost_by_rung=cost, by_llm_model=by_model)


def _minutes_from_seconds(
    seconds: Mapping[str, Decimal], keys: Sequence[str]
) -> dict[str, Decimal]:
    """A partition of a month's SECONDS as paise-exact MINUTES that add to the month total.

    The division happens here, once per bucket, rather than in SQL: `SUM(a)/60 + SUM(b)/60`
    and `SUM(a+b)/60` are two roundings of one number and Postgres picks the result scale,
    so dividing per bucket in the query would put the parts and the total a hair apart
    before `allocate_paise` could even see them.

    `keys` is passed rather than derived so the caller fixes the ORDER: `allocate_paise`
    hands its spare paise out by discarded fraction and breaks ties BY POSITION, so an
    order that varied between two renders of one closed month would move a paisa between
    two buckets for no reason.

    Called once per partition of the SAME seconds (rungs, and surcharged models), which is
    why the total is computed from `seconds.values()` rather than from `keys`: both
    partitions round to the identical monthly minute figure by construction.
    """
    exact = [seconds[key] / _SECONDS_PER_MINUTE for key in keys]
    total = to_paise(sum(seconds.values(), Decimal("0")) / _SECONDS_PER_MINUTE)
    return dict(zip(keys, allocate_paise(exact, total), strict=True))


def rung_minutes(seconds: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Per-rung SECONDS -> per-rung MINUTES, paise-exact and summing to the month's total."""
    return _minutes_from_seconds(seconds, OVERAGE_RUNGS)


def llm_model_minutes(seconds: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Per-MODEL SECONDS -> per-model MINUTES, the same allocation as `rung_minutes`.

    Sorted keys, because the model set is open where `OVERAGE_RUNGS` is a fixed tuple, and
    `_minutes_from_seconds` needs a stable order to place its remainder deterministically.
    `UNSURCHARGED_MODEL` (`''`) sorts first, which is arbitrary and stable — the only
    property that matters is that it does not depend on dict iteration.
    """
    return _minutes_from_seconds(seconds, sorted(seconds))


@dataclass(frozen=True, slots=True)
class MonthTotals:
    """`MonthSeconds` with the two minute partitions allocated. What every panel prices off.

    Both minute maps are allocations of the SAME monthly total, so `sum(by_rung.values())`
    and `sum(by_llm_model.values())` are the identical figure — which is what lets the
    overage lines and the surcharge line sit on one invoice without a reconciliation.
    """

    by_rung: dict[str, Decimal]
    cost_by_rung: dict[str, Decimal]
    by_llm_model: dict[str, Decimal]


async def _tier_totals(
    session: AsyncSession, *, tenant_id: UUID, month: str, since: datetime | None = None
) -> MonthTotals:
    """(minutes, our cost) per TTS rung — and minutes per surcharged model — for one month.

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
    unfiltered those rows would land in the `""` bucket and do two wrong things at once:
    inflate `tier_usage.cost_unattributed_inr`, which an operator reads as "calls we
    could not attribute a voice to"; and add our absorbed AI cost to
    `margin_for_tenant`'s cost side without the matching revenue. The AI ledger has its
    own reader (`billing/ai_quota.py::read_ai_quota`) and this one stays about minutes.

    A THIRD consequence used to be listed here and is no longer reachable: our absorbed
    cost landing in a closed month's `spend_used_inr` on the CLIENT's panel, "because
    `_spend_used` sums this map". It did, until P1.3 — the closed branch is now
    `calling_revenue_inr`, priced off MINUTES at the client's own rate, and never reads
    the cost half of this map at all. The filter is still required for the two above; the
    sentence is corrected rather than deleted because a reader who finds the old claim
    elsewhere should be able to see it was retired and why.
    """
    read = await rung_seconds(session, tenant_id=tenant_id, month=month, since=since)
    return MonthTotals(
        by_rung=rung_minutes(read.by_rung),
        cost_by_rung=read.cost_by_rung,
        by_llm_model=llm_model_minutes(read.by_llm_model),
    )


@dataclass(frozen=True, slots=True)
class PricedLlmSurcharge:
    """A whole month's language-model surcharge (D-455). The sibling of `PricedOverage`.

    **IT IS ADDITIVE AND IT DOES NOT TOUCH THE ALLOWANCE.** The plan's `included_min` is
    spent on CALLING minutes by `priced_overage`, which this deliberately does not enter:
    a client inside their allowance who moves to the dearer model costs us 2.7x more on
    every one of those included minutes, so a surcharge that vanished under the allowance
    would leave the defect D-455 exists to close open for every managed client who never
    goes into overage. The upgrade is priced on the minutes that USED it, which is also
    the only rule with no allocation policy to invent — `split_overage` had to choose
    which rung the allowance lands on, and a second such choice across a second dimension
    would be a founder decision wearing a function.
    """

    #: Minutes the surcharge was charged on. A PART of `usage_summary.minutes_used`, and
    #: zero whenever the plan quotes no surcharge — there is no charge to attribute then.
    minutes: Decimal
    #: The models those minutes ran on, sorted. Named on the statement, because a client
    #: seeing a bigger number has to be able to reach the screen where they caused it.
    models: tuple[str, ...]
    #: `minutes x rate`, quantized ONCE. What the invoice's single upgrade line says.
    total_inr: Decimal


def priced_llm_surcharge(
    *, minutes_by_model: Mapping[str, Decimal], surcharge: Decimal | None
) -> PricedLlmSurcharge:
    """THE one pricing of a month's model surcharge. The panel and the invoice both call it.

    `minutes_by_model` is `llm_model_minutes`' own output — paise-exact minutes that add to
    the month's published total — with `UNSURCHARGED_MODEL` holding everything the plan
    does not surcharge. That key is skipped here rather than filtered upstream, so the
    minutes handed in are always the whole month and the surcharged share is visibly a
    part of it.

    **ONE AMOUNT FOR ALL SURCHARGED MODELS, NOT ONE PER MODEL, and that is a deliberate
    departure from `overage_rungs` next door.** The two rungs there carry two DIFFERENT
    rates, so a single blended line could not multiply out and had to become two. A plan
    quotes ONE model surcharge, so every surcharged minute is priced identically and
    splitting them would print two lines at the same unit price — which reads as two
    charges — while ALSO costing a paisa: `to_paise(a*r) + to_paise(b*r)` is not
    `to_paise((a+b)*r)`. One quantization, one line, and `qty x unit = amount` holds
    exactly. The models are still named, in the line's description.

    **`surcharge is None` is "this plan quotes no model surcharge", never "the surcharge is
    zero"** — the same reading `rate_value is None` has in `priced_overage`, and the same
    reason: a plan that gives the better model away is a decision, a plan nobody has asked
    is not. Both produce nothing to charge and no line, because a ₹0.00 line on an invoice
    invites a dispute about nothing; what differs is the RATE the panel publishes beside it.
    """
    if surcharge is None or surcharge <= 0:
        return PricedLlmSurcharge(minutes=_ZERO_PAISE, models=(), total_inr=_ZERO_PAISE)
    surcharged = {
        model: minutes
        for model, minutes in sorted(minutes_by_model.items())
        if model != UNSURCHARGED_MODEL and minutes > 0
    }
    minutes = sum(surcharged.values(), _ZERO_PAISE)
    return PricedLlmSurcharge(
        minutes=minutes,
        models=tuple(surcharged),
        total_inr=to_paise(minutes * surcharge),
    )


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
    `plans.overage_rate_second` is an open founder decision and is NULL everywhere. They
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
        billable_premium=minutes_by_rung[BASE_OVERAGE_RUNG],
        # Unattributed folds in with value: SURFACES §2b's rule is that a call we cannot
        # prove got the premium voice is never charged the premium rate.
        billable_value=minutes_by_rung[SECOND_OVERAGE_RUNG] + minutes_by_rung[UNATTRIBUTED_RUNG],
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
    #: What this call adds to the month's LANGUAGE-MODEL SURCHARGE (D-455). Zero on every
    #: plan that quotes none, and zero for a call the client did not choose the model of.
    #: A difference of two month totals like the other two, so it telescopes for the same
    #: reason and needs no separate rule for a month that straddles a model switch.
    llm_surcharge_inr: Decimal


async def month_increment(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    month: str,
    tier: str,
    llm_model_bucket: str,
    seconds: Decimal,
    included_min: Decimal,
    rate: Decimal,
    rate_value: Decimal | None,
    llm_surcharge: Decimal | None,
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

    `seconds` is this call's own `telephony_s` quantity, `tier` the rung it was metered on
    and `llm_model_bucket` the model bucket it was stamped into
    (`rates.llm_surcharge_applies` decides, and `UNSURCHARGED_MODEL` is the answer for a
    call the surcharge does not touch) — the three values the caller has just written to
    the ledger.

    **THE SURCHARGE IS THE SAME DIFFERENCE-OF-TWO-MONTHS ARITHMETIC** and deliberately not
    `this call's minutes x the rate`. It has to be: the month's minutes are PAISE-ALLOCATED
    across buckets (`allocate_paise` distributes a remainder over the whole set, so it is
    not linear in any one bucket), and a per-call product would drift from the figure the
    invoice prints by the accumulated remainder. Computed as a difference it telescopes to
    the month's own surcharge exactly — including across a month that straddles a model
    switch, where the ledger simply holds two buckets and this call moves one of them.
    """
    after = await rung_seconds(session, tenant_id=tenant_id, month=month)
    before_seconds = dict(after.by_rung)
    before_models = dict(after.by_llm_model)
    # `max(0, …)` cannot bind on the meter's path — the rows for `seconds` are in this
    # transaction and in this month, so they are in the sum we just read. It is kept
    # because a negative bucket would make `allocate_paise` refuse rather than answer,
    # and a caller that passed seconds the ledger does not hold should get the honest
    # "this call added nothing" instead of an exception on a metered call.
    before_seconds[tier] = max(Decimal("0"), before_seconds[tier] - seconds)
    before_models[llm_model_bucket] = max(
        Decimal("0"), before_models.get(llm_model_bucket, Decimal("0")) - seconds
    )
    after_minutes = rung_minutes(after.by_rung)
    before_minutes = rung_minutes(before_seconds)
    # Both partitions are re-allocated over the same "before" total, so the surcharge's
    # before-state is the month the previous call priced against — the property that makes
    # the increments telescope on this axis too.
    after_model_minutes = llm_model_minutes(after.by_llm_model)
    before_model_minutes = llm_model_minutes(before_models)
    after_overage = priced_overage(
        minutes_by_rung=after_minutes,
        included_min=included_min,
        rate=rate,
        rate_value=rate_value,
    )
    before_overage = priced_overage(
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
        overage_inr=after_overage.total_inr - before_overage.total_inr,
        llm_surcharge_inr=(
            priced_llm_surcharge(
                minutes_by_model=after_model_minutes, surcharge=llm_surcharge
            ).total_inr
            - priced_llm_surcharge(
                minutes_by_model=before_model_minutes, surcharge=llm_surcharge
            ).total_inr
        ),
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
    # ONE reading of the clock for the whole function, for `today`'s own reason: the trial
    # arm below asks whether this account is inside a funded period and how many days are
    # left, and two readings taken a query apart can straddle the end instant and publish
    # "active, 0 days left" beside charges that were computed as if it had ended.
    at = datetime.now(UTC)
    # WHICH INSTANT THIS MONTH IS PRICED AT, resolved (and the month validated) BEFORE
    # any query runs — a month we cannot parse is a month we cannot pick a plan for, and
    # a 422 up front beats a ₹0.00 statement for `?month=july`.
    priced_at = month_pricing_instant(period)
    # WHAT A MINUTE COST IN *THIS* MONTH, resolved at the same instant the plan is (D-492).
    #
    # This used to be `get_settings().self_serve_inr_per_min` read inside
    # `calling_revenue_inr` — the LIVE setting, on a statement for a month that closed and
    # was paid for out of the wallet at whatever the rate was THEN. A price change therefore
    # re-priced every past month on this panel: measured on this tree, 14.83 minutes
    # rendered ₹88.98 and then ₹133.47 after the rate moved 6 -> 9, against wallet debits
    # totalling ₹89.00 that had not moved and could not.
    #
    # The plan's terms were already resolved at `priced_at` for exactly this reason
    # (`billing/plans.py`), and the list price is the prepaid motion's equivalent of a plan
    # rate — the same fact about the same month, so it is asked at the same instant.
    list_rate = await self_serve_rate_at(session, at=priced_at)
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
    # WHERE THIS CLIENT'S COUNTING PERIOD BEGINS (D-536). None for every account that has
    # never been given a trial, which is the plain IST billing month this panel has always
    # shown. For an account on one — or one that just came off one — it is the trial
    # boundary, and every figure below is counted from there: "when the trial is lifted or
    # over or stopped the numbers should start from 0 again". Nothing is deleted to make
    # that true; the WINDOW moves, and `usage_events` keeps every row (hard rule 4).
    epoch = await counter_epoch(session, tenant_id=tenant_id)
    # WHICH VOICE SPOKE THIS MONTH'S MINUTES, AND WHAT THE WALLET WAS ACTUALLY CHARGED
    # (D-547) — out of the ledger's own lot splits, over the same window as the minutes.
    lot_charges = await voice_tier_usage(session, tenant_id=tenant_id, month=period, since=epoch)
    voices = lot_charges.by_voice
    totals = await _tier_totals(session, tenant_id=tenant_id, month=period, since=epoch)
    tier_minutes = totals.by_rung
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
            {"tid": tenant_id, **_month_bounds(period, since=epoch)},
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
                    f"{EFFECTIVE_CAP_MIN_SQL}, {EFFECTIVE_CAP_SPEND_SQL}, "
                    f"{OVERAGE_RATE_SECOND_SQL}, "
                    "llm_model_surcharge"
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
    # NULL is not zero: "this plan quotes no separate second rate" (bill everything at
    # `overage_rate`) and "the second rung is free" are different plans.
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

    # THE MODEL SURCHARGE (D-455), priced off the SAME read and the SAME plan row.
    #
    # NULL is not zero here either: "this plan quotes no model surcharge" and "the upgrade
    # is free" are different plans, and the rate published below says which of the two a
    # reader is in. It is deliberately NOT netted into `overage_cost_inr`: the overage is
    # minutes at the plan's rate and this is an upgrade on top of it, so they are two
    # lines on the statement and two figures on the panel — a client who switched model
    # must be able to see which of the two moved.
    surcharge_rate = Decimal(str(plan[6])) if plan and plan[6] is not None else None
    surcharge = priced_llm_surcharge(minutes_by_model=totals.by_llm_model, surcharge=surcharge_rate)

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
    # `plan_tier_of`, not a fourth hand-rolled `SELECT plan_tier`: `billing/ai_quota.py`
    # already describes that function as "the one reader of `organizations.plan_tier` —
    # the same one `usage_summary` and `charge_for_call` use", and it is also the function
    # that supplies the default, so a NULL column cannot read as one tier here and as
    # `managed` everywhere else.
    tier = await plan_tier_of(session, tenant_id)
    minutes_left: int | None = None
    # **THE CAP REMAINDER, AND NOTHING ELSE (D-547).** This field used to carry TWO
    # different quantities under one name: what remains of a managed plan's included
    # minutes, and — for a prepaid wallet — the balance divided by the live list rate.
    # One field with two meanings forced the browser to branch on `plan_tier` to know
    # which it had been sent, which is a decision the server had already made and thrown
    # away (`apps/web/.../billing/UsageTab.tsx`).
    #
    # The prepaid half is also no longer ANSWERABLE this way: since lots, a minute costs
    # what the lot it is spent from was sold at, so one balance over one live rate is the
    # wrong number for every client who bought at a rate the card no longer offers. The
    # honest prepaid runway is a PAIR, one figure per voice quality, summed lot by lot —
    # `billing/wallet.tier_minutes`, published by `GET /v1/billing/wallet/lots` and by the
    # credits screen. A prepaid account therefore gets `None` here, which is this field's
    # own long-standing word for "no answer", and the runway is read from the wallet.
    if plan and plan[3] is not None:
        minutes_left = max(0, int(Decimal(str(plan[3])) - minutes))

    # IS THIS CLIENT'S CALLING ON US RIGHT NOW (D-536)? Asked AFTER the runway above so
    # the trial's answer overrides it rather than being computed around it, and asked as a
    # fact about the account today rather than about the month on screen — the same reading
    # `capped` takes two paragraphs up, for the same reason: a client re-opening last
    # month's statement is being told what they owe, not what they owed.
    trial = await read_trial(session, tenant_id=tenant_id)
    trial_active = trial is not None and trial.is_active(at=at)
    if trial_active:
        # A trial bypasses the credit gate entirely (`compliance.service.credits_exhausted`),
        # so a wallet balance is not what limits this client's calling and quoting minutes
        # from it would be a number they cannot spend down. `None` is this field's own word
        # for "no answer" (a plan with no cap answers the same way), and the trial
        # block below says why —
        # publishing 0 would tell a client with a working service that it has stopped.
        minutes_left = None

    if capped:
        # `spend_state.capped` is the ONLY cap the gate enforces, and it refuses every
        # outbound call regardless of tier. Offering runway on top of that is a promise
        # the platform will not keep. (Inbound is unaffected by the cap — the gate is
        # outbound-only — but inbound is not something an owner "has minutes left" to
        # spend, so the outbound answer is the honest one for a planning number.)
        #
        # AFTER the trial arm above and not before it: a spend cap is a ceiling the CLIENT
        # or an operator set and it still binds during a trial (a trial is a billing state,
        # never a licence to ignore a ceiling somebody asked for), so when both are true the
        # cap is the honest answer.
        minutes_left = 0

    # WHAT THE CLIENT OWES, and during a trial it is ZERO — that is the whole feature.
    #
    # Because `epoch` moved the window to the trial's own start, every minute counted above
    # was spoken inside the funded period, so there is no apportionment to get wrong and no
    # partial month to explain. What the same minutes WOULD have cost is published beside it
    # as `trial_absorbed_inr` rather than discarded: the client sees what the service is
    # worth, and the figure a screen prints as "on us" is the same arithmetic the bill uses
    # rather than a second one. It is the CLIENT's price throughout — never `unit_cost_paid`,
    # which is ours and which no client panel has ever shown.
    #
    # WHICH OF THE TWO CALLING FIGURES THIS PERIOD TAKES, decided once here. A trial period
    # took NO wallet debit, so the lots hold nothing to read and the honest answer to "what
    # would this have cost" is the counterfactual (`absorbed_calling_inr`); every other
    # period is what the ledger charged (`calling_revenue_inr`, out of the lot splits).
    # The two are never both published: `month_charges_inr` below is ₹0.00 during a trial
    # and `trial_absorbed_inr` is ₹0.00 outside one. `counter_epoch` is what makes the
    # choice total rather than a per-call question — the window starts at the trial's start
    # while it runs and at its END once it is over, so every row inside it is on one side.
    calling = (
        absorbed_calling_inr(
            plan_tier=tier,
            minutes=minutes,
            overage_cost_inr=overage_cost,
            llm_surcharge_inr=surcharge.total_inr,
            self_serve_rate_inr_per_min=list_rate,
        )
        if trial_active
        else calling_revenue_inr(
            plan_tier=tier,
            prepaid_charged_inr=lot_charges.total_inr,
            overage_cost_inr=overage_cost,
            llm_surcharge_inr=surcharge.total_inr,
        )
    )
    charges = to_paise(
        month_charges_inr(
            monthly_fee_inr=(
                to_paise(Decimal(str(plan[0]))) if plan and plan[0] is not None else None
            ),
            calling_inr=calling,
        )
    )
    spend_used = to_paise(
        _spend_used(period, today, counters.billed_inr, closed_month_billed=calling)
    )
    second_rate_display = rate_to_display(value_rate) if value_rate is not None else None

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
        "overage_minutes_base_rung": overage_premium,
        "overage_minutes_second_rung": overage_value,
        # ⚠ DEPRECATED, STEP 1 OF TWO (hard rule 8, D-558). The two names above replace
        # these: `premium`/`value` claimed a voice quality that never chose the rung.
        # BOTH are emitted and carry the SAME figures, so nothing reading the wire
        # breaks; STEP 2 deletes the pair below and the console's fallback with it.
        "overage_minutes_premium": overage_premium,
        "overage_minutes_value": overage_value,
        "overage_cost_inr": overage_cost,
        # The rate the overage was priced at, published so the invoice does not have to
        # re-read `plans` and risk picking a different row than this computation did.
        "overage_rate_inr": rate_to_display(overage_rate),
        # None when this plan quotes no separate second rate — in which case BOTH rungs
        # above were priced at `overage_rate_inr`, and saying None rather than repeating
        # the base rate is what tells a reader which of those two worlds they are in.
        # Bound once above and published twice, for the reason `tier_usage` gives: two
        # spellings of one rate must not be two evaluations of it.
        "overage_rate_second_inr": second_rate_display,
        # ⚠ DEPRECATED, STEP 1 OF TWO — the name `overage_rate_second_inr` replaces.
        "overage_rate_value_inr": second_rate_display,
        # THE MODEL SURCHARGE, as three figures a client can check against each other
        # (D-455): the minutes that carried it, the rate they carried, and the total —
        # which is `minutes x rate` because `priced_llm_surcharge` quantized it once.
        #
        # `llm_surcharge_rate_inr` is None exactly when the plan quotes no surcharge, and
        # a ₹0.00 total then means "your model choice costs you nothing" rather than "you
        # ran no upgraded minutes" — the same None-is-not-zero reading as the value rate
        # above, on the column beside it. Published UNROUNDED through `rate_to_display`
        # for that function's reason: the invoice re-prices from this figure.
        "llm_surcharge_rate_inr": (
            rate_to_display(surcharge_rate) if surcharge_rate is not None else None
        ),
        "llm_surcharge_minutes": surcharge.minutes,
        "llm_surcharge_inr": surcharge.total_inr,
        # WHICH MODELS. The identifiers the client themselves chose, sorted, so the
        # statement and the panel can name the cause of the number rather than only its
        # size. Empty on every plan that quotes no surcharge and on every month nobody
        # upgraded.
        "llm_surcharge_models": list(surcharge.models),
        # Quantized to paise like every other money field: NUMERIC(12,4) is the
        # storage precision, two decimals is what a rupee amount means to a reader.
        "monthly_fee_inr": (
            to_paise(Decimal(str(plan[0]))) if plan and plan[0] is not None else None
        ),
        # THE TOTAL, so no screen has to add rupees in a browser. `month_charges_inr` is
        # the same expression `margin_for_tenant` books as revenue, quantized to paise here
        # because that is what a rupee amount means to the client reading it.
        #
        # It is deliberately NOT `spend_used_inr`, and confusing the two is the reason this
        # comment is long. `spend_used_inr` is what has been METERED — the live counter on
        # an open month, the ledger on a closed one — so on an open month it lags the
        # retainer entirely and answers "what have my calls drawn down". This answers "what
        # will this month cost me", retainer included, from the same three published
        # components a client can add up by hand.
        "month_charges_inr": _ZERO_PAISE if trial_active else charges,
        "cap_minutes": int(plan[3]) if plan and plan[3] is not None else None,
        "minutes_left": minutes_left,
        "capped": capped,
        # THE CLIENT'S OWN SPEND, in the client's own currency (P1.3). See `_spend_used`
        # for what each branch reads and why neither of them is `spend_used` any more.
        "spend_used_inr": _ZERO_PAISE if trial_active else spend_used,
        # IS THIS PERIOD ON US, AND UNTIL WHEN (D-536). Always present, `active: False` for
        # every account that has never had a trial — a key that appears and disappears is a
        # key a screen forgets to handle, and this one decides whether the two figures above
        # mean "you owe nothing" or "you have spent nothing".
        "trial": {
            "active": trial_active,
            "days_remaining": trial.days_remaining(at=at) if trial is not None else None,
            "ends_at": trial.ends_at if trial_active and trial is not None else None,
        },
        # WHAT WE ABSORBED for this client this period, at the CLIENT's own price. Zero
        # whenever no trial is running, so a screen can print it unconditionally. Never our
        # supplier cost: `unit_cost_paid` is commercially ours and the client panel has
        # never shown it (`trials.trial_cost_to_us_inr` is where an OPERATOR reads that).
        "trial_absorbed_inr": charges if trial_active else _ZERO_PAISE,
        # WHAT EACH VOICE COST THIS MONTH (D-547), from the ledger's own lot splits.
        #
        # With two voices at two prices, "how much of this month was the dearer voice" is
        # the question a client actually asks of a bill that moved, and nothing on this
        # panel could answer it. (It is also what the usage screen's legacy "reduced rate"
        # pair — NULL on every plan — is meant to be replaced BY, plan §5.F1; that web
        # change is another lane's and the fields above are untouched here.) The MINUTES
        # add to `minutes_used`
        # (every debited call is one voice or the other) and the CHARGES are the rupees
        # actually taken off the wallet, not minutes re-multiplied by a rate — which is the
        # whole reason `meta.lots` records them.
        #
        # THE FIELD NAMES ARE THE VENDOR'S AND THE LABELS ARE THE CLIENT'S, deliberately.
        # `sarvam_*` is what an auditor reconciles against a Sarvam invoice; "Clear" is
        # what a client reads, and no client-facing surface names a vendor as a product
        # tier (founder, 7 Sep 2026). The label is SENT rather than kept in the browser for
        # the reason every money figure here is: a second copy in TypeScript is how the two
        # drift and a client meets both names.
        "sarvam_minutes": to_paise(voices["sarvam"].minutes),
        "sarvam_charges_inr": to_paise(voices["sarvam"].charged_inr),
        "sarvam_label": VOICE_TIER_LABELS["sarvam"],
        "cartesia_minutes": to_paise(voices["cartesia"].minutes),
        "cartesia_charges_inr": to_paise(voices["cartesia"].charged_inr),
        "cartesia_label": VOICE_TIER_LABELS["cartesia"],
    }


def month_charges_inr(*, monthly_fee_inr: Decimal | None, calling_inr: Decimal) -> Decimal:
    """EVERYTHING THIS BILLING PERIOD HAS COST THE CLIENT — the retainer plus the calling.

    **THE ADDITION HAS TO HAPPEN SOMEWHERE, AND THE BROWSER IS THE ONE PLACE IT MUST NOT.**
    `UsagePanelOut` published three charge components and no total, so both client screens
    that show "this month so far" had to add rupees in JavaScript. `apps/web/src/lib/money
    .ts` did it correctly — whole paise, never `Number()` on a rupee string — and said in
    its own docstring that a field on the endpoint was the better shape and that it could
    not add one. This is that field's arithmetic. A total computed in the browser is a
    second implementation of a bill, in a language with one numeric type, on the screen a
    client checks against their own books.

    **IT IS THE SAME EXPRESSION `margin_for_tenant` CALLS REVENUE, AND THAT IS THE POINT
    RATHER THAN A COINCIDENCE.** What the client owes us and what we book as revenue for
    the period are the same number seen from two sides; they were computed by two
    expressions in two modules, which is how they come to disagree. There is now one, and
    both surfaces read it.

    **RETURNS UNQUANTIZED `Decimal`, and the two callers quantize differently ON PURPOSE.**
    `usage_summary` publishes `to_paise(...)` because a rupee amount on a screen means two
    decimals; `margin_for_tenant` keeps the raw value because it subtracts a cost from it
    first and `margin_pct` divides by it — rounding before either would round twice.
    Returning a pre-quantized figure here is the defect `calling_revenue_inr` documents at
    length one function down, on the same path.

    **`calling_inr` IS RESOLVED BY THE CALLER, AND THAT IS DELIBERATE.** This function used
    to take the plan tier, the minutes and a list rate and call `calling_revenue_inr`
    itself. Since D-547 there are two answers to "what did this period's calling come to" —
    what the lots were actually charged (`calling_revenue_inr`) and, for a period that was
    on us, what it WOULD have come to (`absorbed_calling_inr`) — and the caller is the only
    one holding the fact that decides between them. Pushing that decision in here would
    mean a `trial_active` flag on a money function, which is how a screen ends up publishing
    the wrong one of two numbers that look alike.

    `monthly_fee_inr` is `None` — not zero — while a client is mid-onboarding with no plan
    row, which is a real state; it contributes nothing and the total is then the calling
    alone. A prepaid tenant has no retainer either, and its calling half is priced at the
    list price rather than out of an allowance: `calling_revenue_inr` already holds that
    branch and is not re-decided here.
    """
    return (monthly_fee_inr or Decimal("0")) + calling_inr


#: A MONTH'S TALK TIME AND CHARGES, SPLIT BY THE VOICE THAT SPOKE (D-547, plan §4.D.4).
#:
#: **READ OUT OF `meta.lots`, WHICH IS THE POINT OF `meta.lots`.** Invariant §2.3.5 says a
#: month's statement and the margin panel are re-derivable from the `usage` rows alone, and
#: this is the reader that proves it: every split carries the minutes it bought, the rate it
#: bought them at and the voice they were spoken in, so the per-voice figures are the SAME
#: numbers the wallet was debited rather than a second derivation from minutes x a rate.
#: There is no third place a per-voice charge could come from — `usage_events` records our
#: COST and knows nothing about what a lot was sold at.
#:
#: `kind = 'call'` filters out the `ai_assist` splits (a dashboard-AI block, and the D-455
#: model surcharge that rides a call's own row): they buy rupees, not minutes, and adding
#: their credits to a voice's charges would say a client spoke minutes they did not.
#:
#: ⚠ **IT IS BELT-AND-BRACES TODAY AND IS KEPT DELIBERATELY.** Measured by deleting it: the
#: answer does not move, because an `ai_assist` split carries no `voice_tier` key at all
#: (ADDENDUM 2 §2.1), so `split->>'voice_tier'` is NULL, the row groups under a tier this
#: function does not publish, and its credits are dropped by the comprehension below. So
#: the discriminator is doing the work and this clause proves nothing a test can see. It
#: stays because the two guards are not the same statement: the absent key says "this split
#: has no voice", and this says "this READER wants call splits only" — and the day a third
#: kind is added that DOES carry a voice (a per-minute add-on, say), the absent-key guard
#: silently stops holding and this one does not.
#: WHICH MONTH A WALLET DEBIT BELONGS TO, and it is NOT the month the row was written in.
#:
#: `record_entry` stamps `occurred_at = clock_timestamp()` — the moment of the INSERT — and
#: for a LATE-SETTLING call that is a different month from the one the call was spoken in:
#: the reconciliation poller's window straddling midnight IST on the 1st, an ARQ retry
#: ladder crossing it, a vendor that takes minutes to price a call (D-492's own list). So a
#: reader windowing these rows on their own `occurred_at` reports a closed month's calling
#: as ₹0.00 while `usage_events` — stamped with the call's `ended_at` — correctly reports
#: its minutes. Measured: 14.83 minutes beside ₹0.00 charged.
#:
#: The call's own instant is therefore what the window binds, taken from the usage rows the
#: SAME call wrote, which is the same column and the same table the minutes beside it are
#: counted from — so the two cannot describe different months. `spend_state` attributes by
#: `ist_billing_month(ended_at)` and this is that rule, applied to the ledger.
#:
#: `u.call_id::text = e.ref` rather than `e.ref::uuid`: a `usage` row's ref is a call id
#: today, but a dashboard-AI debit's is not a UUID at all, and casting the COLUMN would
#: fail the whole statement on one such row rather than simply not matching it.
#:
#: `e.occurred_at >= :month_from` is a floor and not the window: a debit is written when the
#: call is metered, which is never BEFORE the call, so it bounds the scan without excluding
#: anything the EXISTS would have kept.
_CALL_IN_MONTH = (
    "e.occurred_at >= :month_from AND EXISTS ("
    "SELECT 1 FROM usage_events u WHERE u.tenant_id = e.tenant_id AND u.call_id::text = e.ref "
    "AND u.occurred_at >= :month_from AND u.occurred_at < :month_to)"
)

_VOICE_SPLIT_SQL: Final = (
    "SELECT split->>'voice_tier' AS tier, "
    "COALESCE(SUM((split->>'minutes')::numeric), 0) AS minutes, "
    "COALESCE(SUM((split->>'credits')::numeric), 0) AS charged "
    "FROM credit_ledger e, LATERAL jsonb_array_elements(e.meta->'lots') AS split "
    f"WHERE e.tenant_id = :tid AND e.reason = 'usage' AND {_CALL_IN_MONTH} "
    "AND split->>'kind' = 'call' GROUP BY 1"
)

#: THE MONEY TAKEN OFF THE WALLET FOR CALLING THAT IS NOT MINUTES — today only the D-455
#: model surcharge, which rides a call's own `usage` row as an `ai_assist` split
#: (`charge_for_call`).
#:
#: **THE `EXISTS` IS WHAT MAKES THIS "CALLING" RATHER THAN "EVERYTHING".** A dashboard-AI
#: block is an `ai_assist` split too, on a row of its own with no call splits on it; adding
#: those rupees to a month's CALLING charge would bill a client for the copilot under the
#: heading of their phone calls, which is neither what the panel says nor what
#: `calling_revenue_inr` has ever meant. So the predicate is on the ROW: only rows that also
#: carry a `call` split. A row that carries both is a call and its upgrade, which is exactly
#: the pair this figure is the second half of.
_CALL_EXTRA_SPLIT_SQL: Final = (
    "SELECT COALESCE(SUM((split->>'credits')::numeric), 0) AS charged "
    "FROM credit_ledger e, LATERAL jsonb_array_elements(e.meta->'lots') AS split "
    f"WHERE e.tenant_id = :tid AND e.reason = 'usage' AND {_CALL_IN_MONTH} "
    "AND split->>'kind' = 'ai_assist' "
    "AND EXISTS (SELECT 1 FROM jsonb_array_elements(e.meta->'lots') AS c "
    "            WHERE c->>'kind' = 'call')"
)


@dataclass(frozen=True, slots=True)
class VoiceUsage:
    """One voice tier's share of a month: minutes spoken, and what the client paid."""

    minutes: Decimal
    charged_inr: Decimal


@dataclass(frozen=True, slots=True)
class LotCharges:
    """WHAT A MONTH'S CALLING ACTUALLY TOOK OFF A PREPAID WALLET, out of `meta.lots`.

    `by_voice` is the per-tier split the client's panel publishes; `extra_inr` is the money
    on those same rows that bought no minutes (the D-455 model surcharge). `total_inr` is
    the sum, and it is the number that IS the prepaid motion's calling revenue — see
    `calling_revenue_inr`.
    """

    by_voice: Mapping[str, VoiceUsage]
    extra_inr: Decimal

    @property
    def total_inr(self) -> Decimal:
        """Every rupee of calling this month, whatever split kind carried it."""
        return sum((voice.charged_inr for voice in self.by_voice.values()), self.extra_inr)


async def voice_tier_usage(
    session: AsyncSession, *, tenant_id: UUID, month: str, since: datetime | None = None
) -> LotCharges:
    """This month's minutes and charges from the ledger's own lot splits (D-547).

    Both tiers are always present in `by_voice`, at zero where nothing was spoken, because
    a panel that omitted the tier a client did not use would make "we never used Studio"
    and "the field did not load" the same screen.

    A MANAGED tenant reads zero throughout: they are invoiced against a retainer and their
    calls take no wallet debit at all, so there are no splits to read. That is the same
    answer `credit_balance_inr` gives them and for the same reason — it is not a gap.

    `since` is the caller's counting epoch (`trials.counter_epoch`), passed for the reason
    every other figure on the usage panel takes it: the trial boundary moves the window,
    and charges read over a wider window than the minutes printed beside them would not
    describe one period.
    """
    binds = {"tid": tenant_id, **_month_bounds(month, since=since)}
    rows = (await session.execute(text(_VOICE_SPLIT_SQL), binds)).all()
    found = {
        str(row[0]): VoiceUsage(
            minutes=Decimal(str(row[1] or 0)), charged_inr=Decimal(str(row[2] or 0))
        )
        for row in rows
    }
    extra = (await session.execute(text(_CALL_EXTRA_SPLIT_SQL), binds)).scalar_one()
    return LotCharges(
        by_voice={
            tier: found.get(tier, VoiceUsage(minutes=Decimal("0"), charged_inr=Decimal("0")))
            for tier in VOICE_TIER_LABELS
        },
        extra_inr=Decimal(str(extra or 0)),
    )


def calling_revenue_inr(
    *,
    plan_tier: str | None,
    prepaid_charged_inr: Decimal,
    overage_cost_inr: Decimal,
    llm_surcharge_inr: Decimal,
) -> Decimal:
    """What the CLIENT owes for a whole billing period's CALLING, at their own rate.

    **THE MODEL SURCHARGE IS ADDED ON BOTH MOTIONS (D-455)**, which is why it is one
    argument rather than a branch: "a dearer model adds ₹x to every minute the client
    chose it for" is one rule, and the two motions differ only in what the BASE minute
    costs. Passed in already priced rather than recomputed here, for the reason the
    overage is: `usage_summary` derived it from `priced_llm_surcharge`, and `build_invoice`
    prints its upgrade line from those same published figures — a second derivation here
    is what would let a panel and a statement disagree.

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

    **THE PREPAID ANSWER IS THE LEDGER'S, AND THAT IS THE MONEY FIX (D-547).** This
    branch used to be `self_serve_rate_inr_per_min x minutes + llm_surcharge_inr` — one
    list rate times a month's minutes — and since lots that is the wrong number for every
    client who did not buy the smallest pack. A wallet is a QUEUE of lots, each frozen at
    the two rates its own purchase was sold at, and a call is charged by walking them
    (`lots.consume`); the row that records it carries the splits in `meta.lots`, and
    `SUM(meta.lots[].credits)` IS that row's delta by construction (invariant §2.3.5). So
    the money the client owes for calling is a SUM, not a product, and re-deriving it from
    a rate could not agree with the ledger for:

    * any client on a pack rung below the card's first — a ₹15,000 purchase is ₹4.70 a
      Sarvam minute against a list price of ₹5.00, reported 6.4% high;
    * ANY Studio minute at all, at ₹8.00 against the same ₹5.00, reported 37.5% low;
    * a wallet holding two lots at two prices, where no single rate is right.

    Measured on this tree, the same screen showed both: `UsageTab` renders the per-voice
    charges out of `meta.lots` beside a `month_charges_inr` derived from list x minutes,
    and they disagreed on every non-starter wallet — and the same closed month CHANGED
    VALUE at IST rollover, because the open month read the live counter (which the meter
    fed from the lots) and the closed one re-derived. The margin panel overstated revenue
    by the same gap, and `attribution`'s residual was measured against a total the ledger
    had never charged.

    `prepaid_charged_inr` is therefore READ, by `voice_tier_usage`, from the very rows the
    wallet was debited on. It is a required argument rather than one with a default for the
    reason the list rate was: a default is how the re-derivation gets back in, silently, at
    whichever call site forgets.

    **WHAT ABOUT A PERIOD ON US?** A trial takes no debit, so there are no splits and this
    correctly answers ₹0.00 — which is exactly what a client on a trial owes.
    `absorbed_calling_inr` is what prices the counterfactual, and it is a separate function
    so that neither answer can be mistaken for the other.

    **A MANAGED tenant's answer is the overage the caller already priced**, passed in
    rather than recomputed, because `usage_summary` derived it from `overage_rungs` — the
    same function `build_invoice` prints its lines from. Re-deriving it here would be the
    second computation that lets a panel and a statement disagree.

    The retainer is deliberately NOT included: it is published as its own figure on both
    surfaces, and adding it here would double it wherever both are shown.

    **THE MEASURED RESIDUAL D-254 RECORDED IS CLOSED ON THIS BRANCH, and the founder
    decision it was waiting on is no longer needed to close it.** The old text below stands
    as the record of what was wrong. This figure and the money taken off the wallet used to
    be two arithmetics — the wallet debited per call at `to_paise`-scale-4 of
    `rate x (seconds / 60)` (`rates.prepaid_billed_inr`), this one `rate x the month's
    PUBLISHED minute count` — and the gap was systematic, bounded by half a paisa of
    minutes times the rate. Measured on this tree, ten calls of 7/7/7/13/41/59/101/137/211/307
    seconds at ₹6.00 debited ₹89.0000 off the wallet while this function answered ₹88.98
    (14.83 min x ₹6.00). It is now literally the ledger's own sum, so the two cannot differ
    at all — and `docs/evidence/deepdive-money.md` N-2 ("is a prepaid statement a receipt
    for top-ups, a statement of consumption, or both") is answered in the direction the
    wallet already implemented: the WALLET is the statement. What a client multiplies out
    by hand on the panel is the per-voice pair published beside the total, each at its own
    lot rate, which is the arithmetic they can actually check.
    """
    if plan_tier in PREPAID_TIERS:
        return prepaid_charged_inr
    return overage_cost_inr + llm_surcharge_inr


def absorbed_calling_inr(
    *,
    plan_tier: str | None,
    minutes: Decimal,
    overage_cost_inr: Decimal,
    llm_surcharge_inr: Decimal,
    self_serve_rate_inr_per_min: Decimal,
) -> Decimal:
    """WHAT A PERIOD ON US *WOULD* HAVE COST — the counterfactual, and only that (D-536).

    A trial takes NO wallet debit at all (`workers/pipeline`: `charged_inr` stays ₹0.00
    when `trial_covers` is true), so there are no lot splits to read and
    `calling_revenue_inr` correctly answers ₹0.00. `trial_absorbed_inr` is a different
    question — "what is the service we are giving you worth" — and it has to be priced,
    which is why it is a second function rather than a flag on the first. Two names for two
    quantities: one is what the ledger took, the other is what it deliberately did not.

    **THE ARITHMETIC IS THE PIPELINE'S OWN.** The meter accrues exactly
    `prepaid_billed_inr(minutes, list_rate) + surcharge` into `spend_state.billed_inr` for a
    call that was on us, so this is the same rule stated once more at period scale rather
    than a second estimate of the same thing.

    A MANAGED tenant on a trial is absorbed at the overage its plan would have charged,
    which is `calling_revenue_inr`'s managed branch unchanged — there is no wallet in that
    motion and nothing about it is counterfactual except that it is not invoiced.
    """
    if plan_tier in PREPAID_TIERS:
        return self_serve_rate_inr_per_min * minutes + llm_surcharge_inr
    return overage_cost_inr + llm_surcharge_inr


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


# --- the overage rungs (SURFACES §2b) ------------------------------------------
#
# `usage_events.meta.tts_tier` is stamped by the post-call pipeline with the plan's base
# overage rung (there is one voice quality now — the single-tier voice decision — so it is
# a single constant, not a per-voice choice). Everything below reads that one field, so the
# client panel and the margin panel cannot end up telling two different stories about the
# same call.


async def tier_usage(
    session: AsyncSession, *, tenant_id: UUID, month: str | None = None
) -> dict[str, Any]:
    """Minutes and OUR cost, split by the TTS rung each call was metered on.

    Three buckets, not two, and the third is the honest one: rows written before rung
    attribution existed — or by a path that could not attribute one — carry no rung at
    all. They are reported as `unattributed` rather than folded silently into a rung,
    because "we know which rung this ran on" and "we never knew" are different facts.

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
    totals = await _tier_totals(session, tenant_id=tenant_id, month=period)
    minutes, cost = totals.by_rung, totals.cost_by_rung

    # THE THREE COSTS ARE ALLOCATED, NOT ROUNDED SEPARATELY (D-371) — the same fix the
    # MINUTES beside them already had, on the column nobody had applied it to.
    #
    # `GET /v1/admin/tenants/{id}/margin` nests these under the margin card's `cost_inr`
    # and its docstring promises they "add up to `cost_inr` exactly — they are a
    # partition of it, not a parallel estimate". `to_paise` on each bucket does not keep
    # that promise: `unit_cost_paid` is NUMERIC(12,4) and `qty` NUMERIC(14,4), so a
    # bucket's sum of products routinely carries four decimals. Measured on two calls of
    # 601 s and 401 s at ₹0.0125/s — ₹7.5125 and ₹5.0125 — the rungs published ₹7.51 and
    # ₹5.01, adding to ₹12.52 beside a `cost_inr` of ₹12.53. `allocate_paise` is the one
    # function in this module for exactly this (largest remainder), and passing it
    # `cost_inr`'s own figure — `to_paise` of the same sum `margin_for_tenant` takes — is
    # what makes the partition true by construction rather than by two roundings
    # happening to agree.
    cost_base, cost_second, cost_unattributed = allocate_paise(
        [cost[BASE_OVERAGE_RUNG], cost[SECOND_OVERAGE_RUNG], cost[UNATTRIBUTED_RUNG]],
        to_paise(sum(cost.values(), Decimal("0"))),
    )
    # Bound once and published twice below, under the new name and the one it deprecates.
    # Spelling the arithmetic twice is how a two-step deprecation ends up publishing two
    # different answers to one question — which is worse than the name it set out to fix.
    minutes_base = minutes[BASE_OVERAGE_RUNG]
    minutes_second = minutes[SECOND_OVERAGE_RUNG]
    minutes_billable_second = minutes[SECOND_OVERAGE_RUNG] + minutes[UNATTRIBUTED_RUNG]

    return {
        "month": period,
        "minutes_base_rung": minutes_base,
        "minutes_second_rung": minutes_second,
        "minutes_unattributed": minutes[UNATTRIBUTED_RUNG],
        # What a bill may charge at each rung: unproven never reaches the dearer side.
        "minutes_billable_base_rung": minutes_base,
        "minutes_billable_second_rung": minutes_billable_second,
        "cost_base_rung_inr": cost_base,
        "cost_second_rung_inr": cost_second,
        "cost_unattributed_inr": cost_unattributed,
        # ⚠ DEPRECATED, STEP 1 OF TWO (hard rule 8, D-558). The SAME six figures under the
        # names that claimed a voice quality — same bindings, so the pair cannot disagree.
        # STEP 2 deletes these six.
        "minutes_premium": minutes_base,
        "minutes_value": minutes_second,
        "minutes_billable_premium": minutes_base,
        "minutes_billable_value": minutes_billable_second,
        "cost_premium_inr": cost_base,
        "cost_value_inr": cost_second,
    }


def margin_pct(*, margin_inr: Decimal, revenue_inr: Decimal) -> Decimal | None:
    """Margin as a percentage of revenue, or None when there is no revenue to be a
    percentage OF.

    **None rather than 0.0, because "0% margin" and "nothing billed yet" are different
    facts and an operator acts differently on each.** That rule lived inline in
    `margin_for_tenant` and was copied into the fleet board the day a second surface
    needed it — two spellings of one judgement, which is the D-103 shape this module has
    already paid for. It is a function now so both read it, and so the no-revenue arm is
    provable without arranging a whole fleet that has billed nothing.

    One decimal place, `ROUNDING` passed explicitly like every other quantize here: the
    ambient `decimal` context is process-global and mutable by anything in the image.
    """
    if revenue_inr <= 0:
        return None
    return (margin_inr / revenue_inr * 100).quantize(Decimal("0.1"), rounding=ROUNDING)


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
    totals = await _tier_totals(session, tenant_id=tenant_id, month=str(usage["month"]))
    cost_inr = to_paise(sum(totals.cost_by_rung.values(), Decimal("0")))
    # REVENUE IS THE CLIENT'S PRICE FOR THIS PERIOD, AND WHICH PRICE THAT IS DEPENDS ON
    # THE MOTION. `monthly_fee + overage_cost` is the managed tenant's bill (it is the
    # invoice's subtotal) and it is ₹0.00 for a prepaid one, whose minutes are charged at
    # the list price and taken out of the wallet — so this panel reported the whole
    # self-serve motion as a pure loss until `calling_revenue_inr` existed. The retainer
    # stays here because a prepaid tenant has none; the CALLING half is the part that
    # differs, and it has one home now.
    tier = await plan_tier_of(session, tenant_id)
    # THROUGH `month_charges_inr`, which is also what the client's own panel publishes as
    # `month_charges_inr`. Revenue and "what the client owes" are the same number seen from
    # two sides, and they used to be two expressions in two modules. The model surcharge is
    # REVENUE and belongs on this side of the margin — it is also the only revenue here that
    # moves with our own cost, since a client on the dearer model raises `cost_inr` through
    # an Azure invoice we cannot see per tenant, so it is what keeps the two moving together
    # at all (D-455). Left UNQUANTIZED: the subtraction and `margin_pct`'s division both
    # happen before anything is rounded.
    revenue = month_charges_inr(
        monthly_fee_inr=usage["monthly_fee_inr"],
        # WHAT THE PREPAID WALLET WAS ACTUALLY CHARGED (D-547), read from the same lot
        # splits `usage_summary` published the per-voice figures from, over the same
        # counting window. Re-read here rather than threaded out through that function's
        # dict because the dict is the CLIENT's panel (`UsagePanelOut`) and this is not a
        # field of it — `month` and `counter_epoch` are what make the two reads agree.
        #
        # A period ON US contributes ₹0.00 revenue and that is the honest figure: nothing
        # was charged. The cost side is unchanged, so a trial shows as the loss it is,
        # which is what `trials.trial_cost_to_us_inr` exists to size.
        calling_inr=calling_revenue_inr(
            plan_tier=tier,
            prepaid_charged_inr=(
                await voice_tier_usage(session, tenant_id=tenant_id, month=str(usage["month"]))
            ).total_inr,
            overage_cost_inr=usage["overage_cost_inr"],
            llm_surcharge_inr=usage["llm_surcharge_inr"],
        ),
    )
    margin = to_paise(revenue - cost_inr)
    pct = margin_pct(margin_inr=margin, revenue_inr=revenue)
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
    "BASE_OVERAGE_RUNG",
    "GRANT_META_KIND",
    "GRANT_REF_PREFIX",
    "INBOUND_CUTOVER_JOB",
    "LOT_REPRICE_META_KIND",
    "LOT_REPRICE_REF_PREFIX",
    "LOW_BALANCE_INR",
    "LOW_BALANCE_JOB",
    "MAX_GRANT_INR",
    "MIN_GRANT_INR",
    "PAISE",
    "PAYMENT_REF_SQL",
    "RESTATEMENT_META_KIND",
    "RESTATEMENT_REF_PREFIX",
    "ROUNDING",
    "UNSURCHARGED_MODEL",
    "WALLET_LEVEL_EMPTY",
    "WALLET_LEVEL_LOW",
    "Balance",
    "CorrectableEntry",
    "CreditReason",
    "CreditRemoval",
    "CreditTotals",
    "CreditedLot",
    "EntryLot",
    "LedgerEntryRef",
    "LotCharges",
    "LotDebit",
    "LotRates",
    "MonthSeconds",
    "MonthTotals",
    "OverageRung",
    "PricedLlmSurcharge",
    "RateCard",
    "RecordedPayment",
    "RepricedLot",
    "VoiceUsage",
    "absorbed_calling_inr",
    "adjustment_ref",
    "allocate_paise",
    "apply_credit_to_lots",
    "calling_revenue_inr",
    "charge_for_call",
    "credit_totals",
    "crossed_downwards",
    "crossed_zero",
    "current_billing_month",
    "find_entry_by_ref",
    "find_topup",
    "get_balance",
    "grant_ref",
    "llm_model_minutes",
    "lock_tenant_credits",
    "lot_of_entry",
    "lot_reprice_ref",
    "margin_for_tenant",
    "margin_pct",
    "month_charges_inr",
    "overage_rungs",
    "plan_tier_of",
    "priced_llm_surcharge",
    "rate_card_at",
    "rate_to_display",
    "read_correctable_entry",
    "read_recorded_payment",
    "record_entry",
    "record_usage_from_lots",
    "recorded_payments",
    "remove_credit_from_lots",
    "reprice_lot",
    "restatement_ref",
    "reversed_amounts",
    "split_overage",
    "tier_usage",
    "to_paise",
    "usage_summary",
    "voice_tier_usage",
]
