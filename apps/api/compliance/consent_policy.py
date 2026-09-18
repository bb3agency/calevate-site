"""The account-level switch that decides whether a MISSING opt-in refuses a dial (D-624).

`compliance/service.check_dispatch` is deliberately permissive about consent — *"ABSENCE IS
NOT A REFUSAL, and that asymmetry is the whole design"* — because most dialable leads have
no `consent_ledger` row and refusing all of them would be met as an outage. That default was
right while the client's DLT Principal-Entity registration stood behind the dial: the
REGISTRATION separated a relationship call from a cold list, and the ledger did not have to.

An account sold on a SERVICE/TRANSACTIONAL footing has no such registration behind it, and
its entire position is that it calls the client's own existing consenting customers about
those customers' own bookings. Under the permissive default that position is an INTENTION
rather than a property of the system. This switch makes it the property.

⚠ **THE SWITCH IS NOT THE POLICY, AND THE DISTINCTION MATTERS FOR WHO MAY TOUCH IT.** Turning
it OFF widens who this account may lawfully call, so it is `org:manage` — the owner's
permission — and it is audited with the direction it moved, exactly as
`kb/curation.write_switch` is. Reading it is `org:read`, because a client's staff seeing why
a dial was refused is not authority to change the answer.

ONE WRITER, and it is here. `check_dispatch` READS the column through its own helper and
never writes it; nothing else in the tree writes it at all.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError

#: RLS scopes both statements — `organizations`' policy matches on `id`, so neither
#: statement carries a tenant predicate. The same reasoning `kb/curation` records: a
#: `WHERE id = :tid` here would read as the safety and would in fact be a second copy of a
#: predicate the database already applies, which is the reliance hard rule 1 exists to stop.
_READ_SQL = "SELECT outbound_requires_consent FROM organizations"
_LOCK_SQL = "SELECT outbound_requires_consent FROM organizations FOR UPDATE"
_WRITE_SQL = "UPDATE organizations SET outbound_requires_consent = :enabled, updated_at = now()"


async def read_policy(session: AsyncSession) -> bool:
    """The account's own switch, for the screen that renders it.

    NO ROW IS A 404 rather than a permissive default: under RLS an account that is not this
    session's is indistinguishable from one that does not exist, and answering `false` for a
    row we cannot see would report "this account calls anyone" about an account we know
    nothing about.
    """
    row = (await session.execute(text(_READ_SQL))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    return bool(row[0])


async def write_policy(session: AsyncSession, *, enabled: bool) -> bool:
    """Set the switch. Answers whether anything actually moved.

    THE ROW IS LOCKED FIRST, for `kb/curation.write_switch`'s reason: deciding "did this
    change?" is a read the write depends on, and a read-then-write without a lock is the
    shape BACKEND-PATTERNS §5 refuses. Two owners toggling at the same instant would each
    read the old value and each report a change, and the audit would carry two transitions
    for one.
    """
    row = (await session.execute(text(_LOCK_SQL))).first()
    if row is None:
        raise ProblemError.not_found("Organization")
    await session.execute(text(_WRITE_SQL), {"enabled": enabled})
    return bool(row[0]) != enabled


__all__ = ["read_policy", "write_policy"]
