"""The operations view of clients' authorised calling numbers, and Calevate's filing of them.

    GET  /v1/admin/calling-number-filings                         every client with numbers
                                                                  to file, and our state
    POST /v1/admin/tenants/{tenant_id}/calling-number-filings     mark numbers filed

D-941 as amended 30 Oct 2026: the client authorises, Calevate declares
(`compliance/a2p_filing.py`). The board is the work list an operator files from; the write
records the date and the reference the filing returned.

**The board is `org:read`, the write `admin:tenants`**, for the reason the client-health
board gives (`admin/health_routes.py`): reading a work list is not the authority to act on
it, and a GET gated on a mutating permission is refused to a view-as session (D-22). The
write names its tenant in the path and runs inside `tenant_session`, the house pattern for
an admin-realm mutation (`national_dnd_routes.record_preference_scrub`). No step-up: the
filing opens or closes no gate, so it is outside BACKEND-PATTERNS §7's high-risk list.

**The cross-tenant read widens nothing**: the directory comes from the `app.admin` session,
which sees `organizations` only, and each client's rows are read inside its own
`tenant_session()` under ordinary RLS (`admin/health.py`'s argument, inherited).

**No audit row on the board**, as on the client-health board; every filing writes one.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.a2p_filing import (
    MAX_FILING_REFERENCE_CHARS,
    FilingStatus,
    alarm_from,
    filing_alarm_active,
    filing_status,
    record_filing,
)
from apps.api.compliance.audit import write_audit
from apps.api.compliance.autodialer import MAX_DECLARED_CLIS, enforced_from
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

board_router = APIRouter(prefix="/v1/admin/calling-number-filings", tags=["admin"])
tenant_router = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/calling-number-filings", tags=["admin"]
)

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
BoardReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]
Filer = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

_DIRECTORY = (
    "SELECT id, name, slug FROM organizations "
    "WHERE deleted_at IS NULL AND status <> 'churned' ORDER BY name, id"
)
_ONE = "SELECT name, slug FROM organizations WHERE deleted_at IS NULL AND id = :tid"


class FiledNumberOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str
    #: None until an operator marks it filed.
    filed_on: date | None
    filing_reference: str | None


class ClientFilingOut(BaseModel):
    """One client's authorised numbers and our filing of each."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    slug: str
    #: The IST day the client authorised us.
    authorised_on: date
    numbers: list[FiledNumberOut]
    unfiled: int


class FilingBoardOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The first IST day calls from unconfirmed numbers are refused.
    enforced_from: date
    #: From this IST day an unfiled authorised number raises `calling_numbers_unfiled`.
    alarm_from: date
    alarm: bool
    #: Every client with a current authorisation, those with numbers still to file first.
    clients: list[ClientFilingOut]


class MarkFiledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numbers: list[str] = Field(min_length=1, max_length=MAX_DECLARED_CLIS)
    #: The IST day the numbers were filed. Not in the future.
    filed_on: date
    #: What the filing returned: a ticket or acknowledgement number.
    filing_reference: str = Field(min_length=1, max_length=MAX_FILING_REFERENCE_CHARS)


def _client_out(
    *, tenant_id: UUID, name: str, slug: str, status: FilingStatus
) -> ClientFilingOut | None:
    if status.authorised_on is None or not status.numbers:
        return None
    return ClientFilingOut(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        authorised_on=status.authorised_on,
        numbers=[
            FiledNumberOut(
                number=n.number, filed_on=n.filed_on, filing_reference=n.filing_reference
            )
            for n in status.numbers
        ],
        unfiled=len(status.unfiled),
    )


@board_router.get(
    "",
    response_model=FilingBoardOut,
    openapi_extra=permission_meta("org:read"),
    summary="Clients' authorised calling numbers and whether Calevate has filed them",
)
async def read_filing_board(directory: AdminSession, principal: BoardReader) -> FilingBoardOut:
    del principal
    clients: list[ClientFilingOut] = []
    for org in (await directory.execute(text(_DIRECTORY))).all():
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            status = await filing_status(scoped, tenant_id=tenant_id)
        row = _client_out(tenant_id=tenant_id, name=str(org[1]), slug=str(org[2]), status=status)
        if row is not None:
            clients.append(row)
    clients.sort(key=lambda c: (c.unfiled == 0, c.authorised_on, c.name))
    return FilingBoardOut(
        enforced_from=enforced_from(),
        alarm_from=alarm_from(),
        alarm=filing_alarm_active(),
        clients=clients,
    )


@tenant_router.post(
    "",
    response_model=ClientFilingOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Mark a client's calling numbers filed with the telephone company (audited)",
)
async def mark_filed(
    tenant_id: UUID,
    body: MarkFiledIn,
    request: Request,
    directory: AdminSession,
    principal: Filer,
) -> ClientFilingOut:
    assert principal.user_id is not None
    org = (await directory.execute(text(_ONE), {"tid": tenant_id})).first()
    if org is None:
        raise ProblemError.not_found("organization")
    async with tenant_session(tenant_id) as scoped:
        row_id, filed = await record_filing(
            scoped,
            tenant_id=tenant_id,
            numbers=body.numbers,
            filed_on=body.filed_on,
            filing_reference=body.filing_reference,
            # `requires(..., realm="admin")` resolved this principal against `admin_users`.
            recorded_by_admin_id=principal.user_id,
        )
        # Same transaction as the filing. A count and the reference, never a number
        # (hard rule 6).
        await write_audit(
            scoped,
            action="a2p_filing.recorded",
            actor=principal,
            tenant_id=tenant_id,
            object_type="a2p_number_filing",
            object_id=str(row_id),
            ip=client_request_ip(request),
            summary={
                "numbers": len(filed),
                "filed_on": body.filed_on.isoformat(),
                "filing_reference": body.filing_reference.strip(),
            },
        )
        status = await filing_status(scoped, tenant_id=tenant_id)
    out = _client_out(tenant_id=tenant_id, name=str(org[0]), slug=str(org[1]), status=status)
    assert out is not None, "record_filing refuses a client with nothing authorised"
    return out


__all__ = [
    "ClientFilingOut",
    "FilingBoardOut",
    "MarkFiledIn",
    "board_router",
    "tenant_router",
]
