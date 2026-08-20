"""Restate calls metered under a superseded cost-UNIT assumption — by APPENDING (D-411).

WHY THIS EXISTS AT ALL. `engine/bolna.py` turns the vendor's cost figure into rupees using
two things nothing first-party states outright: which CURRENCY the number is in, and how
many of its units make one major unit (`_MINOR_UNITS_PER_MAJOR`). Both are marked
assumptions, gate 7 (OPERATIONS §2) is where they stop being assumptions, and the adapter
now REFUSES a currency whose unit it has no evidence for rather than dividing it by
another currency's. What refusing does not do is reach backwards: rows written before the
divisor was corrected are still in the ledger, still wrong, and `usage_events` is
INSERT-only (hard rule 4) — a database trigger enforces it and that is not an obstacle to
route around. The rows ARE the evidence of what we believed when we metered them.

So the repair is the one every mistake on an append-only ledger gets here: ONE compensating
row per affected call, carrying the difference. That is the same instrument
`billing.service.record_tier_correction` uses for a call metered on the wrong TTS rung,
deliberately and down to the column values — `unit_type = 'other'`, `qty = 1`,
`unit_cost_paid` = the delta, stamped at the ORIGINAL call's `occurred_at` — because a
second shape of correction row would mean every reader of this ledger had to learn two.

    what moved:  OUR COST, and only our cost.

The client's bill does not move and must not. `usage_summary` prices a month off MINUTES
at the plan's own rate; `unit_cost_paid` is what the engine charged US, and it feeds
`margin_for_tenant` and `_tier_totals`' cost side. A wrong divisor therefore mis-stated
our margin and our spend caps, never an invoice — and a correction that touched the
invoice would be inventing a client-facing error that never happened (the D-373 mistake,
one function over).

WHY IT IS A SEPARATE MODULE FROM `record_tier_correction` RATHER THAN AN ARGUMENT TO IT.
The two share a shape and share nothing else: a tier correction is priced from OUR rate
card (`rates.tier_correction_inr`) against a character count a human supplies, and a
restatement is priced from the ledger's own rows against a divisor the vendor's invoice
settles. Folding them together would put a `chars`/`divisor` either-or inside a money
function that four callers already depend on.

Driven by `scripts/correct_cost_unit.py`, which is READ-ONLY by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import MONEY_Q, ROUNDING

# `_ROW_COST_SQL` is IMPORTED AND NOT RESPELLED, private name and all. "What one usage row
# contributes to our cost" has exactly one definition in this repo (D-370: a zero-`qty` row
# carries its whole leg cost), and a restatement computed against a second spelling of it
# would compensate a number no reader of the ledger ever sees. `billing/service.py` says
# the same thing about itself: "two readers of one money fact is the D-103 shape this
# module has already paid for twice."
from apps.api.billing.service import _ROW_COST_SQL, lock_tenant_credits
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7

log = get_logger("calevate.billing.cost_unit")

#: `meta.kind` on every row this module writes. A CONSTANT because the dedupe below and
#: any future reader must agree on it exactly, and because it must never collide with
#: `TIER_CORRECTION_META_KIND` — `_CORRECTED_TIER_SQL` re-attributes a whole call's minutes
#: when it sees that one, and a restatement asserts nothing about which voice ran.
COST_UNIT_CORRECTION_META_KIND = "cost_unit_restatement"

#: WHICH ROWS WERE PRICED BY THE ADAPTER'S DIVISOR. `pipeline._meter` stamps
#: `meta.source_currency` on every row it writes from a `CostBreakdown`, and the divisor is
#: a function of that currency (`bolna._MINOR_UNITS_PER_MAJOR`), so the currency is enough
#: to identify the population without a second column on a ledger that cannot be altered.
#:
#: IT IS ALSO WHY A CORRECTION ROW MUST NOT CARRY THIS KEY. The rows this module writes
#: stamp `corrected_source_currency` instead: spelled `source_currency`, a second run would
#: read its own output back as more mis-metered cost and compound the restatement.
_SOURCE_CURRENCY_KEY = "source_currency"


@dataclass(frozen=True, slots=True)
class MisMeteredCall:
    """One call's ledger rows as a restatement target."""

    call_id: UUID
    #: What those rows currently contribute to our cost — `SUM(qty * unit_cost_paid)` by
    #: the ledger's own definition, so the delta below is exactly what the margin moves by.
    metered_inr: Decimal
    #: The instant the original rows carry. The correction is stamped at it, not at now():
    #: a July call metered wrong was wrong in July, and dropping the fix into August would
    #: leave both months lying (`record_tier_correction` states the same rule).
    occurred_at: datetime
    #: Carried onto the correction so its money lands on the rung the call ran on rather
    #: than in `tier_usage.cost_unattributed_inr`, which an operator reads as "calls we
    #: could not attribute a voice to".
    tts_tier: str | None
    tts_tier_source: str | None


