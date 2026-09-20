"""Whose connection a bought number is — collected once per tenant, never changed.

The registered owner of a connection Calevate arranges is the CLIENT. That is not
paperwork trivia: it is the difference between connecting a number for a business and
reselling numbers in our own name, which is the shape
`docs/legal/LEGAL-OPS-PLAYBOOK.md`'s stop-list refuses (`:600-614`, items 1 and 10).

ONE ROW PER TENANT, AND THE DATABASE ENFORCES IT. `tenant_id` is UNIQUE and the table
carries `calevate_forbid_mutation`, so "collected once, then reused for every future
number, cannot be changed later" is a property rather than a screen's good manners. A
holder edited after a number was registered would leave the operator's record of who owns
the connection and ours disagreeing, and only theirs decides who is liable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.number_models import HOLDER_TYPES
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7

HolderType = Literal["individual", "business"]

NO_HOLDER_RULE: Final = "number_holder_not_recorded"

NO_HOLDER_REASON: Final = (
    "We need the name and email of the person or business this connection will be "
    "registered to before a number can be bought."
)


@dataclass(frozen=True, slots=True)
class HolderIdentity:
    """The identity every number of this tenant is registered to."""

    holder_type: HolderType
    holder_name: str
    holder_email: str


_SELECT = "SELECT holder_type, holder_name, holder_email FROM number_holders LIMIT 1"


async def read_holder(session: AsyncSession) -> HolderIdentity | None:
    """This tenant's holder, or None. Under RLS, so the tenant is implied.

    No `tenant_id` predicate and no LIMIT argument: the policy scopes the read and the
    unique constraint bounds it at one row. A `WHERE tenant_id = :tid` here would be a
    second, weaker copy of the isolation the policy already provides (hard rule 1).
    """
    row = (await session.execute(text(_SELECT))).first()
    if row is None:
        return None
    holder_type = str(row[0])
    # Narrowed rather than cast: the CHECK constraint makes the column's domain exactly
    # `HOLDER_TYPES`, and asserting that to the type checker with `cast` would be a claim
    # about the database from inside the application.
    assert holder_type in HOLDER_TYPES
    return HolderIdentity(
        holder_type="individual" if holder_type == "individual" else "business",
        holder_name=str(row[1]),
        holder_email=str(row[2]),
    )


async def record_holder(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    holder_type: HolderType,
    holder_name: str,
    holder_email: str,
) -> HolderIdentity:
    """Record the identity, once. A second attempt is refused, not merged.

    THE CONFLICT IS THE REFUSAL rather than a read-then-insert: two tabs submitting at
    once must not be able to produce two holders, and a check before the write leaves both
    of them believing the table was empty (BACKEND-PATTERNS §5's whole subject). The
    unique constraint is the authority, so the race is decided by the database.
    """
    try:
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO number_holders "
                    "(id, tenant_id, holder_type, holder_name, holder_email, recorded_by) "
                    "VALUES (:id, :tid, :ht, :name, :email, :uid)"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "ht": holder_type,
                    "name": holder_name.strip(),
                    "email": holder_email.strip(),
                    "uid": user_id,
                },
            )
    except IntegrityError as exc:
        raise ProblemError.conflict(
            "number_holder_already_recorded",
            "The details of who your numbers are registered to have already been "
            "recorded and cannot be changed.",
            remediation=(
                "Every number on this account is registered to the same holder. If the "
                "details are wrong, talk to us — the change has to be made with the "
                "operator who issued the connection, not here."
            ),
        ) from exc
    return HolderIdentity(
        holder_type=holder_type,
        holder_name=holder_name.strip(),
        holder_email=holder_email.strip(),
    )


async def require_holder(session: AsyncSession) -> HolderIdentity:
    """The holder, or the refusal that says what to send. Raises; writes nothing."""
    holder = await read_holder(session)
    if holder is None:
        raise ProblemError.business_rule(
            NO_HOLDER_RULE,
            NO_HOLDER_REASON,
            remediation=(
                "Record who the connection is registered to — an individual or a "
                "business, with a name and an email — and then buy the number. It is "
                "asked once and reused for every number after that."
            ),
        )
    return holder


__all__ = [
    "NO_HOLDER_REASON",
    "NO_HOLDER_RULE",
    "HolderIdentity",
    "HolderType",
    "read_holder",
    "record_holder",
    "require_holder",
]
