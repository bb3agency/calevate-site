"""A client asking for more calls at once, and Calevate's answer (founder, 5 Nov 2026).

The number of lines is an operator's commercial decision (`tenancy/call_lines`), so the client
gets a request rather than a control. The lifecycle follows the quota-increase shape the big
platforms use (AWS Service Quotas: a request object that is PENDING until APPROVED or DENIED;
Slack app requests: every reviewer is told, and the reviewer acts from the message):

    open ──(an operator raises the lines above what the client had)──▶ done
         └─(an operator declines, with a reason the client reads)────▶ declined

* **One open request per client**, held by the unique partial index
  `uq_call_line_requests_one_open`: the insert is `ON CONFLICT DO NOTHING`, and a second tap
  is answered with the request already open. A read-then-insert would let two taps both see
  "none open" and both insert.
* **Operators are told through the outbox** (`OPERATOR_NOTICE_JOB`, keyed on the request), in
  the transaction that opened it: a rolled-back request tells nobody, a replay tells once.
  The console's bell reads the open requests themselves (`open_requests_by_client`).
* **The client is told on its bell** from the resolved row itself
  (`notifications/service.feed`), not from a copy, for `NOTICE_DAYS`.
* **Closing is part of the existing setter.** `call_lines.set_call_lines` calls
  `close_on_raise` in the transaction that moved the number, so a raise made from anywhere
  closes the request; a raise to any number above what the client had counts, because an
  operator who grants 3 of the 5 asked for has answered the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.base import uuid7
from apps.api.reliability.service import enqueue_outbox_once
from apps.api.tenancy.models import CALL_LINE_REQUEST_TEXT_MAX, CALL_LINES_MAX

log = get_logger(__name__)

#: The ARQ name of `workers/call_line_requests.notify_call_lines_request`.
OPERATOR_NOTICE_JOB: Final = "notify_call_lines_request"

#: How long a resolved request stays on the client's tile and bell.
NOTICE_DAYS: Final = 7

#: After a decline, how long before the same client may ask again. Each request emails every
#: operator, so a declined client tapping again at once would be the same question twice.
ASK_AGAIN_AFTER: Final = timedelta(days=1)

RequestStatus = Literal["open", "done", "declined"]


@dataclass(frozen=True, slots=True)
class LineRequest:
    id: UUID
    status: RequestStatus
    requested_by: UUID | None
    lines_at_request: int
    wanted_lines: int | None
    note: str | None
    created_at: datetime
    resolved_at: datetime | None
    lines_granted: int | None
    decline_reason: str | None


_COLUMNS = (
    "id, status, requested_by, lines_at_request, wanted_lines, note, created_at, resolved_at, "
    "lines_granted, decline_reason"
)


def _request(row: Any) -> LineRequest:
    return LineRequest(
        id=UUID(str(row[0])),
        status=row[1],
        requested_by=UUID(str(row[2])) if row[2] is not None else None,
        lines_at_request=int(row[3]),
        wanted_lines=int(row[4]) if row[4] is not None else None,
        note=row[5],
        created_at=row[6],
        resolved_at=row[7],
        lines_granted=int(row[8]) if row[8] is not None else None,
        decline_reason=row[9],
    )


def clean_text(value: str | None) -> str | None:
    """Trimmed, and None when nothing is left: an empty note is no note."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def open_request_for(session: AsyncSession, *, tenant_id: UUID) -> LineRequest | None:
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM call_line_requests "
                "WHERE tenant_id = :tid AND status = 'open'"
            ),
            {"tid": tenant_id},
        )
    ).first()
    return _request(row) if row is not None else None


async def latest_request(session: AsyncSession, *, tenant_id: UUID) -> LineRequest | None:
    """What the client's tile shows: the open request, else one answered in the last
    `NOTICE_DAYS`, else nothing."""
    row = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM call_line_requests WHERE tenant_id = :tid "
                "AND (status = 'open' OR resolved_at > now() - make_interval(days => :days)) "
                "ORDER BY (status = 'open') DESC, created_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "days": NOTICE_DAYS},
        )
    ).first()
    return _request(row) if row is not None else None


async def resolved_recently(session: AsyncSession, *, limit: int) -> list[LineRequest]:
    """The answered requests the client's bell carries, newest first. Tenant session."""
    rows = await session.execute(
        text(
            f"SELECT {_COLUMNS} FROM call_line_requests WHERE status <> 'open' "
            "AND resolved_at > now() - make_interval(days => :days) "
            "ORDER BY resolved_at DESC LIMIT :lim"
        ),
        {"days": NOTICE_DAYS, "lim": limit},
    )
    return [_request(r) for r in rows.all()]