def correction_ref(*, source_currency: str, from_divisor: Decimal, to_divisor: Decimal) -> str:
    """The restatement's own reference — traceable, and THE idempotency key.

    Content-addressed over the change being applied rather than minted per run, which is
    what makes a re-run a no-op instead of a second correction: the same flip always
    derives the same ref, and the lookup in `record_cost_unit_correction` finds the row
    the first run wrote. A LATER, different flip derives a different ref and gets its own
    correction for its own amount — never a second cancellation of one already applied.
    """
    return f"costunit:{source_currency}:{from_divisor}:{to_divisor}"


def restatement_delta(
    metered_inr: Decimal, *, from_divisor: Decimal, to_divisor: Decimal
) -> Decimal:
    """What this call's cost moves by when the divisor changes.

    `metered = raw / from`, so the true figure is `metered * from / to` and the delta is
    the difference. NUMERIC end to end, never a float (hard rule 7), quantized ONCE at the
    end with `ROUNDING` named explicitly rather than left to the ambient decimal context.

    Multiplied BEFORE dividing so that no intermediate RATIO is materialised: `from / to`
    is non-terminating for something as ordinary as 100/3, and rounding it first would
    carry that error into every row it then multiplied. Measured honestly, the two orders
    agree to the paisa at any magnitude this ledger holds — `Decimal`'s default context
    keeps 28 significant digits — so this is the order being free rather than a live
    defect being fixed. It stops being free the day anything lowers that precision, and an
    arithmetic whose correctness depends on a global setting is not one to leave standing.
    """
    if min(from_divisor, to_divisor) <= 0:
        raise ValueError("a minor-units-per-major divisor must be positive")
    restated = metered_inr * from_divisor / to_divisor
    return (restated - metered_inr).quantize(MONEY_Q, rounding=ROUNDING)


async def mis_metered_calls(session: AsyncSession, *, source_currency: str) -> list[MisMeteredCall]:
    """Every call in THIS tenant whose cost rows were priced as `source_currency`.

    Takes a tenant-scoped session and no tenant id, which is what makes RLS the isolation
    rather than a convention (`db/session.py::session_tenant` argues it) — the query names
    no `tenant_id` and cannot reach another tenant's rows even if a caller wanted it to.

    Correction rows are excluded BY CONSTRUCTION rather than by a filter: neither this
    module's rows nor `record_tier_correction`'s carry `meta.source_currency`. That is the
    right answer for both — a tier correction is priced off our own rate card and was never
    touched by the vendor's divisor, and re-reading our own restatement would compound it.
    """
    rows = (
        await session.execute(
            text(
                "SELECT call_id, "
                f"       SUM({_ROW_COST_SQL}) AS metered_inr, "
                "       MIN(occurred_at) AS occurred_at, "
                "       MIN(meta ->> 'tts_tier') AS tts_tier, "
                "       MIN(meta ->> 'tts_tier_source') AS tts_tier_source "
                "  FROM usage_events "
                f" WHERE call_id IS NOT NULL AND meta ->> '{_SOURCE_CURRENCY_KEY}' = :cur "
                # A stable order for the same reason `retention._due_tenants` has one:
                # without it, WHICH calls a truncated or interrupted run reached varies
                # between runs and "was this call restated?" stops having an answer.
                " GROUP BY call_id ORDER BY call_id"
            ),
            {"cur": source_currency},
        )
    ).all()
    return [
        MisMeteredCall(
            call_id=UUID(str(call_id)),
            metered_inr=Decimal(str(metered)),
            occurred_at=occurred_at,
            tts_tier=tier,
            tts_tier_source=tier_source,
        )
        for call_id, metered, occurred_at, tier, tier_source in rows
    ]


