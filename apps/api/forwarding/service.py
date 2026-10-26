"""A client's existing published number, forwarded by its carrier to its Calevate number (D-746).

Calevate cannot set a carrier forward: the client sets it on its own line. The product
records the number, shows the codes, verifies the forward with a short test call
(`forwarding/testing.py`), and watches for a line that goes quiet (`forwarding/quiet.py`).

THE LOOP GUARD. A number that forwards to Calevate must never be where the agent hands a
caller to a person, nor the phone a held line forwards to: the call would come straight back
to the agent. ThinnestAI refuses loops it can see inside its own system (`forward_loop`); a
loop through the client's carrier is outside its view. So the guard is ours, on every write:
a published number may not equal a business contact (whose numbers are every agent's
hand-off list), a hand-off rung, or the fallback phone, and none of those may equal a
published number. `assert_not_forwarded` is called by each of those writers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.forwarding.models import (
    CARRIERS,
    DEFAULT_RING_SECONDS,
    LINE_KINDS,
    MAX_LINES,
    MODES,
    RING_SECONDS,
)

log = get_logger(__name__)

#: The one sentence every loop refusal says (founder, 11 Oct 2026).
LOOP_MESSAGE: Final = "Use a phone that does not forward to your Calevate number."
LOOP_CODE: Final = "phone_forwards_to_calevate"

#: The Calevate numbers a screen lists; a client rents one or two.
MAX_CALEVATE_NUMBERS: Final = 20

_INDIA = re.compile(r"^\+91\d{10}$")


def normalize_india(raw: str) -> str | None:
    """`+91XXXXXXXXXX` from what a person types (spaces, dashes, a leading 0 or 91)."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        candidate = f"+91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        candidate = f"+91{digits[1:]}"
    elif len(digits) == 12 and digits.startswith("91"):
        candidate = f"+{digits}"
    else:
        return None
    return candidate if _INDIA.match(candidate) else None


def _bad_number() -> ProblemError:
    return ProblemError(
        kind="validation",
        code="forwarded_number_invalid",
        title="Enter your Indian business number",
        detail="Write it as 98765 43210, 040 1234 5678 or +91 98765 43210.",
        remediation="Check the number and try again.",
    )


# --- the loop guard ------------------------------------------------------------------------


async def published_numbers(session: AsyncSession) -> frozenset[str]:
    """This client's published numbers (RLS-scoped to the session's tenant)."""
    rows = (await session.execute(text("SELECT e164 FROM forwarded_lines"))).all()
    return frozenset(str(row[0]) for row in rows)


def _loop_refusal() -> ProblemError:
    return ProblemError.business_rule(
        LOOP_CODE,
        "This number forwards its calls to your Calevate number, so a call passed to it "
        "would come straight back to your agent.",
        remediation=LOOP_MESSAGE,
    )


async def assert_not_forwarded(session: AsyncSession, phones: list[str]) -> None:
    """Refuse a hand-off, contact or fallback phone that is one of this client's published
    numbers. Called by every writer of those phones, in its own session (RLS-scoped)."""
    if not phones:
        return
    published = await published_numbers(session)
    if any(phone in published for phone in phones):
        raise _loop_refusal()


async def _assert_free_of_handoff(session: AsyncSession, e164: str) -> None:
    """Refuse a published number that is already a contact, a hand-off rung or the
    fallback phone: forwarding it would close the loop from the other side."""
    taken = (
        await session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM business_contacts WHERE phone_e164 = :p) "
                "OR EXISTS (SELECT 1 FROM agent_handoff_members WHERE phone_e164 = :p) "
                "OR EXISTS (SELECT 1 FROM heal_fallback_phones WHERE phone_e164 = :p)"
            ),
            {"p": e164},
        )
    ).scalar()
    if taken:
        raise ProblemError.business_rule(
            LOOP_CODE,
            "This number is where your agent passes callers to a person, so it cannot also "
            "forward its calls to your Calevate number.",
            remediation=(
                "Change the person's phone in your contacts or the fallback phone first. "
                + LOOP_MESSAGE
            ),
        )


