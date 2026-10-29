"""The announcement bar's reads and writes (D-869).

Operators compose on `platform_announcements` through the admin-realm session; clients read
through their own tenant session, where `active_for` applies the audience and drops what
this account has dismissed. The audience is decided against `organizations.first_paid_at`,
the one fact this repo keeps for "has this account paid" (D-697): `trial` is never paid,
`paid` is paid at least once.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.announcements.schemas import (
    AnnouncementAdminOut,
    AnnouncementIn,
    AnnouncementOut,
    AnnouncementState,
    AnnouncementUpdateIn,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

#: The most announcements one client read returns. More than two at once is already a
#: wall; the ceiling is for the day somebody schedules ten.
MAX_ACTIVE: Final = 5
MAX_ADMIN_PAGE: Final = 100

#: Most urgent first on the client's bar.
_TONE_RANK_SQL: Final = (
    "CASE p.tone WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 WHEN 'success' THEN 2 ELSE 3 END"
)

_ADMIN_COLUMNS: Final = (
    "p.id, p.message, p.link_url, p.link_label, p.tone, p.audience, p.target_tenant_id, "
    "o.name AS target_tenant_name, p.starts_at, p.ends_at, p.ended_at, p.created_at, "
    "p.updated_at"
)
_ADMIN_FROM: Final = (
    "FROM platform_announcements p LEFT JOIN organizations o ON o.id = p.target_tenant_id"
)


def state_of(
    *, starts_at: datetime, ends_at: datetime | None, ended_at: datetime | None, now: datetime
) -> AnnouncementState:
    if ended_at is not None:
        return "ended"
    if ends_at is not None and ends_at <= now:
        return "finished"
    if starts_at > now:
        return "scheduled"
    return "showing"


def _admin_out(row: Any, now: datetime) -> AnnouncementAdminOut:
    return AnnouncementAdminOut(
        id=row.id,
        message=row.message,
        link_url=row.link_url,
        link_label=row.link_label,
        tone=row.tone,
        audience=row.audience,
        target_tenant_id=row.target_tenant_id,
        target_tenant_name=row.target_tenant_name,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        ended_at=row.ended_at,
        state=state_of(
            starts_at=row.starts_at, ends_at=row.ends_at, ended_at=row.ended_at, now=now
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _assert_target(session: AsyncSession, tenant_id: UUID | None) -> None:
    if tenant_id is None:
        return
    found = (
        await session.execute(text("SELECT 1 FROM organizations WHERE id = :id"), {"id": tenant_id})
    ).first()
    if found is None:
        raise ProblemError.not_found("Client account")


async def get_admin(session: AsyncSession, announcement_id: UUID) -> AnnouncementAdminOut:
    row = (
        await session.execute(
            text(f"SELECT {_ADMIN_COLUMNS} {_ADMIN_FROM} WHERE p.id = :id"),
            {"id": announcement_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Announcement")
    return _admin_out(row, datetime.now(UTC))


async def list_admin(
    session: AsyncSession, *, include_past: bool, limit: int
) -> tuple[list[AnnouncementAdminOut], int]:
    """Newest first. Without `include_past`, only what is scheduled or showing."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_ADMIN_COLUMNS}, count(*) OVER () AS matching {_ADMIN_FROM} "
                "WHERE CAST(:past AS boolean) OR (p.ended_at IS NULL "
                "AND (p.ends_at IS NULL OR p.ends_at > now())) "
                "ORDER BY p.starts_at DESC, p.id DESC LIMIT :limit"
            ),
            {"past": include_past, "limit": limit},
        )
    ).all()
    now = datetime.now(UTC)
    return [_admin_out(r, now) for r in rows], int(rows[0].matching) if rows else 0


