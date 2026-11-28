"""The bell's own sources (D-1048), each read from data the platform already holds.

* `posted`: items a job put on the bell (`preferences.post_bell`), such as a finished campaign.
* `milestones`: the account's first lead, first goal reached, and its 100th, 500th and
  1,000th answered call, each at the instant it happened, shown for `MILESTONE_DAYS`.
* `reminders`: a person who reached the goal at least an hour ago (and at most two days ago)
  whom nobody has rung since. The nudge is dated one hour after they reached it.
* `opt_outs`: people who asked not to be called, one item per IST day.
* `needs_you_split`: the queue's "needs you" calls, told apart into a call-back request and a
  message for the owner (W4.3). A call where the caller asked for a call back, or one was
  booked, is a call-back; any other "needs you" call is a message: something the caller wants
  the business to do.

Names are shown whole and numbers never: the bell sits behind the login, and a reminder that
does not say who is no use (the hot-lead email's rule, `workers/notifications._compose`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.optout import OPTOUT_PURPOSE
from apps.api.crm.lead_definition import BECAME_LEADS_SQL, GOAL_BAND
from apps.api.crm.performance import CONNECTED_SQL
from apps.api.tenancy.caller_words import CallerWords

#: How long a milestone stays on the bell.
MILESTONE_DAYS: Final = 30
#: Answered calls worth marking.
CALL_MILESTONES: Final = (100, 500, 1000)
#: A person at the goal stage for this long with no call since earns a reminder.
REMINDER_AFTER_MINUTES: Final = 60
#: Past this a reminder is stale; the needs-attention queue still lists the person.
REMINDER_WINDOW_HOURS: Final = 48
MAX_REMINDERS: Final = 20
OPT_OUT_DAYS: Final = 7
POSTED_DAYS: Final = 7


@dataclass(frozen=True, slots=True)
class BellItem:
    id: str
    kind: str
    title: str
    detail: str | None
    href: str | None
    occurred_at: datetime
    tone: Literal["info", "success", "warning", "critical"] = "info"


_POSTED_SQL: Final = text(
    "SELECT id, kind, title, detail, href, created_at FROM notification_deliveries "
    "WHERE channel = 'bell' AND created_at > now() - make_interval(days => :days) "
    "ORDER BY created_at DESC LIMIT :lim"
)


async def posted(session: AsyncSession, *, limit: int) -> list[BellItem]:
    rows = (await session.execute(_POSTED_SQL, {"days": POSTED_DAYS, "lim": limit})).all()
    return [
        BellItem(
            id=f"posted:{r[0]}",
            kind=str(r[1]),
            title=str(r[2]),
            detail=r[3],
            href=r[4],
            occurred_at=r[5],
            tone="success" if r[1] == "campaign_finished" else "info",
        )
        for r in rows
    ]


_FIRST_LEAD_SQL: Final = text(f"SELECT min(bl.became_lead_at) FROM {BECAME_LEADS_SQL} AS bl")
_FIRST_GOAL_SQL: Final = text(
    "SELECT min(created_at) FROM lead_events WHERE type = 'status_change' "
    "AND payload ->> 'status' = ANY(:goal)"
)
_NTH_CALL_SQL: Final = text(
    "SELECT started_at FROM calls WHERE NOT (trial_call OR paid_test_call) "
    f"AND started_at IS NOT NULL AND {CONNECTED_SQL} "
    "ORDER BY started_at, id OFFSET :skip LIMIT 1"
)


def _recent(at: object, now: datetime) -> datetime | None:
    if not isinstance(at, datetime):
        return None
    return at if (now - at).days < MILESTONE_DAYS else None


async def milestones(session: AsyncSession, *, words: CallerWords, now: datetime) -> list[BellItem]:
    items: list[BellItem] = []
    first = _recent((await session.execute(_FIRST_LEAD_SQL)).scalar(), now)
    if first is not None:
        items.append(
            BellItem(
                id="milestone:first_lead",
                kind="milestone",
                title=f"Your first {words.new_lead}.",
                detail=None,
                href="/leads",
                occurred_at=first,
                tone="success",
            )
        )
    goal = _recent(
        (await session.execute(_FIRST_GOAL_SQL, {"goal": list(GOAL_BAND)})).scalar(), now
    )
    if goal is not None:
        items.append(
            BellItem(
                id="milestone:first_goal",
                kind="milestone",
                title="Your first goal reached.",
                detail=None,
                href="/leads",
                occurred_at=goal,
                tone="success",
            )
        )
    for n in CALL_MILESTONES:
        at = _recent((await session.execute(_NTH_CALL_SQL, {"skip": n - 1})).scalar(), now)
        if at is None:
            continue
        items.append(
            BellItem(
                id=f"milestone:calls_{n}",
                kind="milestone",
                title=f"{n:,} calls answered.",
                detail=None,
                href="/calls",
                occurred_at=at,
                tone="success",
            )
        )
    return items


_REMINDERS_SQL: Final = text(
    "SELECT l.id, l.name, l.status_set_at FROM leads l "
    "WHERE l.status = 'hot' AND l.deleted_at IS NULL AND l.status_set_at IS NOT NULL "
    "AND l.status_set_at <= now() - make_interval(mins => :after) "
    "AND l.status_set_at > now() - make_interval(hours => :window) "
    "AND NOT EXISTS (SELECT 1 FROM calls k WHERE k.lead_id = l.id "
    "  AND k.direction = 'outbound' AND k.created_at > l.status_set_at) "
    "ORDER BY l.status_set_at DESC, l.id LIMIT :lim"
)


async def reminders(session: AsyncSession, *, words: CallerWords) -> list[BellItem]:
    rows = (
        await session.execute(
            _REMINDERS_SQL,
            {
                "after": REMINDER_AFTER_MINUTES,
                "window": REMINDER_WINDOW_HOURS,
                "lim": MAX_REMINDERS,
            },
        )
    ).all()
    items: list[BellItem] = []
    for lead_id, name, reached_at in rows:
        who = " ".join((name or "").split()) or f"A {words.caller}"
        items.append(
            BellItem(
                id=f"reminder:{lead_id}:{reached_at.isoformat()}",
                kind="reminder",
                title=f"Call {who} back",
                detail="Reached your goal over an hour ago and nobody has called since.",
                href=f"/leads/{lead_id}",
                occurred_at=reached_at + timedelta(minutes=REMINDER_AFTER_MINUTES),
                tone="warning",
            )
        )
    return items


_OPT_OUTS_SQL: Final = text(
    "SELECT (cl.created_at AT TIME ZONE 'Asia/Kolkata')::date AS day, count(*), "
    "max(cl.created_at) FROM consent_ledger cl "
    "WHERE cl.status = 'withdrawn' AND cl.purpose = :purpose "
    "AND cl.created_at > now() - make_interval(days => :days) "
    "GROUP BY day ORDER BY day DESC"
)


async def opt_outs(session: AsyncSession) -> list[BellItem]:
    rows = (
        await session.execute(_OPT_OUTS_SQL, {"purpose": OPTOUT_PURPOSE, "days": OPT_OUT_DAYS})
    ).all()
    return [
        BellItem(
            id=f"opt_out:{day.isoformat()}",
            kind="opt_out",
            title=(
                "1 person asked not to be called."
                if int(count) == 1
                else f"{int(count)} people asked not to be called."
            ),
            detail="They are on your do-not-call list now.",
            href="/do-not-call",
            occurred_at=last,
        )
        for day, count, last in rows
    ]


_CALLBACK_ASKED_SQL: Final = text(
    "SELECT id FROM calls WHERE id = ANY(:ids) "
    "AND (callback_requested IS TRUE OR outcome_tag = 'call_back_booked')"
)


async def needs_you_split(session: AsyncSession, call_ids: list[UUID]) -> set[UUID]:
    """Of these "needs you" calls, the ones that are call-back requests."""
    if not call_ids:
        return set()
    rows = await session.execute(_CALLBACK_ASKED_SQL, {"ids": call_ids})
    return {UUID(str(r[0])) for r in rows}


__all__ = [
    "CALL_MILESTONES",
    "MILESTONE_DAYS",
    "BellItem",
    "milestones",
    "needs_you_split",
    "opt_outs",
    "posted",
    "reminders",
]
