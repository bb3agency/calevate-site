"""The "no cold calls" pledge a client accepts before placing outbound calls (D-692).

Under D-692 the client is not DLT-registered and calls go out from ordinary ten-digit
numbers, so what separates a lawful relationship call from unsolicited commercial
communication is WHO is called. The pledge is the client's signed undertaking on exactly
that: only people who already deal with the business or asked to be called, never a
bought, rented or scraped list. It does not replace the DNC scrub or calling hours, which
still run on every dial.

VERSIONED, AND A NEW VERSION RE-OPENS THE GATE. `PLEDGE_VERSION` is the integer the gate
compares the latest acceptance against; changing a word of `PLEDGE_TEXT` without bumping it
is caught by `tests/outbound_pledge_test.py`, which pins the hash per version. An
acceptance records the SHA-256 of the exact text accepted, so "what did they agree to" is
answerable without trusting that this file was never edited.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

PLEDGE_VERSION: Final = 1

PLEDGE_TEXT: Final = (
    "No cold calls. On behalf of this business I confirm that our agents will call only "
    "people who already have a relationship with us — our existing customers, people who "
    "have enquired with us, and people who have asked us to call them. We will never call "
    "numbers from a purchased, rented, scraped or otherwise acquired contact list. We will "
    "stop calling anyone who asks us to, straight away. We understand that calls are placed "
    "only between 9:00 and 21:00 IST, that numbers on the do-not-call list are never "
    "called, and that our outbound calling will be suspended if we break this pledge."
)

PLEDGE_TEXT_SHA256: Final = hashlib.sha256(PLEDGE_TEXT.encode("utf-8")).hexdigest()

PLEDGE_MISSING_RULE: Final = "outbound_pledge_missing"
PLEDGE_OUTDATED_RULE: Final = "outbound_pledge_outdated"

PLEDGE_MISSING_REASON: Final = (
    "Before this account can place outbound calls, the account owner needs to accept the "
    "no-cold-calls pledge: you will call only people who already deal with you or asked "
    "to be called. Answering inbound calls is unaffected."
)
PLEDGE_OUTDATED_REASON: Final = (
    "The no-cold-calls pledge has been updated since this account accepted it. Read and "
    "accept the current version to resume outbound calls. Answering inbound calls is "
    "unaffected."
)


@dataclass(frozen=True, slots=True)
class PledgeState:
    """The latest acceptance, or none. `is_current` is the one predicate the gate asks."""

    accepted_version: int | None
    accepted_at: datetime | None
    accepted_by_user_id: UUID | None

    @property
    def is_current(self) -> bool:
        return self.accepted_version == PLEDGE_VERSION


_LATEST = (
    "SELECT pledge_version, accepted_at, accepted_by_user_id FROM outbound_pledge_acceptances "
    "WHERE tenant_id = :tid ORDER BY accepted_at DESC, created_at DESC LIMIT 1"
)


async def read_pledge(session: AsyncSession, *, tenant_id: UUID) -> PledgeState:
    row = (await session.execute(text(_LATEST), {"tid": tenant_id})).first()
    if row is None:
        return PledgeState(None, None, None)
    return PledgeState(int(row[0]), row[1], row[2])


async def pledge_blocker(session: AsyncSession, *, tenant_id: UUID) -> tuple[str, str] | None:
    """`(rule, reason)` if the pledge blocks this tenant's outbound, else None."""
    state = await read_pledge(session, tenant_id=tenant_id)
    if state.accepted_version is None:
        return (PLEDGE_MISSING_RULE, PLEDGE_MISSING_REASON)
    if not state.is_current:
        return (PLEDGE_OUTDATED_RULE, PLEDGE_OUTDATED_REASON)
    return None


async def accept_pledge(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    version: int,
    text_sha256: str,
    ip: str | None,
) -> UUID:
    """Record an acceptance of the CURRENT text. Refuses a stale version or a hash that
    is not the current text's, so a screen rendered before a bump cannot accept words the
    client was never shown."""
    if version != PLEDGE_VERSION or text_sha256 != PLEDGE_TEXT_SHA256:
        raise ProblemError.business_rule(
            "outbound_pledge_version_stale",
            "The pledge has changed since this page was opened.",
            remediation="Reload the page, read the current pledge and accept it again.",
        )
    acceptance_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO outbound_pledge_acceptances (id, tenant_id, pledge_version, "
            "  text_sha256, accepted_by_user_id, ip, accepted_at, created_at) "
            "VALUES (:id, :tid, :version, :sha, :uid, :ip, now(), now())"
        ),
        {
            "id": acceptance_id,
            "tid": tenant_id,
            "version": version,
            "sha": text_sha256,
            "uid": user_id,
            "ip": ip,
        },
    )
    return acceptance_id


__all__ = [
    "PLEDGE_MISSING_REASON",
    "PLEDGE_MISSING_RULE",
    "PLEDGE_OUTDATED_REASON",
    "PLEDGE_OUTDATED_RULE",
    "PLEDGE_TEXT",
    "PLEDGE_TEXT_SHA256",
    "PLEDGE_VERSION",
    "PledgeState",
    "accept_pledge",
    "pledge_blocker",
    "read_pledge",
]