async def create(
    session: AsyncSession, payload: AnnouncementIn, *, admin_user_id: UUID | None
) -> AnnouncementAdminOut:
    await _assert_target(session, payload.target_tenant_id)
    starts_at = payload.starts_at or datetime.now(UTC)
    if payload.ends_at is not None and payload.ends_at <= starts_at:
        raise ProblemError(
            kind="validation",
            code="announcement_window",
            title="It must end after it starts",
            detail="The end time is not after the start time.",
            remediation="Pick an end time after the start, or leave the end empty.",
        )
    new_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO platform_announcements (id, message, link_url, link_label, tone, "
            "audience, target_tenant_id, starts_at, ends_at, created_by, updated_by, "
            "created_at, updated_at) VALUES (:id, :message, :link_url, :link_label, :tone, "
            ":audience, :target, :starts_at, :ends_at, :by, :by, now(), now())"
        ),
        {
            "id": new_id,
            "message": payload.message,
            "link_url": payload.link_url,
            "link_label": payload.link_label,
            "tone": payload.tone,
            "audience": payload.audience,
            "target": payload.target_tenant_id,
            "starts_at": starts_at,
            "ends_at": payload.ends_at,
            "by": admin_user_id,
        },
    )
    return await get_admin(session, new_id)


async def update(
    session: AsyncSession,
    announcement_id: UUID,
    payload: AnnouncementUpdateIn,
    *,
    admin_user_id: UUID | None,
) -> tuple[AnnouncementAdminOut, list[str]]:
    """Merge the fields sent over the row, re-validate the whole, write it back under a
    compare-and-swap on `updated_at`. Returns the row and the names of the fields that moved.
    An ended announcement is history and is refused."""
    current = await get_admin(session, announcement_id)
    if current.state == "ended":
        raise ProblemError.conflict(
            "announcement_ended",
            "This announcement was ended and can no longer be changed.",
            remediation="Write a new announcement instead.",
        )
    sent = payload.model_fields_set
    merged: dict[str, Any] = {
        name: getattr(payload, name) if name in sent else getattr(current, name)
        for name in (
            "message",
            "link_url",
            "link_label",
            "tone",
            "audience",
            "target_tenant_id",
            "starts_at",
            "ends_at",
        )
    }
    if merged["audience"] != "tenant" and "target_tenant_id" not in sent:
        merged["target_tenant_id"] = None
    # On create a missing start means "now"; on a PATCH a null start would reach the NOT
    # NULL column, so it is refused with the other invalid shapes.
    if merged["starts_at"] is None:
        raise ProblemError(
            kind="validation",
            code="announcement_invalid",
            title="That change does not make a valid announcement",
            detail="The start time cannot be cleared.",
            remediation="Send a start time, or leave the start out to keep it.",
        )
    try:
        checked = AnnouncementIn.model_validate(merged)
    except ValidationError as exc:
        raise ProblemError(
            kind="validation",
            code="announcement_invalid",
            title="That change does not make a valid announcement",
            detail="; ".join(str(e["msg"]) for e in exc.errors()),
            remediation="Check the audience, the link and the start and end times together.",
        ) from exc
    await _assert_target(session, checked.target_tenant_id)
    moved = [name for name in merged if getattr(checked, name) != getattr(current, name)]
    if not moved:
        return current, []
    result = await session.execute(
        text(
            "UPDATE platform_announcements SET message = :message, link_url = :link_url, "
            "link_label = :link_label, tone = :tone, audience = :audience, "
            "target_tenant_id = :target, starts_at = :starts_at, ends_at = :ends_at, "
            "updated_by = :by, updated_at = now() "
            "WHERE id = :id AND ended_at IS NULL AND updated_at = :seen"
        ),
        {
            "id": announcement_id,
            "message": checked.message,
            "link_url": checked.link_url,
            "link_label": checked.link_label,
            "tone": checked.tone,
            "audience": checked.audience,
            "target": checked.target_tenant_id,
            "starts_at": checked.starts_at,
            "ends_at": checked.ends_at,
            "by": admin_user_id,
            "seen": current.updated_at,
        },
    )
    if rowcount_of(result) == 0:
        raise ProblemError.conflict(
            "announcement_changed_elsewhere",
            "Someone changed or ended this announcement while you were editing it.",
            remediation="Reload it and make your change again.",
        )
    return await get_admin(session, announcement_id), moved


