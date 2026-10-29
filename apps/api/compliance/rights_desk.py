"""The rights desk: a client's customers' DPDP requests, each with a 90-day clock (D-943).

The client is the Data Fiduciary for its callers (DPDP Act 2023; Calevate is its
processor), and the DPDP Rules 2025 give a fiduciary 90 days to answer a request to see,
correct or erase a person's data (official, PIB backgrounder 17 Nov 2025, as read in
`docs/research/research_notes/Calevate market and technology edge/india_regulation.md` §3).
The duty commences about 13 May 2027 (SECONDARY); the desk works now because a request a
customer makes today is still a request.

What exists already and is NOT rebuilt here: the subject export (`compliance/export.py`)
answers access, the erasure with its certificate (`compliance/deletion.py`) answers erasure.
The desk is the log in front of them — what was asked, when, by which channel, and how it
was answered — and the clock nothing else kept.

The person is named by `subject_ref` (`compliance.export.subject_ref`), the same handle the
erasure register uses, so a desk row and the erasure that answered it line up without the
desk holding a number (hard rule 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.export import subject_ref
from apps.api.compliance.models import (
    RIGHTS_REMINDER_DAYS,
    RIGHTS_REQUEST_CHANNELS,
    RIGHTS_REQUEST_KINDS,
    RIGHTS_RESPONSE_DAYS,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of

#: The most rows the desk returns. A business with more open requests than this has a
#: problem the list is not the answer to, and the counts below are not capped.
MAX_LIST: Final = 200
#: How far back a request may be dated: a person may have asked by letter weeks before
#: anyone logged it, but not before the business existed on this platform in any sense.
MAX_BACKDATE: Final = timedelta(days=365)

#: What answering each kind may consist of. `explained` fits every kind: a written answer
#: is always a possible answer, including "we hold nothing of yours".
ANSWERED_OUTCOMES: Final[dict[str, frozenset[str]]] = {
    "access": frozenset({"exported", "explained", "not_held"}),
    "correction": frozenset({"corrected", "explained", "not_held"}),
    "erasure": frozenset({"erased", "explained", "not_held"}),
    "nomination": frozenset({"nominated", "explained"}),
    "grievance": frozenset({"explained"}),
}
REFUSED_OUTCOMES: Final = frozenset({"identity_not_confirmed", "explained"})


@dataclass(frozen=True, slots=True)
class RightsRequest:
    id: UUID
    kind: str
    channel: str
    subject_ref: str
    received_at: datetime
    due_at: datetime
    status: str
    outcome: str | None
    closed_at: datetime | None
    deletion_request_id: UUID | None

    def days_left(self, now: datetime) -> int:
        """Whole days until the deadline; negative once it has passed."""
        return (self.due_at - now).days

    def due_soon(self, now: datetime) -> bool:
        return self.status == "open" and self.due_at - now <= timedelta(days=RIGHTS_REMINDER_DAYS)


_COLUMNS = (
    "id, kind, channel, subject_ref, received_at, due_at, status, outcome, closed_at, "
    "deletion_request_id"
)


def _row(row: Row[Any]) -> RightsRequest:
    return RightsRequest(*row)


async def log_request(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    kind: str,
    channel: str,
    phone_e164: str,
    received_at: datetime | None,
    created_by: UUID | None,
) -> RightsRequest:
    """Open one request. The deadline is fixed from when the person ASKED."""
    if kind not in RIGHTS_REQUEST_KINDS:
        raise ProblemError.business_rule("rights_unknown_kind", "That is not a request we log.")
    if channel not in RIGHTS_REQUEST_CHANNELS:
        raise ProblemError.business_rule("rights_unknown_channel", "Say how the person asked.")
    now = datetime.now(UTC)
    asked = received_at or now
    if asked.tzinfo is None:
        asked = asked.replace(tzinfo=UTC)
    if asked > now + timedelta(minutes=5):
        raise ProblemError.business_rule(
            "rights_received_in_future",
            "The date the person asked cannot be in the future.",
            remediation="Use the day they asked you, or leave it empty for today.",
        )
    if asked < now - MAX_BACKDATE:
        raise ProblemError.business_rule(
            "rights_received_too_old",
            "That request is more than a year old.",
            remediation="Log the date it was received; if it is older, answer it directly.",
        )
    row = (
        await session.execute(
            text(
                "INSERT INTO data_rights_requests (id, tenant_id, kind, channel, subject_ref, "
                "received_at, due_at, status, created_by, created_at, updated_at) VALUES "
                "(:id, :tid, :kind, :channel, :ref, :asked, "
                "CAST(:asked AS timestamptz) + make_interval(days => :days), "
                f"'open', :by, now(), now()) RETURNING {_COLUMNS}"
            ),
            {
                "days": RIGHTS_RESPONSE_DAYS,
                "id": uuid7(),
                "tid": tenant_id,
                "kind": kind,
                "channel": channel,
                "ref": subject_ref(phone_e164),
                "asked": asked,
                "by": created_by,
            },
        )
    ).one()
    return _row(row)


async def list_requests(session: AsyncSession, *, limit: int = MAX_LIST) -> list[RightsRequest]:
    """Open requests first, soonest deadline first; then the closed, newest first."""
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLUMNS} FROM data_rights_requests "
                "ORDER BY (status = 'open') DESC, "
                "CASE WHEN status = 'open' THEN due_at END ASC, closed_at DESC, id DESC "
                "LIMIT :limit"
            ),
            {"limit": min(limit, MAX_LIST)},
        )
    ).all()
    return [_row(row) for row in rows]


@dataclass(frozen=True, slots=True)
class DeskCounts:
    open: int
    due_soon: int
    overdue: int


async def counts(session: AsyncSession) -> DeskCounts:
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE status = 'open'), "
                "count(*) FILTER (WHERE status = 'open' AND due_at <= :soon AND due_at > :now), "
                "count(*) FILTER (WHERE status = 'open' AND due_at <= :now) "
                "FROM data_rights_requests"
            ),
            {
                "now": datetime.now(UTC),
                "soon": datetime.now(UTC) + timedelta(days=RIGHTS_REMINDER_DAYS),
            },
        )
    ).one()
    return DeskCounts(open=int(row[0]), due_soon=int(row[1]), overdue=int(row[2]))


async def close_request(
    session: AsyncSession,
    *,
    request_id: UUID,
    status: str,
    outcome: str,
    deletion_request_id: UUID | None,
    closed_by: UUID | None,
) -> RightsRequest:
    """Answer or refuse an open request, once (CAS on `status = 'open'`)."""
    current = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM data_rights_requests WHERE id = :id"),
            {"id": request_id},
        )
    ).first()
    if current is None:
        raise ProblemError.not_found("Request")
    request = _row(current)
    allowed = REFUSED_OUTCOMES if status == "refused" else ANSWERED_OUTCOMES.get(request.kind)
    if status not in ("answered", "refused") or allowed is None or outcome not in allowed:
        raise ProblemError.business_rule(
            "rights_outcome_mismatch",
            "That answer does not fit this kind of request.",
            remediation=f"Use one of: {', '.join(sorted(allowed or ()))}.",
        )
    if outcome == "erased":
        await _assert_erasure_answers(session, request, deletion_request_id)
    elif deletion_request_id is not None:
        raise ProblemError.business_rule(
            "rights_erasure_link_unexpected",
            "Only an erasure is answered by an erasure certificate.",
        )
    result = await session.execute(
        text(
            "UPDATE data_rights_requests SET status = :status, outcome = :outcome, "
            "closed_at = now(), closed_by = :by, deletion_request_id = :del, updated_at = now() "
            "WHERE id = :id AND status = 'open'"
        ),
        {
            "id": request_id,
            "status": status,
            "outcome": outcome,
            "by": closed_by,
            "del": deletion_request_id,
        },
    )
    if rowcount_of(result) == 0:
        raise ProblemError.conflict(
            "rights_request_closed", "This request has already been answered."
        )
    row = (
        await session.execute(
            text(f"SELECT {_COLUMNS} FROM data_rights_requests WHERE id = :id"),
            {"id": request_id},
        )
    ).one()
    return _row(row)


async def _assert_erasure_answers(
    session: AsyncSession, request: RightsRequest, deletion_request_id: UUID | None
) -> None:
    """An `erased` answer names the erasure that did it, for the SAME person."""
    if deletion_request_id is None:
        raise ProblemError.business_rule(
            "rights_erasure_not_linked",
            "Say which erasure answered this request.",
            remediation="File the erasure from this request, then mark it answered.",
        )
    match = (
        await session.execute(
            text("SELECT subject_ref FROM deletion_requests WHERE id = :id"),
            {"id": deletion_request_id},
        )
    ).first()
    if match is None:
        raise ProblemError.not_found("Erasure")
    if str(match[0]) != request.subject_ref:
        raise ProblemError.business_rule(
            "rights_erasure_other_person",
            "That erasure was for a different phone number.",
            remediation="File an erasure for this person's own number.",
        )


__all__ = [
    "ANSWERED_OUTCOMES",
    "MAX_LIST",
    "REFUSED_OUTCOMES",
    "DeskCounts",
    "RightsRequest",
    "close_request",
    "counts",
    "list_requests",
    "log_request",
]
