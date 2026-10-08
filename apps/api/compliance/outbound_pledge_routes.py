"""The no-cold-calls pledge, as the client reads and accepts it (D-692).

    GET  /v1/compliance/outbound-pledge   the current text, its version, and this account's
                                          latest acceptance
    POST /v1/compliance/outbound-pledge   accept the current version

Reading is `org:read`, so a support person in a read-only "view as client" session sees
why outbound is blocked. Accepting is `org:manage` — it is an undertaking made for the
business, and a view-as session must not make it on the client's behalf. The acceptance is
recorded twice on purpose: a row in `outbound_pledge_acceptances` (the consent record the
gate reads) and an `audit_log` entry (who did it, from where, in the hash chain).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.outbound_pledge import (
    PLEDGE_TEXT,
    PLEDGE_TEXT_SHA256,
    PLEDGE_VERSION,
    PledgeState,
    accept_pledge,
    read_pledge,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/outbound-pledge", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
PledgeReader = Annotated[Principal, Depends(requires("org:read"))]
PledgeWriter = Annotated[Principal, Depends(requires("org:manage"))]


class OutboundPledgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    pledge_text: str
    text_sha256: str
    accepted_version: int | None
    accepted_at: datetime | None
    # True when the latest acceptance is of the current version — the gate's own answer.
    is_current: bool


class OutboundPledgeIn(BaseModel):
    """Echoes what the screen showed, so a page rendered before a new version cannot
    accept words the client never saw."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _out(state: PledgeState) -> OutboundPledgeOut:
    return OutboundPledgeOut(
        version=PLEDGE_VERSION,
        pledge_text=PLEDGE_TEXT,
        text_sha256=PLEDGE_TEXT_SHA256,
        accepted_version=state.accepted_version,
        accepted_at=state.accepted_at,
        is_current=state.is_current,
    )


@router.get(
    "",
    response_model=OutboundPledgeOut,
    openapi_extra=permission_meta("org:read"),
    summary="The no-cold-calls pledge and whether this account has accepted it",
)
async def read_outbound_pledge(session: Session, principal: PledgeReader) -> OutboundPledgeOut:
    assert principal.tenant_id is not None
    return _out(await read_pledge(session, tenant_id=principal.tenant_id))


@router.post(
    "",
    response_model=OutboundPledgeOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Accept the current no-cold-calls pledge",
    description=(
        "Records who accepted which version, when and from which address. Outbound calling "
        "needs a current acceptance; a new version needs accepting again."
    ),
)
async def accept_outbound_pledge(
    body: OutboundPledgeIn,
    request: Request,
    session: Session,
    principal: PledgeWriter,
) -> OutboundPledgeOut:
    assert principal.tenant_id is not None
    # `client_user_id` (D-587): the pledge is an undertaking by a named person at the
    # business, so an operator in a view-as session cannot give it for them.
    person = principal.client_user_id
    if person is None:
        raise ProblemError.business_rule(
            "outbound_pledge_is_the_clients_own_act",
            "The pledge has to be accepted by somebody at your own business.",
            remediation="Sign in to your own account and accept it there.",
        )
    ip = client_request_ip(request)
    acceptance_id: UUID = await accept_pledge(
        session,
        tenant_id=principal.tenant_id,
        user_id=person,
        version=body.version,
        text_sha256=body.text_sha256,
        ip=ip,
    )
    await write_audit(
        session,
        action="outbound_pledge.accepted",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="outbound_pledge_acceptance",
        object_id=str(acceptance_id),
        ip=ip,
        summary={"version": body.version, "text_sha256": body.text_sha256},
    )
    return _out(await read_pledge(session, tenant_id=principal.tenant_id))


__all__ = ["router"]