async def end(
    session: AsyncSession, announcement_id: UUID, *, admin_user_id: UUID | None
) -> tuple[AnnouncementAdminOut, bool]:
    """Stop showing it now. Returns the row and whether THIS call ended it."""
    result = await session.execute(
        text(
            "UPDATE platform_announcements SET ended_at = now(), updated_by = :by, "
            "updated_at = now() WHERE id = :id AND ended_at IS NULL"
        ),
        {"id": announcement_id, "by": admin_user_id},
    )
    return await get_admin(session, announcement_id), rowcount_of(result) == 1


#: The audience test against this account's own `organizations` row, which a tenant session
#: can read (its policy matches on `id`), and its own agents for `outbound`. One spelling,
#: shared by the read and the dismissal, so the two cannot disagree about who was shown what.
_AUDIENCE_SQL: Final = (
    "(p.audience = 'all' "
    "  OR (p.audience = 'trial' AND o.first_paid_at IS NULL) "
    "  OR (p.audience = 'paid' AND o.first_paid_at IS NOT NULL) "
    "  OR (p.audience = 'tenant' AND p.target_tenant_id = :tid) "
    "  OR (p.audience = 'outbound' AND EXISTS (SELECT 1 FROM agents a "
    "      WHERE a.tenant_id = :tid AND a.deleted_at IS NULL AND a.direction <> 'inbound')))"
)
_ACTIVE_SQL: Final = (
    "SELECT p.id, p.message, p.link_url, p.link_label, p.tone, p.starts_at, p.ends_at "
    "FROM platform_announcements p JOIN organizations o ON o.id = :tid "
    "WHERE p.ended_at IS NULL AND p.starts_at <= :now "
    "AND (p.ends_at IS NULL OR p.ends_at > :now) "
    f"AND {_AUDIENCE_SQL} "
    "AND NOT EXISTS (SELECT 1 FROM announcement_dismissals d "
    "  WHERE d.announcement_id = p.id AND d.tenant_id = :tid) "
    f"ORDER BY {_TONE_RANK_SQL}, p.starts_at DESC, p.id DESC LIMIT :limit"
)


async def active_for(
    session: AsyncSession, *, tenant_id: UUID, limit: int, now: datetime | None = None
) -> list[AnnouncementOut]:
    rows = (
        await session.execute(
            text(_ACTIVE_SQL),
            {"tid": tenant_id, "now": now or datetime.now(UTC), "limit": limit},
        )
    ).all()
    return [
        AnnouncementOut(
            id=r.id,
            message=r.message,
            link_url=r.link_url,
            link_label=r.link_label,
            tone=r.tone,
            starts_at=r.starts_at,
            ends_at=r.ends_at,
        )
        for r in rows
    ]


async def dismiss(session: AsyncSession, *, tenant_id: UUID, announcement_id: UUID) -> bool:
    """Put it away for this account. True when THIS call did; False when it already was.
    404 for an announcement this account was never shown, so the route is not a way to
    learn which ids exist for other audiences. Who pressed it is the audit row's actor."""
    visible = (
        await session.execute(
            text(
                "SELECT 1 FROM platform_announcements p JOIN organizations o ON o.id = :tid "
                f"WHERE p.id = :id AND {_AUDIENCE_SQL}"
            ),
            {"tid": tenant_id, "id": announcement_id},
        )
    ).first()
    if visible is None:
        raise ProblemError.not_found("Announcement")
    result = await session.execute(
        text(
            "INSERT INTO announcement_dismissals (id, tenant_id, announcement_id, "
            "created_at, updated_at) VALUES (:id, :tid, :aid, now(), now()) "
            "ON CONFLICT (tenant_id, announcement_id) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id, "aid": announcement_id},
    )
    return rowcount_of(result) == 1


__all__ = [
    "MAX_ACTIVE",
    "MAX_ADMIN_PAGE",
    "active_for",
    "create",
    "dismiss",
    "end",
    "get_admin",
    "list_admin",
    "state_of",
    "update",
]