async def record_cost_unit_correction(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call: MisMeteredCall,
    source_currency: str,
    from_divisor: Decimal,
    to_divisor: Decimal,
) -> Decimal | None:
    """Append the compensating row. Returns the delta written, or None if nothing moved.

    None means one of two things and both are correct outcomes: the flip changes this
    call's cost by less than a paisa (a ₹0 row is not evidence of anything), or this exact
    flip has already been applied to this call.

    IDEMPOTENCY IS THE WHOLE GAME on a ledger whose rows cannot be taken back, so it is
    taken the way `record_tier_correction` takes it — the dedupe SELECT runs with
    `lock_tenant_credits` ALREADY HELD, because a check-then-write outside that lock is
    exactly how this repo produced double credits once already (D-110). Two operators
    running the script at once write one row between them.
    """
    delta = restatement_delta(call.metered_inr, from_divisor=from_divisor, to_divisor=to_divisor)
    if delta == 0:
        return None

    await lock_tenant_credits(session, tenant_id)
    ref = correction_ref(
        source_currency=source_currency, from_divisor=from_divisor, to_divisor=to_divisor
    )
    already = (
        await session.execute(
            text(
                "SELECT 1 FROM usage_events WHERE tenant_id = :tid AND call_id = :cid "
                "AND meta->>'correction_ref' = :ref LIMIT 1"
            ),
            {"tid": tenant_id, "cid": call.call_id, "ref": ref},
        )
    ).first()
    if already:
        return None

    meta = {
        "kind": COST_UNIT_CORRECTION_META_KIND,
        "correction_ref": ref,
        # NOT `source_currency` — see `_SOURCE_CURRENCY_KEY`. This row must never read as
        # one of the rows it corrects.
        "corrected_source_currency": source_currency,
        "from_minor_units_per_major": str(from_divisor),
        "to_minor_units_per_major": str(to_divisor),
        "metered_inr": str(call.metered_inr),
        "tts_tier": call.tts_tier,
        "tts_tier_source": call.tts_tier_source,
        # The audit question a date on the row cannot answer, because `occurred_at` is
        # deliberately the original call's.
        "issued_at": datetime.now(UTC).isoformat(),
    }
    await session.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, unit_cost_paid, "
            "occurred_at, meta, created_at) VALUES (:id, :tid, :cid, 'other', 1, :cost, "
            ":at, CAST(:meta AS jsonb), now())"
        ),
        {
            "id": uuid7(),
            "tid": tenant_id,
            "cid": call.call_id,
            "cost": delta,
            "at": call.occurred_at,
            "meta": json.dumps(meta),
        },
    )
    log.info(
        "cost_unit_restated",
        extra={
            "tenant_id": str(tenant_id),
            "call_id": str(call.call_id),
            "correction_ref": ref,
        },
    )
    return delta


__all__ = [
    "COST_UNIT_CORRECTION_META_KIND",
    "MisMeteredCall",
    "correction_ref",
    "mis_metered_calls",
    "record_cost_unit_correction",
    "restatement_delta",
]