# --- the lines -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalevateNumber:
    id: UUID
    e164: str
    #: An agent that answers calls is on it.
    answering: bool


async def calevate_numbers(session: AsyncSession) -> list[CalevateNumber]:
    """The numbers we rented for this client, which a published number can forward to."""
    rows = (
        await session.execute(
            text(
                "SELECT n.id, n.e164, (a.id IS NOT NULL AND a.status = 'live' "
                "AND a.direction IN ('inbound', 'both') AND a.deleted_at IS NULL) "
                "FROM phone_numbers n LEFT JOIN agents a ON a.id = n.agent_id "
                "WHERE n.released_at IS NULL AND n.engine_owned ORDER BY n.created_at "
                "LIMIT :limit"
            ),
            {"limit": MAX_CALEVATE_NUMBERS},
        )
    ).all()
    return [CalevateNumber(id=row[0], e164=str(row[1]), answering=bool(row[2])) for row in rows]


@dataclass(frozen=True, slots=True)
class LineView:
    id: UUID
    e164: str
    line_kind: str
    carrier: str
    mode: str
    ring_seconds: int
    calevate_number_id: UUID | None
    calevate_number_e164: str | None
    status: str
    attested_at: datetime
    last_tested_at: datetime | None
    caller_id_finding: str | None
    concurrency_finding: str | None
    quiet_since: datetime | None
    last_test_outcome: str | None


_LINES_SQL: Final = (
    "SELECT l.id, l.e164, l.line_kind, l.carrier, l.mode, l.ring_seconds, "
    "l.calevate_number_id, n.e164, l.status, l.attested_at, l.last_tested_at, "
    "l.caller_id_finding, l.concurrency_finding, l.quiet_since, t.outcome "
    "FROM forwarded_lines l "
    "LEFT JOIN phone_numbers n ON n.id = l.calevate_number_id AND n.released_at IS NULL "
    "LEFT JOIN forwarding_tests t ON t.id = l.last_test_id "
)


def _view(row: Any) -> LineView:
    return LineView(
        id=row[0],
        e164=str(row[1]),
        line_kind=str(row[2]),
        carrier=str(row[3]),
        mode=str(row[4]),
        ring_seconds=int(row[5]),
        calevate_number_id=row[6],
        calevate_number_e164=str(row[7]) if row[7] is not None else None,
        status=str(row[8]),
        attested_at=row[9],
        last_tested_at=row[10],
        caller_id_finding=row[11],
        concurrency_finding=row[12],
        quiet_since=row[13],
        last_test_outcome=row[14],
    )


async def list_lines(session: AsyncSession) -> list[LineView]:
    rows = (await session.execute(text(_LINES_SQL + "ORDER BY l.created_at"))).all()
    return [_view(row) for row in rows]


async def read_line(session: AsyncSession, line_id: UUID) -> LineView:
    row = (await session.execute(text(_LINES_SQL + "WHERE l.id = :id"), {"id": line_id})).first()
    if row is None:
        raise ProblemError.not_found("Forwarded number")
    return _view(row)


def _check_choice(line_kind: str, carrier: str, mode: str, ring_seconds: int) -> None:
    """The mode and ring time agree (the carrier timer has no 0: 0 means all calls)."""
    if line_kind not in LINE_KINDS or carrier not in CARRIERS or mode not in MODES:
        raise ProblemError(
            kind="validation",
            code="forwarding_choice_invalid",
            title="Choose the kind of line, its provider and how calls should reach your agent",
            detail="One of the choices was not recognised.",
            remediation="Choose again from the lists.",
        )
    valid = (mode == "all_calls" and ring_seconds == 0) or (
        mode == "conditional" and ring_seconds in RING_SECONDS
    )
    if not valid:
        raise ProblemError(
            kind="validation",
            code="forwarding_ring_time_invalid",
            title="Choose a ring time of 5 to 30 seconds, or straight to your agent",
            detail="Phone networks take 5, 10, 15, 20, 25 or 30 seconds.",
            remediation="Pick one of the ring times offered.",
        )


