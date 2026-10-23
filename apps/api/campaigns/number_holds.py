"""A stopped client's rented numbers: held, then released before the next renewal (D-860).

Founder, 23 Oct 2026. A number a client rents through us is charged from its wallet every
month (D-665). When the client STOPS, the number is not given up at once, and nobody pays
another month for it:

* **Stopped** means the account is closed (`tenancy/closure.py`), or the prepaid wallet has
  been below zero for `number_hold_after_negative_days` (console setting, default 7; the 7 was
  proposed to the founder and not confirmed). A wallet below zero during an active trial
  stops nothing (D-536), so it holds nothing either.
* **Held**: nobody answers the number and nobody calls out on it (our attachment record
  treats a held number as answering nothing, `engine_numbers.wanted_attachment`), and the
  renewal job charges nothing for it (`workers/number_rental._RENEWING`).
* **Until** the period the client already paid for ends, never more than `MAX_HOLD`, and
  always before the voice platform's next monthly rent: `release_instant` below.
* **Undo**: a top-up back to zero or more, or the account reopened, ends the hold. The number
  answers again on the agent it was on (`phone_numbers.agent_id` is never touched by a hold)
  and the renewal job collects the next period as usual.
* **Then released** at once, for good (`?confirm=release`; "it goes back to the pool, anybody
  may rent it next, and this month's rent is not refunded",
  thinnest-findings/mirror/snapshots/2026-10-19/pages/api-reference/phone-numbers/
  release-phone-number.md:7, :461-464). There is no cool-off in our own workspace: the founder
  declined paying a renewal to keep one.

Which numbers: those we rented in the client's OWN workspace (`engine_owned`, a vendor handle
naming that workspace). A number held in our developer workspace and lent to a client for
testing is not the client's to lose; it stays an operator's to release (`releasable_by`).

This module writes rows only. The vendor calls (reading the rent day, detaching, releasing)
and the emails are the hold job's, `apps/workers/number_holds.py`, which every writer here
reaches through the outbox (`queue_hold_settlement`) and which also runs hourly.

Ids and counts in every log line; never a phone number (hard rule 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.models import NumberHoldReason, number_on_hold_sql
from apps.api.billing.number_rental import add_months, is_prepaid
from apps.api.billing.plans import IST
from apps.api.billing.service import get_balance
from apps.api.billing.trials import trial_billing_active
from apps.api.campaigns.engine_numbers import engine_number_provider, releasable_by
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.closure import read_closure
from apps.api.tenancy.engine_workspace import read_workspace_state

log = get_logger(__name__)

#: The outbox job that applies, ends and releases one tenant's holds
#: (`workers/number_holds.settle_number_holds`).
SETTLE_JOB: Final = "settle_number_holds"

#: The longest a number is held (founder, 23 Oct 2026).
MAX_HOLD: Final = timedelta(days=30)

#: How long before the earliest instant the next monthly rent could fall the number is
#: released. The rent day is known to the day at best (see `renewal_days`), the platform does
#: not say at what hour of that day it charges, and the hold job runs hourly with retries: a
#: full day lets about twenty-four attempts fail before any renewal could be charged, and
#: costs the client one day of a hold that is already only theirs because they stopped.
RELEASE_MARGIN: Final = timedelta(hours=24)

#: The reminder goes this many days before the release date, at `REMINDER_HOUR` IST, and
#: only on a hold long enough that it does not arrive on the heels of the first email.
REMINDER_DAYS_BEFORE: Final = 3
REMINDER_HOUR: Final = time(9, 0)
REMINDER_MIN_HOLD: Final = timedelta(days=5)


# --- when a held number is released ----------------------------------------------------


def renewal_days(anchors: Iterable[datetime]) -> set[date]:
    """Every calendar day the platform's monthly rent may count from.

    The platform charges "again every month on the same day until you release the number"
    (rent-phone-number.md:449-451) without saying in which zone that day is read. `since` is
    sent in UTC (get-phone-number.md:702-707) and our own records are dated in IST (D-709),
    and the two dates differ for any number rented between 18:30 and midnight UTC. So both
    readings of every anchor are candidates, and the earliest renewal any of them implies
    is the one we release before.
    """
    days: set[date] = set()
    for anchor in anchors:
        days.add(anchor.astimezone(UTC).date())
        days.add(anchor.astimezone(IST).date())
    return days


def next_renewal_start(anchors: Iterable[datetime], *, after: datetime) -> datetime:
    """The earliest instant the next monthly rent after `after` could be charged.

    For each candidate day, the first monthly repeat whose day has not yet begun in IST (the
    earlier of the two zones' midnights), the day clamped to the month's last
    (`add_months`): a number rented on the 31st renews on the 30th of a 30-day month or
    earlier, never later. A renewal day already under way when the hold starts is taken as
    charged; the next one is the one to beat.
    """
    best: datetime | None = None
    for day in renewal_days(anchors):
        months = 1
        while True:
            start = datetime.combine(add_months(day, months), time.min, tzinfo=IST)
            if start > after:
                break
            months += 1
        best = start if best is None or start < best else best
    if best is None:
        raise ValueError("a renewal needs at least one anchor")
    return best


def _ist_midnight(moment: datetime) -> datetime:
    return datetime.combine(moment.astimezone(IST).date(), time.min, tzinfo=IST)


def release_instant(*, held_at: datetime, anchors: Iterable[datetime]) -> datetime:
    """When a number held at `held_at` is released.

    `RELEASE_MARGIN` before the next renewal could start, and never after `MAX_HOLD` (the cap
    brought back to that day's IST midnight, so every release date reads as a whole day:
    "released on the 23rd" means "keep it by topping up before the 23rd"). Never before
    `held_at`: a hold that starts inside the margin releases at once, before the renewal it
    can still beat.
    """
    renewal = next_renewal_start(anchors, after=held_at)
    cap = _ist_midnight(held_at + MAX_HOLD)
    return max(held_at, min(cap, renewal - RELEASE_MARGIN))


def reminder_instant(*, held_at: datetime, release_at: datetime) -> datetime | None:
    """When the reminder goes: `REMINDER_DAYS_BEFORE` days before the release date at
    `REMINDER_HOUR` IST, or None when the hold is shorter than `REMINDER_MIN_HOLD`."""
    if release_at - held_at < REMINDER_MIN_HOLD:
        return None
    day = release_at.astimezone(IST).date() - timedelta(days=REMINDER_DAYS_BEFORE)
    at = datetime.combine(day, REMINDER_HOUR, tzinfo=IST)
    return at if held_at < at < release_at else None


# --- whether a tenant is stopped -------------------------------------------------------

#: When the wallet last went below zero and has stayed there: the first entry after the
#: newest one that left it at zero or more. Ordered as `billing/service._newest_balance`
#: orders the ledger.
_NEGATIVE_SINCE: Final = """
WITH last_ok AS (
    SELECT occurred_at, id FROM credit_ledger
     WHERE tenant_id = :tid AND balance_after >= 0
     ORDER BY occurred_at DESC, id DESC LIMIT 1
)
SELECT min(c.occurred_at) FROM credit_ledger c
 WHERE c.tenant_id = :tid
   AND (NOT EXISTS (SELECT 1 FROM last_ok)
        OR (c.occurred_at, c.id) > (SELECT occurred_at, id FROM last_ok))
"""


async def negative_since(session: AsyncSession, *, tenant_id: UUID) -> datetime | None:
    """Since when this wallet has been below zero, or None when it is at zero or more."""
    if (await get_balance(session, tenant_id=tenant_id)).amount_inr >= 0:
        return None
    since = (await session.execute(text(_NEGATIVE_SINCE), {"tid": tenant_id})).scalar()
    return since if isinstance(since, datetime) else None


async def stopped_reason(
    session: AsyncSession, *, tenant_id: UUID, now: datetime
) -> NumberHoldReason | None:
    """Why this tenant's rented numbers must be held now, or None when they must not."""
    closure = await read_closure(session, tenant_id=tenant_id)
    if closure.is_closed or closure.is_erased:
        return "account_closed"
    if not await is_prepaid(session, tenant_id=tenant_id):
        return None
    since = await negative_since(session, tenant_id=tenant_id)
    if since is None:
        return None
    if await trial_billing_active(session, tenant_id=tenant_id, at=now):
        return None
    threshold = timedelta(days=get_settings().number_hold_after_negative_days)
    return "wallet_negative" if now - since >= threshold else None


# --- the rows ---------------------------------------------------------------------------

_HOLDABLE: Final = (
    "SELECT n.id, n.engine_number_ref FROM phone_numbers n WHERE n.engine_owned "
    "AND n.released_at IS NULL AND n.engine_number_ref IS NOT NULL "
    f"AND n.provider = :provider AND NOT {number_on_hold_sql('n')} ORDER BY n.created_at, n.id"
)

_PLACE: Final = (
    "INSERT INTO phone_number_holds (id, tenant_id, number_id, agent_id, reason, held_at, "
    "created_at, updated_at) SELECT :id, :tid, n.id, n.agent_id, :reason, now(), now(), now() "
    "FROM phone_numbers n WHERE n.id = :nid "
    "ON CONFLICT (number_id) WHERE ended_at IS NULL DO NOTHING RETURNING id"
)


async def place_holds(
    session: AsyncSession, *, tenant_id: UUID, reason: NumberHoldReason
) -> list[UUID]:
    """Hold every number this tenant rents in its own workspace that is not held already.
    In the caller's transaction; the vendor work follows from `queue_hold_settlement`.
    Returns the numbers newly held."""
    provider = engine_number_provider()
    if provider is None:
        return []
    own = (await read_workspace_state(session, tenant_id)).workspace_id
    rows = (await session.execute(text(_HOLDABLE), {"provider": provider})).all()
    placed: list[UUID] = []
    for number_id, ref in rows:
        if not releasable_by(str(ref), own_workspace=own, by_admin=False):
            continue
        inserted = (
            await session.execute(
                text(_PLACE),
                {"id": uuid7(), "tid": tenant_id, "nid": number_id, "reason": reason},
            )
        ).first()
        if inserted is not None:
            placed.append(UUID(str(number_id)))
    if placed:
        log.warning(
            "number_holds_placed",
            extra={"tenant_id": str(tenant_id), "reason": reason, "numbers": len(placed)},
        )
    return placed


async def queue_hold_settlement(session: AsyncSession, *, tenant_id: UUID) -> None:
    """Owe this tenant a pass of the hold job, in the caller's transaction: a closure, a
    reopening and a wallet climbing back to zero each act on the phone at once rather than
    at the next hourly tick."""
    await enqueue_outbox(session, job=SETTLE_JOB, payload={"tenant_id": str(tenant_id)})


@dataclass(frozen=True, slots=True)
class OpenHold:
    hold_id: UUID
    number_id: UUID
    engine_number_ref: str | None
    reason: NumberHoldReason
    held_at: datetime
    release_at: datetime | None
    remind_at: datetime | None
    detached: bool
    recorded_at: datetime
    number_released: bool


_OPEN: Final = (
    "SELECT h.id, h.number_id, n.engine_number_ref, h.reason, h.held_at, h.release_at, "
    "h.remind_at, h.detached_at IS NOT NULL, n.created_at, n.released_at IS NOT NULL "
    "FROM phone_number_holds h JOIN phone_numbers n ON n.id = h.number_id "
    "WHERE h.ended_at IS NULL ORDER BY h.held_at, h.id"
)


async def open_holds(session: AsyncSession) -> list[OpenHold]:
    """This tenant's open holds, in its tenant session."""
    return [
        OpenHold(
            hold_id=UUID(str(r[0])),
            number_id=UUID(str(r[1])),
            engine_number_ref=str(r[2]) if r[2] else None,
            reason=r[3],
            held_at=r[4],
            release_at=r[5],
            remind_at=r[6],
            detached=bool(r[7]),
            recorded_at=r[8],
            number_released=bool(r[9]),
        )
        for r in (await session.execute(text(_OPEN))).all()
    ]


async def resume_holds(session: AsyncSession) -> list[UUID]:
    """End every open hold of this tenant because it is no longer stopped. A CAS: a hold a
    concurrent release ended first is not resumed. Returns the numbers to reattach."""
    rows = (
        await session.execute(
            text(
                "UPDATE phone_number_holds SET ended_at = now(), end_reason = 'resumed', "
                "updated_at = now() WHERE ended_at IS NULL RETURNING number_id"
            )
        )
    ).all()
    return [UUID(str(r[0])) for r in rows]


async def close_holds_of_released_numbers(session: AsyncSession) -> int:
    """End the open holds of numbers already given back some other way (the client's own
    Release, an operator's). Nothing to tell anybody: the release notice is stamped as done."""
    rows = (
        await session.execute(
            text(
                "UPDATE phone_number_holds h SET ended_at = now(), end_reason = 'released', "
                "release_notice_at = now(), updated_at = now() FROM phone_numbers n "
                "WHERE n.id = h.number_id AND h.ended_at IS NULL AND n.released_at IS NOT NULL "
                "RETURNING h.id"
            )
        )
    ).all()
    return len(rows)


async def apply_hold(
    session: AsyncSession,
    *,
    hold_id: UUID,
    release_at: datetime,
    remind_at: datetime | None,
    anchor_source: str,
) -> bool:
    """Set a recorded hold's release date. A CAS on `release_at IS NULL`: a second pass
    that read the same hold does not move the date the first one told the client."""
    row = (
        await session.execute(
            text(
                "UPDATE phone_number_holds SET release_at = :release, remind_at = :remind, "
                "anchor_source = :source, updated_at = now() "
                "WHERE id = :id AND ended_at IS NULL AND release_at IS NULL RETURNING id"
            ),
            {"release": release_at, "remind": remind_at, "source": anchor_source, "id": hold_id},
        )
    ).first()
    return row is not None


async def mark_detached(session: AsyncSession, *, hold_id: UUID) -> None:
    await session.execute(
        text(
            "UPDATE phone_number_holds SET detached_at = now(), updated_at = now() "
            "WHERE id = :id AND detached_at IS NULL"
        ),
        {"id": hold_id},
    )


async def claim_release(session: AsyncSession, *, hold_id: UUID) -> bool:
    """End a due hold as released, in the transaction that releases the number at the
    vendor and records it. The row lock this takes is what a concurrent resume waits on, so
    a hold is never both resumed and released; a vendor failure rolls the claim back."""
    row = (
        await session.execute(
            text(
                "UPDATE phone_number_holds SET ended_at = now(), end_reason = 'released', "
                "updated_at = now() WHERE id = :id AND ended_at IS NULL "
                "AND release_at IS NOT NULL AND release_at <= now() RETURNING id"
            ),
            {"id": hold_id},
        )
    ).first()
    return row is not None


#: The notices a hold sends, each stamped in the transaction that queues it.
NOTICE_HELD: Final = "held"
NOTICE_REMINDER: Final = "reminder"
NOTICE_RELEASED: Final = "released"
NOTICE_EVENTS: Final = (NOTICE_HELD, NOTICE_REMINDER, NOTICE_RELEASED)

_CLAIM_NOTICES: Final[dict[str, str]] = {
    NOTICE_HELD: (
        "UPDATE phone_number_holds SET start_notice_at = now(), updated_at = now() "
        "WHERE ended_at IS NULL AND release_at IS NOT NULL AND start_notice_at IS NULL "
        "RETURNING id"
    ),
    NOTICE_REMINDER: (
        "UPDATE phone_number_holds SET reminder_notice_at = now(), updated_at = now() "
        "WHERE ended_at IS NULL AND remind_at IS NOT NULL AND remind_at <= now() "
        "AND start_notice_at IS NOT NULL AND reminder_notice_at IS NULL RETURNING id"
    ),
    NOTICE_RELEASED: (
        "UPDATE phone_number_holds SET release_notice_at = now(), updated_at = now() "
        "WHERE end_reason = 'released' AND release_notice_at IS NULL RETURNING id"
    ),
}


async def claim_notices(session: AsyncSession, *, event: str) -> list[UUID]:
    """The holds owed `event`'s email, stamped as queued. The caller queues ONE email for
    all of them in this transaction, so a client with three numbers reads one message."""
    rows = (await session.execute(text(_CLAIM_NOTICES[event]))).all()
    return [UUID(str(r[0])) for r in rows]


async def held_numbers(session: AsyncSession) -> dict[UUID, datetime | None]:
    """Each held number of this tenant and its release instant (None until the hold job has
    set it), for the numbers list."""
    rows = (
        await session.execute(
            text("SELECT number_id, release_at FROM phone_number_holds WHERE ended_at IS NULL")
        )
    ).all()
    return {UUID(str(r[0])): r[1] for r in rows}


__all__ = [
    "MAX_HOLD",
    "NOTICE_EVENTS",
    "NOTICE_HELD",
    "NOTICE_RELEASED",
    "NOTICE_REMINDER",
    "RELEASE_MARGIN",
    "REMINDER_DAYS_BEFORE",
    "SETTLE_JOB",
    "OpenHold",
    "apply_hold",
    "claim_notices",
    "claim_release",
    "close_holds_of_released_numbers",
    "held_numbers",
    "mark_detached",
    "negative_since",
    "next_renewal_start",
    "open_holds",
    "place_holds",
    "queue_hold_settlement",
    "release_instant",
    "reminder_instant",
    "renewal_days",
    "resume_holds",
    "stopped_reason",
]
