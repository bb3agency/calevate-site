"""Reading the client's own DLT Principal Entity registration (SEC-COMP §3).

The read half of a fact that only ops may write. `campaigns.service.record_dlt_registration`
records what the registrar says about a client's Principal Entity — deliberately with no
client-facing write route, because a client who could mark their own PE `active` would be
marking the launch gate green on a registration that does not exist. That reasoning covers
the WRITE and was silently applied to the read as well, which left the client with a launch
button disabled by `pe_registration_missing` / `pe_registration_not_active` and no page
anywhere that said what the registrar currently holds.

So: one function, on the caller's RLS-scoped session, returning the four facts a client is
entitled to about their own entity — what state it is in, which entity id it names, when it
was registered, and when WE last verified it — plus the PE→TM link, which fails separately
and sends the client to a different desk (`tm_link_not_active`).

**Absence is a value, not an exception.** Every tenant starts with no row, and a `None`
return would push each caller into inventing the same "not filed yet" shape. `recorded`
carries it explicitly so an empty registration and an unfiled one are one type.

**Hard rule 1.** The query carries `tenant_id` as a predicate AND runs under RLS. The
predicate is not the isolation — the GUC is — but a read whose predicate names the tenant
cannot silently start returning another tenant's row if a policy is ever loosened; it
returns zero rows twice over.

**Not the TM registration.** Calevate's own telemarketer registration is one global fact in
`platform_state`, read by `ops.service.read_tm_registration` and surfaced on
`GET /v1/ops/platform`. It is not per tenant and is not repeated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class PeRegistration:
    """What the registrar says about THIS client, as the platform last verified it."""

    # False = no row at all, which is the normal state of a new account and a different
    # fact from `status='not_started'` ("we have begun and are nowhere"). The launch gate
    # already distinguishes them (`pe_registration_missing` vs `pe_registration_not_active`)
    # and a client-facing view that collapsed them would explain the wrong next action.
    recorded: bool
    status: str | None
    tm_link_status: str | None
    pe_id: str | None
    entity_name: str | None
    registered_at: datetime | None
    verified_at: datetime | None

    @property
    def is_active(self) -> bool:
        """The client half of SEC-COMP §3's first bullet, in one property.

        Both halves, because both are required and either one failing stops the dialling:
        an entity registration that never authorised Calevate as its telemarketer places
        no calls. Computed here rather than in the console so this and
        `campaigns.service.launch_blockers` can never answer the question differently.
        """
        return self.status == "active" and self.tm_link_status == "active"


NOT_RECORDED = PeRegistration(
    recorded=False,
    status=None,
    tm_link_status=None,
    pe_id=None,
    entity_name=None,
    registered_at=None,
    verified_at=None,
)


async def read_pe_registration(session: AsyncSession, *, tenant_id: UUID) -> PeRegistration:
    """This tenant's PE registration, on the caller's RLS-scoped session.

    Returns `NOT_RECORDED` when there is no row — including for a session scoped to a
    different tenant, or one with no tenant GUC at all, both of which see zero rows by
    policy. That is the correct answer in every case: this session cannot see a
    registration, so as far as it is concerned there is none.
    """
    row = (
        await session.execute(
            text(
                "SELECT status, tm_link_status, pe_id, entity_name, registered_at, verified_at "
                "FROM dlt_registrations WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        return NOT_RECORDED
    return PeRegistration(
        recorded=True,
        status=str(row[0]),
        tm_link_status=str(row[1]),
        pe_id=row[2],
        entity_name=row[3],
        registered_at=row[4],
        verified_at=row[5],
    )


__all__ = ["NOT_RECORDED", "PeRegistration", "read_pe_registration"]