async def _resolve_calevate_number(session: AsyncSession, number_id: UUID | None) -> UUID:
    numbers = await calevate_numbers(session)
    if not numbers:
        raise ProblemError.business_rule(
            "forwarding_needs_calevate_number",
            "You need your Calevate number before you can forward your existing number to it.",
            remediation="Get your Calevate number on the Phone numbers page first.",
        )
    if number_id is None:
        return numbers[0].id
    if all(number.id != number_id for number in numbers):
        raise ProblemError.not_found("Calevate number")
    return number_id


async def _queue_prompt_line(session: AsyncSession, tenant_id: UUID) -> None:
    """The agents' hidden-caller instruction is composed only for a client that has a
    forwarded number, so the first one added or the last one removed republishes them."""
    from apps.api.agents.live_apply import queue_live_apply

    await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason="forwarded_line")


def _attesting_user(principal: Principal) -> UUID:
    """Only a person of this business can say the number is the business's own."""
    user = principal.client_user_id
    if user is None:
        raise ProblemError.business_rule(
            "forwarding_attestation_personal",
            "Only someone from this business can confirm the number belongs to it.",
            remediation="Ask the business owner to add the number from their own account.",
        )
    return user


async def create_line(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    number: str,
    line_kind: str,
    carrier: str,
    mode: str,
    ring_seconds: int,
    calevate_number_id: UUID | None,
    attest: bool,
    ip: str | None = None,
) -> LineView:
    """Record a published number the client will forward. The client must confirm it is
    the business's own (the test call may only ever dial a number so confirmed)."""
    if not attest:
        raise ProblemError(
            kind="validation",
            code="forwarding_attestation_required",
            title="Confirm this number belongs to your business",
            detail="We only test numbers a business confirms are its own.",
            remediation="Tick the box to confirm, then save.",
        )
    attested_by = _attesting_user(principal)
    e164 = normalize_india(number)
    if e164 is None:
        raise _bad_number()
    _check_choice(line_kind, carrier, mode, ring_seconds)
    target = await _resolve_calevate_number(session, calevate_number_id)
    if any(n.e164 == e164 for n in await calevate_numbers(session)):
        raise ProblemError.business_rule(
            "forwarding_number_is_calevate",
            "That is your Calevate number. Enter the number your callers already know.",
            remediation="Enter your existing business number.",
        )
    await _assert_free_of_handoff(session, e164)
    existing = await list_lines(session)
    if any(line.e164 == e164 for line in existing):
        raise ProblemError.conflict(
            "forwarding_number_exists",
            "That number is already set up.",
            remediation="Change it below instead of adding it again.",
        )
    if len(existing) >= MAX_LINES:
        raise ProblemError.business_rule(
            "forwarding_lines_limit",
            f"You can set up at most {MAX_LINES} existing numbers.",
            remediation="Remove one you no longer use first.",
        )
    line_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO forwarded_lines (id, tenant_id, e164, line_kind, carrier, mode, "
            "ring_seconds, calevate_number_id, status, attested_by, attested_at) VALUES "
            "(:id, :tid, :e164, :kind, :carrier, :mode, :ring, :num, 'untested', :by, now())"
        ),
        {
            "id": line_id,
            "tid": tenant_id,
            "e164": e164,
            "kind": line_kind,
            "carrier": carrier,
            "mode": mode,
            "ring": ring_seconds,
            "num": target,
            "by": attested_by,
        },
    )
    if not existing:
        await _queue_prompt_line(session, tenant_id)
    await write_audit(
        session,
        actor=principal,
        action="forwarding.line_added",
        tenant_id=tenant_id,
        object_type="forwarded_line",
        object_id=str(line_id),
        ip=ip,
        summary={"line_kind": line_kind, "carrier": carrier, "mode": mode, "attested": True},
    )
    log.info("forwarding_line_added", extra={"tenant_id": str(tenant_id), "line_id": str(line_id)})
    return await read_line(session, line_id)