async def ask_for_more(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    lines_now: int,
    on_trial: bool,
    wanted: int | None,
    note: str | None,
) -> tuple[LineRequest, bool]:
    """Open a request, or answer the one already open. `(request, created)`; operators are
    owed a notice only for a request this call created."""
    if on_trial:
        raise ProblemError(
            kind="business_rule",
            code="call_lines_request_on_trial",
            title="More calls at once come with a paid account",
            detail="A free trial has one call at a time. Once you pay, you can ask for more.",
        )
    already = await open_request_for(session, tenant_id=tenant_id)
    if already is not None:
        return already, False
    if lines_now >= CALL_LINES_MAX:
        raise ProblemError(
            kind="business_rule",
            code="call_lines_at_most",
            title="This account already has the most calls at once",
            detail=f"{CALL_LINES_MAX} calls at once is the most an account can have.",
        )
    if wanted is not None and not lines_now < wanted <= CALL_LINES_MAX:
        raise ProblemError(
            kind="validation",
            code="call_lines_wanted_out_of_range",
            title="Choose more calls than you have now",
            detail=f"You have {lines_now} now. Ask for {lines_now + 1} to {CALL_LINES_MAX}.",
            fields=[
                {
                    "field": "wanted",
                    "rule": "out_of_range",
                    "message": f"Must be {lines_now + 1}-{CALL_LINES_MAX}.",
                }
            ],
        )
    declined_lately = (
        await session.execute(
            text(
                "SELECT 1 FROM call_line_requests WHERE tenant_id = :tid "
                "AND status = 'declined' AND resolved_at > now() - make_interval(secs => :s)"
            ),
            {"tid": tenant_id, "s": ASK_AGAIN_AFTER.total_seconds()},
        )
    ).first()
    if declined_lately is not None:
        raise ProblemError(
            kind="conflict",
            code="call_lines_request_too_soon",
            title="We answered your last request today",
            detail="You can ask again tomorrow.",
        )
    note = clean_text(note)
    if note is not None and len(note) > CALL_LINE_REQUEST_TEXT_MAX:
        raise ProblemError(
            kind="validation",
            code="call_lines_note_too_long",
            title="The note is too long",
            detail=f"Keep it under {CALL_LINE_REQUEST_TEXT_MAX} characters.",
            fields=[{"field": "note", "rule": "max_length", "message": "Too long."}],
        )
    # The index arbiter is the partial unique index: two taps racing here both reach the
    # INSERT, one wins, and the other reads the winner below.
    row = (
        await session.execute(
            text(
                "INSERT INTO call_line_requests (id, tenant_id, requested_by, lines_at_request, "
                "wanted_lines, note, status, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :now_lines, :wanted, :note, 'open', now(), now()) "
                "ON CONFLICT (tenant_id) WHERE status = 'open' DO NOTHING "
                f"RETURNING {_COLUMNS}"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "uid": user_id,
                "now_lines": lines_now,
                "wanted": wanted,
                "note": note,
            },
        )
    ).first()
    if row is None:
        winner = await open_request_for(session, tenant_id=tenant_id)
        assert winner is not None, "the conflicting open request must be visible"
        return winner, False
    created = _request(row)
    await enqueue_outbox_once(
        session,
        job=OPERATOR_NOTICE_JOB,
        payload={"tenant_id": str(tenant_id), "request_id": str(created.id)},
        dedupe_key=f"call_lines_request:{created.id}",
    )
    log.info(
        "call_lines_requested",
        extra={"tenant_id": str(tenant_id), "request_id": str(created.id)},
    )
    return created, True


async def close_on_raise(
    session: AsyncSession, *, tenant_id: UUID, lines_in_force: int, admin_id: UUID | None
) -> LineRequest | None:
    """Mark the open request done when the lines now in force exceed what the client had
    when it asked. Conditional UPDATE: a decline landing at the same moment wins or loses
    the row, never both."""
    row = (
        await session.execute(
            text(
                "UPDATE call_line_requests SET status = 'done', resolved_at = now(), "
                "resolved_by = :admin, lines_granted = :lines, updated_at = now() "
                "WHERE tenant_id = :tid AND status = 'open' AND lines_at_request < :lines "
                f"RETURNING {_COLUMNS}"
            ),
            {"tid": tenant_id, "lines": lines_in_force, "admin": admin_id},
        )
    ).first()
    if row is None:
        return None
    done = _request(row)
    log.info(
        "call_lines_request_done",
        extra={"tenant_id": str(tenant_id), "request_id": str(done.id), "lines": lines_in_force},
    )
    return done


async def decline(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    request_id: UUID,
    admin_id: UUID | None,
    reason: str,
) -> LineRequest:
    cleaned = clean_text(reason)
    if cleaned is None or len(cleaned) > CALL_LINE_REQUEST_TEXT_MAX:
        raise ProblemError(
            kind="validation",
            code="call_lines_decline_reason",
            title="Say why, in one short sentence",
            detail=f"The client reads it. 1 to {CALL_LINE_REQUEST_TEXT_MAX} characters.",
            fields=[{"field": "reason", "rule": "length", "message": "Required, short."}],
        )
    row = (
        await session.execute(
            text(
                "UPDATE call_line_requests SET status = 'declined', resolved_at = now(), "
                "resolved_by = :admin, decline_reason = :reason, updated_at = now() "
                "WHERE id = :rid AND tenant_id = :tid AND status = 'open' "
                f"RETURNING {_COLUMNS}"
            ),
            {"rid": request_id, "tid": tenant_id, "admin": admin_id, "reason": cleaned},
        )
    ).first()
    if row is None:
        raise ProblemError(
            kind="conflict",
            code="call_lines_request_not_open",
            title="This request is already answered",
            detail="Someone raised the lines or declined it first. Reload to see what was done.",
        )
    return _request(row)


async def requester_name(session: AsyncSession, *, user_id: UUID | None) -> str | None:
    """Who asked, as an operator reads it: their name, else their email."""
    if user_id is None:
        return None
    value = (
        await session.execute(
            text("SELECT COALESCE(name, email) FROM users WHERE id = :uid"), {"uid": user_id}
        )
    ).scalar_one_or_none()
    return str(value) if value else None


def wanted_phrase(request: LineRequest) -> str:
    """ "4", or "more" when the client named no number."""
    return str(request.wanted_lines) if request.wanted_lines is not None else "more"


__all__ = [
    "ASK_AGAIN_AFTER",
    "NOTICE_DAYS",
    "OPERATOR_NOTICE_JOB",
    "LineRequest",
    "RequestStatus",
    "ask_for_more",
    "clean_text",
    "close_on_raise",
    "decline",
    "latest_request",
    "open_request_for",
    "requester_name",
    "resolved_recently",
    "wanted_phrase",
]
