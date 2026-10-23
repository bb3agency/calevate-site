"""The bell's feed (D-869): one list built from what already exists, plus a read mark.

Two sources, merged newest first:

* the needs-attention queue (`crm/attention.attention_queue`) — every thing the platform
  refused to do quietly, hot leads and low credit included;
* the announcements this account is shown (`announcements/service.active_for`).

Nothing is copied into a notifications table: a second store of the same facts would drift
from the queue the attention screen reads. What is stored is one high-water mark per person
(`notification_reads`), and "unread" is "newer than the mark".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.announcements import service as announcements
from apps.api.announcements.models import Tone
from apps.api.crm.attention import attention_queue
from apps.api.db.base import uuid7

MAX_FEED: Final = 100

NotificationSource = Literal["attention", "announcement"]

#: How loud each attention kind is on the bell. A kind missing here is `warning`: an
#: unlisted refusal is still something to look at.
_ATTENTION_TONE: Final[dict[str, Tone]] = {
    "lead_hot": "success",
    "inbound_stopped": "critical",
    "credit_low": "critical",
    "call_failed": "warning",
    "lead_blocked": "warning",
    "delivery_failed": "warning",
    "campaign_stalled": "warning",
    "kb_rejected": "warning",
    "action_broken": "warning",
    "forwarded_line_quiet": "warning",
}


class NotificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Unique within the feed: `<source>:<id>`.
    id: str
    source: NotificationSource
    #: The attention kind (`crm/schemas.AttentionKind`), or `announcement`.
    kind: str
    tone: Tone
    title: str
    detail: str | None
    #: Realm-relative link for an attention item; an https address or a console path for an
    #: announcement. None when there is nowhere to go.
    href: str | None
    link_label: str | None
    occurred_at: datetime
    unread: bool


class NotificationFeedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationOut]
    #: Unread among `items`.
    unread: int
    #: Everything the attention queue holds, not just this page (`AttentionOut.total`).
    attention_total: int
    #: The reader's mark; None before they have opened the bell, or for an operator viewing
    #: the account (who has no mark of their own here).
    seen_through: datetime | None


class SeenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Everything up to this instant has been seen; now when left out. A mark never moves
    #: backwards and never past now.
    through: datetime | None = None


class SeenOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seen_through: datetime | None


async def read_mark(session: AsyncSession, *, user_id: UUID | None) -> datetime | None:
    if user_id is None:
        return None
    value = (
        await session.execute(
            text("SELECT seen_through FROM notification_reads WHERE user_id = :uid"),
            {"uid": user_id},
        )
    ).scalar_one_or_none()
    return value if isinstance(value, datetime) else None


async def feed(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID | None, limit: int
) -> NotificationFeedOut:
    mark = await read_mark(session, user_id=user_id)
    queue = await attention_queue(session, limit=limit)
    shown = await announcements.active_for(
        session, tenant_id=tenant_id, limit=announcements.MAX_ACTIVE
    )

    def unread(at: datetime) -> bool:
        return mark is None or at > mark

    items = [
        NotificationOut(
            id=f"attention:{item['kind']}:{item['id']}",
            source="attention",
            kind=str(item["kind"]),
            tone=_ATTENTION_TONE.get(str(item["kind"]), "warning"),
            title=str(item["title"]),
            detail=str(item["detail"]) if item.get("detail") else None,
            href=item.get("href"),
            link_label=None,
            occurred_at=item["occurred_at"],
            unread=unread(item["occurred_at"]),
        )
        for item in queue["items"]
    ]
    items += [
        NotificationOut(
            id=f"announcement:{a.id}",
            source="announcement",
            kind="announcement",
            tone=a.tone,
            title=a.message,
            detail=None,
            href=a.link_url,
            link_label=a.link_label,
            occurred_at=a.starts_at,
            unread=unread(a.starts_at),
        )
        for a in shown
    ]
    items.sort(key=lambda n: (n.occurred_at, n.id), reverse=True)
    items = items[:limit]
    return NotificationFeedOut(
        items=items,
        unread=sum(1 for n in items if n.unread),
        attention_total=int(queue["total"]),
        seen_through=mark,
    )


async def mark_seen(
    session: AsyncSession, *, tenant_id: UUID, user_id: UUID, through: datetime | None
) -> datetime:
    """Move the person's mark forward to `through` (clamped to now). Never backwards: two
    tabs marking at once land on the later of the two."""
    now = datetime.now(UTC)
    at = now if through is None or through > now else through
    value = (
        await session.execute(
            text(
                "INSERT INTO notification_reads (id, tenant_id, user_id, seen_through, "
                "created_at, updated_at) VALUES (:id, :tid, :uid, :at, now(), now()) "
                "ON CONFLICT (tenant_id, user_id) DO UPDATE SET "
                "seen_through = GREATEST(notification_reads.seen_through, EXCLUDED.seen_through), "
                "updated_at = now() RETURNING seen_through"
            ),
            {"id": uuid7(), "tid": tenant_id, "uid": user_id, "at": at},
        )
    ).scalar_one()
    assert isinstance(value, datetime)
    return value


__all__ = [
    "MAX_FEED",
    "NotificationFeedOut",
    "NotificationOut",
    "SeenIn",
    "SeenOut",
    "feed",
    "mark_seen",
    "read_mark",
]
