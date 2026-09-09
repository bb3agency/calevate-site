"""**HOW MANY CARTESIA MINUTES THE WHOLE PLATFORM SPOKE THIS MONTH** — the one reader,
and the one writer.

WHY THIS EXISTS. Cartesia is not billed per minute: it is a monthly subscription with an
included credit allotment and an overage past it (`billing/rates.CartesiaPlan`). A
subscription has no per-minute cost until a VOLUME is named, so every honest figure about
the Cartesia leg — what a minute costs us, whether a rate-card rung is above water, which
plan we should be on — is a function of one platform-wide number that no module held until
now. The ops console printed the plan's BEST per-minute price under a column headed "COSTS
US" instead, and on 9 Sep 2026 the founder read it and said it could not be right (D-556).

**PLATFORM-WIDE, WHICH IS WHY IT IS A COUNTER.** The allotment is bought once for the whole
deployment, not per client, so the volume that prices it is the sum over every tenant.
`usage_events` FORCEs RLS and `admin_session` widens the policy on `organizations` ALONE
(`db/session.admin_session`), so a cross-tenant `SUM` is unaskable in app code and reaching
for the admin DB role to get one would break hard rule 1. That is exactly the corner
`billing/ai_quota.read_platform_ai_spend` is in, and this is its answer: a platform-scoped
counter with no `tenant_id` and no policy, moved in ONE statement by the meter that writes
the per-tenant rows, and read by anyone in one query.

⚠ **THE FIRST BUILD OF THIS MODULE WALKED THE CLIENT BOOK INSTEAD** — one tenant session
and two aggregates per account, the shape `billing/spend_routes.fleet_spend` uses. It was
correct, and it does not scale on a READ an ops console refreshes: measured on this
repository's own development database, **8,480 organizations**, it turned one rate-card read
into 8,480 session checkouts and stalled the test suite. The lesson is worth keeping rather
than quietly deleting: a board an operator opens deliberately can afford a per-tenant walk;
a screen that polls cannot, and "it is the same shape the other board uses" is not by itself
an argument that a shape belongs on a different surface.

**TWO INDEPENDENT COUNTS, NOT ONE FIGURE TIMES AN ASSUMPTION.** `characters` is what the
BYOK synthesizer actually spoke and `call_minutes` is what those calls actually billed.
Cartesia sells CREDITS, which are characters, so the plan is priced off the first and
divided by the second — and `rates.TTS_ASSUMED_CHARS_PER_CALL_MINUTE` (360-540, unmeasured,
pilot gate 12) never enters the number an operator reads as today's cost. That band is what
the MODEL has to assume when pricing a hypothetical volume; it has no business inside a
measurement of a month somebody ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Characters per unit of `usage_events.qty` on a `tts_kchars` row — the quantum
#: `workers/pipeline._CHARS_PER_KCHAR` divides by, spelled here because this module
#: multiplies it back before storing. `billing/spend_routes.py` holds the same constant for
#: the same reason and `tests/cartesia_volume_test.py` pins the two equal.
CHARS_PER_KCHAR: Final[Decimal] = Decimal("1000")

#: The vendor whose volume this counter tracks. ONE member, matching
#: `ops/model_pricing.PLAN_BILLED_TTS_PROVIDERS`: a `usage_events` row carries no vendor, so
#: a second plan-billed vendor could not be told from the first without a discriminator on
#: the ledger row — a migration, not an edit to a constant.
PLAN_BILLED_VOICE: Final = "cartesia"

#: THE COUNTER MOVES IN ONE STATEMENT, so two calls completing at the same instant cannot
#: both read a pre-increment total and both write it back (BACKEND-PATTERNS §5 — the guard
#: is IN the write). `platform_tts_volume` is a counter and not a ledger, so `DO UPDATE` is
#: correct here and the table is deliberately NOT in `APPEND_ONLY_TABLES`: every figure it
#: holds is re-derivable from the per-tenant `usage_events` rows that produced it.
_BUMP_SQL: Final = """
INSERT INTO platform_tts_volume (month, provider, characters, call_minutes, updated_at)
VALUES (:month, :provider, :characters, :call_minutes, now())
ON CONFLICT (month, provider) DO UPDATE
   SET characters   = platform_tts_volume.characters   + EXCLUDED.characters,
       call_minutes = platform_tts_volume.call_minutes + EXCLUDED.call_minutes,
       updated_at   = now()
"""

_READ_SQL: Final = (
    "SELECT characters, call_minutes FROM platform_tts_volume "
    "WHERE month = :month AND provider = :provider"
)


@dataclass(frozen=True, slots=True)
class CartesiaVolume:
    """What the whole platform spoke on the Cartesia voice in one IST billing month.

    `characters` and `call_minutes` are INDEPENDENT counts of the same calls, both from our
    own meter, and neither is derived from the other — see the module docstring. Either may
    be zero, which is a real answer (nobody has run a Studio call this month) and not an
    absence.
    """

    month: str
    characters: Decimal
    call_minutes: Decimal


async def fleet_cartesia_volume(session: AsyncSession, *, month: str) -> CartesiaVolume:
    """This month's fleet-wide Cartesia characters and call-minutes. ONE indexed row.

    Works on any session — the table carries no `tenant_id` and no policy, so it answers the
    same on a tenant-scoped session as on the admin one. That is the whole reason it exists
    (module docstring), and it is what lets an ops READ ask the question without a walk.

    A month with no row is ZERO, not an error: nothing has been spoken yet. The caller
    distinguishes "nobody spoke" from "there is no cost per minute" —
    `rates.cartesia_measured_cost_inr_per_call_minute` returns `None` for a zero divisor
    rather than putting a number on a screen that means neither.
    """
    row = (
        await session.execute(text(_READ_SQL), {"month": month, "provider": PLAN_BILLED_VOICE})
    ).first()
    if row is None:
        return CartesiaVolume(month=month, characters=Decimal("0"), call_minutes=Decimal("0"))
    return CartesiaVolume(
        month=month,
        characters=Decimal(str(row[0] or 0)),
        call_minutes=Decimal(str(row[1] or 0)),
    )


async def bump_cartesia_volume(
    session: AsyncSession, *, month: str, characters: Decimal, call_minutes: Decimal
) -> None:
    """Add one call's characters and minutes to the month's fleet total.

    Called by the post-call meter INSIDE the same transaction as the `usage_events` rows it
    describes, so the counter and the ledger it summarises can never be half-written — and
    the meter's own "already metered?" guard is what makes it exactly-once per call. A
    non-positive contribution writes nothing: a call that synthesized no characters and
    billed no minutes has nothing to add, and an `INSERT ... DO UPDATE` for it would create
    a month row that says a Studio call happened when none did.
    """
    if characters <= 0 and call_minutes <= 0:
        return
    await session.execute(
        text(_BUMP_SQL),
        {
            "month": month,
            "provider": PLAN_BILLED_VOICE,
            "characters": max(Decimal("0"), characters),
            "call_minutes": max(Decimal("0"), call_minutes),
        },
    )


__all__ = [
    "CHARS_PER_KCHAR",
    "PLAN_BILLED_VOICE",
    "CartesiaVolume",
    "bump_cartesia_volume",
    "fleet_cartesia_volume",
]
