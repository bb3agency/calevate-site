"""Calevate's filing of the calling numbers clients authorise us to declare (D-941 amended).

The client confirms its numbers and authorises us (`compliance/autodialer.py`); we declare
them to the telephone company and record that here. The route for filing is pending the
voice platform's answer (OPERATIONS §2 gate 59), so an operator files by whatever route
that answer gives and records the date and the reference it returned.

THE GATE DOES NOT WAIT FOR THIS. The client has done its part by authorising us; holding its
calls on our own paperwork would punish it for our delay. Our lateness is an operations
alarm instead: the client-health board raises `calling_numbers_unfiled` from
`FILING_ALARM_DAYS` before the enforcement date for any authorised number we have not filed.

A number counts as filed when any filing of the tenant names it; the latest such filing is
the one shown. Filings are append-only, so a mistaken reference is corrected by filing again.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import autodialer
from apps.api.compliance.autodialer import declared_cli, enforced_from, read_declaration
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

#: How long before the enforcement date an unfiled authorised number becomes an alarm.
FILING_ALARM_DAYS: Final = 7
MAX_FILING_REFERENCE_CHARS: Final = 200
#: Filings read per tenant; a client is filed a handful of times a year.
_FILING_HISTORY_LIMIT: Final = 100


@dataclass(frozen=True, slots=True)
class NumberFiling:
    """One authorised number and our latest filing of it, if any."""

    number: str
    filed_on: date | None = None
    filing_reference: str | None = None

    @property
    def filed(self) -> bool:
        return self.filed_on is not None


@dataclass(frozen=True, slots=True)
class FilingStatus:
    """A tenant's authorised numbers, each with our filing state.

    `authorised_on` is None when the client has no current authorisation (none recorded, a
    withdrawal, or only a version-1 row): there is then nothing for us to file.
    """

    authorised_on: date | None
    numbers: tuple[NumberFiling, ...]

    @property
    def unfiled(self) -> tuple[str, ...]:
        return tuple(n.number for n in self.numbers if not n.filed)


def alarm_from() -> date:
    """The first IST day an unfiled authorised number is an alarm."""
    return enforced_from() - timedelta(days=FILING_ALARM_DAYS)


def filing_alarm_active(today: date | None = None) -> bool:
    return (today or autodialer.ist_today()) >= alarm_from()


async def authorised_numbers(
    session: AsyncSession, *, tenant_id: UUID
) -> tuple[date | None, tuple[str, ...]]:
    """`(authorised_on, numbers)` from the tenant's latest row, if it is a current one."""
    declaration = await read_declaration(session, tenant_id=tenant_id)
    if not declaration.recorded or declaration.state != "notified" or not declaration.attested:
        return None, ()
    return declaration.notified_on, declaration.declared_clis


async def filing_status(session: AsyncSession, *, tenant_id: UUID) -> FilingStatus:
    """The tenant's authorised numbers and our latest filing of each, on its RLS session."""
    authorised_on, numbers = await authorised_numbers(session, tenant_id=tenant_id)
    if not numbers:
        return FilingStatus(authorised_on=authorised_on, numbers=())
    rows = await session.execute(
        text(
            "SELECT filed_clis, filed_on, filing_reference FROM a2p_number_filings "
            "WHERE tenant_id = :tid ORDER BY created_at DESC, id DESC LIMIT :limit"
        ),
        {"tid": tenant_id, "limit": _FILING_HISTORY_LIMIT},
    )
    latest: dict[str, tuple[date, str]] = {}
    for clis, filed_on, reference in rows:
        for number in clis or ():
            latest.setdefault(str(number), (filed_on, str(reference)))
    return FilingStatus(
        authorised_on=authorised_on,
        numbers=tuple(
            NumberFiling(number, *latest[number]) if number in latest else NumberFiling(number)
            for number in numbers
        ),
    )


async def record_filing(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    numbers: Sequence[str],
    filed_on: date,
    filing_reference: str,
    recorded_by_admin_id: UUID,
) -> tuple[UUID, tuple[str, ...]]:
    """Append one filing of `numbers` and return its id and the numbers as stored.

    Refuses a number the client has not currently authorised: we may declare only what the
    client authorised, and a filing of anything else would be a record of acting without it.
    A future `filed_on` is refused because a filing is recorded after it is made.
    """
    _, authorised = await authorised_numbers(session, tenant_id=tenant_id)
    filed: list[str] = []
    for raw in numbers:
        number = declared_cli(raw) if raw.strip() else None
        if number is None or number not in authorised:
            raise ProblemError.business_rule(
                "a2p_filing_number_not_authorised",
                "That number is not one this client has authorised us to declare.",
                remediation="File only the numbers listed for this client.",
            )
        if number not in filed:
            filed.append(number)
    if not filed:
        raise ProblemError.business_rule(
            "a2p_filing_numbers_missing",
            "Pick at least one number to mark filed.",
            remediation="Tick the numbers you filed.",
        )
    reference = filing_reference.strip()
    if not reference or len(reference) > MAX_FILING_REFERENCE_CHARS:
        raise ProblemError.business_rule(
            "a2p_filing_reference_invalid",
            "Enter the reference the filing returned.",
            remediation=f"Use 1 to {MAX_FILING_REFERENCE_CHARS} characters.",
        )
    if filed_on > autodialer.ist_today():
        raise ProblemError.business_rule(
            "a2p_filing_date_in_future",
            "A filing date cannot be in the future.",
            remediation="Enter the day the numbers were filed.",
        )
    row_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO a2p_number_filings (id, tenant_id, filed_clis, filed_on, "
            "filing_reference, recorded_by_admin_id) VALUES (:id, :tid, :clis, :on, :ref, :by)"
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "clis": filed,
            "on": filed_on,
            "ref": reference,
            "by": recorded_by_admin_id,
        },
    )
    return row_id, tuple(filed)


__all__ = [
    "FILING_ALARM_DAYS",
    "MAX_FILING_REFERENCE_CHARS",
    "FilingStatus",
    "NumberFiling",
    "alarm_from",
    "authorised_numbers",
    "filing_alarm_active",
    "filing_status",
    "record_filing",
]
