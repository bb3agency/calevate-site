"""The client's own surface for the ordinary-DID confirmation.

`campaigns/sender_attestation.py` holds the reasoning. These three endpoints are the only
way a row is ever written: there is no admin route that attests on a client's behalf, and
that absence is the point — the direction binds the sender, so an attestation Calevate
recorded for them would evidence nothing about what they accepted.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.sender_attestation import (
    SENDER_STATEMENT,
    SENDER_STATEMENT_VERSION,
    latest_attestation,
    record_attestation,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.ownership import assert_visible

router = APIRouter(prefix="/v1/numbers", tags=["campaigns"])

Session = Annotated[AsyncSession, Depends(db)]
# `org:manage`, the same permission that buys a number. Accepting a regulatory obligation
# on the business's behalf is not something a seat with agent-editing rights should do.
NumberOwner = Annotated[Principal, Depends(requires("org:manage"))]

# The GET is a read, and read-only impersonation must be able to reach it (D-22). The
# POST that records the confirmation keeps `org:manage`.
NumberViewer = Annotated[Principal, Depends(requires("org:read"))]


class SenderAttestationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Whether this number may carry service and transactional campaigns today. False for a
    #: number whose attestation predates the current wording — the client is asked again
    #: rather than held to words they did not read.
    attested: bool
    #: True only where the confirmation is the thing standing between this number and an
    #: outbound campaign, so the console does not offer it on a 140 or 160 number that needs
    #: no confirmation at all.
    applicable: bool
    statement: str
    statement_version: str


class SenderAttestationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Echoed back from the page the person read, and compared before the write. A console
    #: left open across a wording change must reload.
    statement_version: str


def _tenant_of(principal: Principal) -> UUID:
    """`Principal.tenant_id` is Optional for the admin realm; this router is client-only."""
    if principal.tenant_id is None:
        raise ProblemError.not_found("Number")
    return principal.tenant_id


def _acting_client_user(principal: Principal) -> UUID:
    """`client_user_id`, so `attested_by` can only ever hold a `users.id` (D-587).

    Unreachable behind `assert_view_as_may`, and asserted anyway: this is what makes the
    foreign key impossible to violate rather than merely un-violated.
    """
    user_id = principal.client_user_id
    if user_id is None:
        raise ProblemError.business_rule(
            "sender_attestation_requires_the_client",
            "Only someone signed in to this account can confirm this.",
            remediation="Ask the account owner to confirm it from their own console.",
        )
    return user_id


async def _series_of(session: AsyncSession, number_id: UUID) -> str:
    row = (
        await session.execute(
            text("SELECT series FROM phone_numbers WHERE id = :id"), {"id": number_id}
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Number")
    return str(row[0])


@router.get(
    "/{number_id}/sender-attestation",
    response_model=SenderAttestationOut,
    openapi_extra=permission_meta("org:read"),
    summary="Whether this number carries the outbound-sender confirmation",
)
async def read(number_id: UUID, session: Session, principal: NumberViewer) -> SenderAttestationOut:
    """What this number's confirmation says today, and whether it is even needed."""
    await assert_visible(session, "phone_number", number_id)
    state = await latest_attestation(session, phone_number_id=number_id)
    return SenderAttestationOut(
        attested=state.current,
        applicable=await _series_of(session, number_id) == "standard",
        statement=SENDER_STATEMENT,
        statement_version=SENDER_STATEMENT_VERSION,
    )


@router.post(
    "/{number_id}/sender-attestation",
    response_model=SenderAttestationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Confirm this business is the sender and accepts the obligation",
)
async def attest(
    number_id: UUID,
    body: SenderAttestationIn,
    request: Request,
    session: Session,
    principal: NumberOwner,
) -> SenderAttestationOut:
    """Record that this business is the sender and accepts the obligation.

    Refused on a 140 or 160 number rather than stored harmlessly: a row against a number
    that needs no exception would later read as though an exception had been needed, and the
    ledger's value is that every row in it means the same thing.
    """
    # TRAI binds the SENDER. An operator accepting on the client's behalf would record a
    # statement the client never made, so the act is withheld from view-as
    # (`rbac.VIEW_AS_WITHHELD_ACTS`) before anything is written.
    assert_view_as_may(principal, "compliance.outbound_sender_attestation")
    await assert_visible(session, "phone_number", number_id)
    series = await _series_of(session, number_id)
    if series != "standard":
        raise ProblemError.business_rule(
            "sender_attestation_not_applicable",
            f"A {series} number is a registered voice header, so it needs no confirmation.",
            remediation="This number can already carry service and transactional campaigns.",
        )
    await record_attestation(
        session,
        tenant_id=_tenant_of(principal),
        phone_number_id=number_id,
        user_id=_acting_client_user(principal),
        statement_version=body.statement_version,
    )
    await write_audit(
        session,
        action="outbound_sender.attested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={"statement_version": SENDER_STATEMENT_VERSION},
    )
    return SenderAttestationOut(
        attested=True,
        applicable=True,
        statement=SENDER_STATEMENT,
        statement_version=SENDER_STATEMENT_VERSION,
    )


@router.delete(
    "/{number_id}/sender-attestation",
    response_model=SenderAttestationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Withdraw the outbound-sender confirmation for this number",
)
async def withdraw(
    number_id: UUID,
    request: Request,
    session: Session,
    principal: NumberOwner,
) -> SenderAttestationOut:
    """Step back out of the obligation. A new row, never a deletion (hard rule 4).

    Takes no statement version: refusing a withdrawal because the page is stale would hold
    someone to an obligation they are trying to leave.
    """
    await assert_visible(session, "phone_number", number_id)
    await record_attestation(
        session,
        tenant_id=_tenant_of(principal),
        phone_number_id=number_id,
        user_id=_acting_client_user(principal),
        statement_version=SENDER_STATEMENT_VERSION,
        withdraw=True,
    )
    await write_audit(
        session,
        action="outbound_sender.withdrawn",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="phone_number",
        object_id=str(number_id),
        ip=client_request_ip(request),
        summary={},
    )
    return SenderAttestationOut(
        attested=False,
        applicable=await _series_of(session, number_id) == "standard",
        statement=SENDER_STATEMENT,
        statement_version=SENDER_STATEMENT_VERSION,
    )