async def update_line(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    line_id: UUID,
    line_kind: str,
    carrier: str,
    mode: str,
    ring_seconds: int,
    calevate_number_id: UUID | None,
    ip: str | None = None,
) -> LineView:
    """Change how the number is forwarded. A change of mode or target means the forward the
    client set may no longer match, so the line reads untested until it is tested again."""
    _check_choice(line_kind, carrier, mode, ring_seconds)
    before = await read_line(session, line_id)
    target = await _resolve_calevate_number(
        session, calevate_number_id or before.calevate_number_id
    )
    changed_forward = (
        before.mode != mode
        or before.ring_seconds != ring_seconds
        or before.calevate_number_id != target
    )
    await session.execute(
        text(
            "UPDATE forwarded_lines SET line_kind = :kind, carrier = :carrier, mode = :mode, "
            "ring_seconds = :ring, calevate_number_id = :num, "
            "status = CASE WHEN :reset AND status <> 'testing' THEN 'untested' ELSE status END, "
            "updated_at = now() WHERE id = :id"
        ),
        {
            "id": line_id,
            "kind": line_kind,
            "carrier": carrier,
            "mode": mode,
            "ring": ring_seconds,
            "num": target,
            "reset": changed_forward,
        },
    )
    await write_audit(
        session,
        actor=principal,
        action="forwarding.line_changed",
        tenant_id=tenant_id,
        object_type="forwarded_line",
        object_id=str(line_id),
        ip=ip,
        summary={"carrier": carrier, "mode": mode, "ring_seconds": str(ring_seconds)},
    )
    return await read_line(session, line_id)


async def delete_line(
    session: AsyncSession,
    *,
    principal: Principal,
    tenant_id: UUID,
    line_id: UUID,
    ip: str | None = None,
) -> None:
    """Forget a published number. The client should also switch the forward off on its
    phone; the screen shows the codes for that before the button."""
    deleted = (
        await session.execute(
            text("DELETE FROM forwarded_lines WHERE id = :id RETURNING id"), {"id": line_id}
        )
    ).first()
    if deleted is None:
        raise ProblemError.not_found("Forwarded number")
    remaining = (await session.execute(text("SELECT count(*) FROM forwarded_lines"))).scalar_one()
    if remaining == 0:
        await _queue_prompt_line(session, tenant_id)
    await write_audit(
        session,
        actor=principal,
        action="forwarding.line_removed",
        tenant_id=tenant_id,
        object_type="forwarded_line",
        object_id=str(line_id),
        ip=ip,
        summary={"removed": True},
    )


async def has_forwarded_line(session: AsyncSession) -> bool:
    """Does this client forward a published number? Decides the agents' hidden-caller line."""
    return bool(
        (await session.execute(text("SELECT EXISTS (SELECT 1 FROM forwarded_lines)"))).scalar()
    )


def platform_caller_numbers() -> frozenset[str]:
    """The platform numbers a forwarding test rings from."""
    settings = get_settings()
    return frozenset(
        n
        for n in (settings.trial_caller_number, settings.forwarding_test_second_number)
        if n is not None
    )


__all__ = [
    "DEFAULT_RING_SECONDS",
    "LOOP_CODE",
    "LOOP_MESSAGE",
    "CalevateNumber",
    "LineView",
    "assert_not_forwarded",
    "calevate_numbers",
    "create_line",
    "delete_line",
    "has_forwarded_line",
    "list_lines",
    "normalize_india",
    "platform_caller_numbers",
    "published_numbers",
    "read_line",
    "update_line",
]
