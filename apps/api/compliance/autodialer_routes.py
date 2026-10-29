"""Where a client declares the numbers its automated calls come from (D-941).

    GET  /v1/compliance/autodialer-notice   what is declared, what is not, and from when it counts
    POST /v1/compliance/autodialer-notice   declare the numbers, or withdraw the declaration

**CLIENT-REALM, AND THERE IS NO ADMIN WRITE.** The declaration is the sender's statement
about its own numbers; a route that let somebody at Calevate record it would open the dial
gate on a statement the client never made. Support helping on the phone still has the client
press it. Operators read who has declared from the client-health board.

**`org:read` to look, `org:manage` to declare.** Looking stays open to a view-as session,
which is the session support is in when a client rings asking why nothing dials.

**A tenant with nothing on file is a 200 with `recorded: false`, never a 404.**
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.autodialer import (
    DECLARATION_TEXT,
    DECLARATION_TEXT_SHA256,
    DECLARATION_VERSION,
    MAX_DECLARED_CLIS,
    MAX_NOTICE_REFERENCE_CHARS,
    a2p_declaration_blocker,
    enforced_from,
    enforcement_active,
    outbound_agent_numbers,
    outbound_in_use,
    read_declaration,
    record_declaration,
    tenant_rented_numbers,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/autodialer-notice", tags=["compliance"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is not one.
Session = Annotated[AsyncSession, Depends(db)]
Reader = Annotated[Principal, Depends(requires("org:read"))]
Recorder = Annotated[Principal, Depends(requires("org:manage"))]


class DeclarationBlockerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    reason: str


class CallingNumberDeclarationOut(BaseModel):
    """What this account has declared, what it still has to, and from when it counts."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    state: str | None
    notified_on: date | None
    notice_reference: str | None
    declared_clis: list[str]
    #: False on a row recorded before D-941, which covers no dial.
    attested: bool
    #: The attestation version accepted on the latest row; a screen offers the current text
    #: again when it differs from `attestation_version`.
    attested_version: int | None
    #: The same predicate the dial gate uses: recorded, notified, attested, dated today or
    #: earlier (IST).
    effective: bool
    #: Every number rented for this account, to prefill the form.
    rented_numbers: list[str]
    #: Numbers bound to agents that place calls and missing from the declaration: a call from
    #: one is refused once the rule is in force.
    undeclared_clis: list[str]
    #: Whether this account has an agent that places calls. An answering-only account has
    #: nothing to declare.
    applies: bool
    #: The first IST day calls from undeclared numbers are refused, and whether it has come.
    enforced_from: date
    enforced: bool
    #: What the gate says about this account's agents' numbers, whether or not it is in
    #: force yet; None when they are all covered.
    blocker: DeclarationBlockerOut | None
    attestation_version: int
    attestation_text: str
    attestation_sha256: str


class CallingNumberDeclarationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_clis: list[str] = Field(default_factory=list, max_length=MAX_DECLARED_CLIS)
    #: The day the numbers were declared, in the client's calendar. A future date is
    #: accepted and counts from that day.
    notified_on: date
    #: The client's own handle for the declaration: a ticket number, a subject line.
    notice_reference: str | None = Field(default=None, max_length=MAX_NOTICE_REFERENCE_CHARS)
    attestation_version: int
    attestation_sha256: str = Field(min_length=64, max_length=64)
    #: A withdrawal is a NEW row, never an edit (hard rule 4).
    withdraw: bool = False


async def _out(session: AsyncSession, *, tenant_id: UUID) -> CallingNumberDeclarationOut:
    declaration = await read_declaration(session, tenant_id=tenant_id)
    agent_numbers = await outbound_agent_numbers(session)
    applies = await outbound_in_use(session)
    # The readiness row's question (`legal.readiness.a2p_readiness_row`), asked the same way.
    blocker = (
        await a2p_declaration_blocker(session, tenant_id=tenant_id, caller_ids=agent_numbers)
        if applies
        else None
    )
    return CallingNumberDeclarationOut(
        recorded=declaration.recorded,
        state=declaration.state,
        notified_on=declaration.notified_on,
        notice_reference=declaration.notice_reference,
        declared_clis=list(declaration.declared_clis),
        attested=declaration.attested,
        attested_version=declaration.attested_version,
        effective=declaration.is_effective(),
        rented_numbers=await tenant_rented_numbers(session),
        undeclared_clis=[n for n in agent_numbers if n not in declaration.declared_clis],
        applies=applies,
        enforced_from=enforced_from(),
        enforced=enforcement_active(),
        blocker=(
            None if blocker is None else DeclarationBlockerOut(rule=blocker[0], reason=blocker[1])
        ),
        attestation_version=DECLARATION_VERSION,
        attestation_text=DECLARATION_TEXT,
        attestation_sha256=DECLARATION_TEXT_SHA256,
    )


@router.get(
    "",
    response_model=CallingNumberDeclarationOut,
    openapi_extra=permission_meta("org:read"),
    summary="The calling numbers this account has declared",
    description=(
        "Automated calls may only come from numbers declared in advance to the telephone "
        "company that provides them. This says which numbers you have declared, which of "
        "your agents' numbers are missing, and the day from which a call from an undeclared "
        "number is refused. Incoming calls are never affected."
    ),
)
async def read_notice(session: Session, principal: Reader) -> CallingNumberDeclarationOut:
    assert principal.tenant_id is not None
    return await _out(session, tenant_id=principal.tenant_id)


@router.post(
    "",
    response_model=CallingNumberDeclarationOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Declare your calling numbers, or withdraw the declaration",
    description=(
        "Record the numbers your automated calls come from, the day you declared them and "
        "any reference you hold, and confirm the statement shown. Withdrawing files a new "
        "record rather than deleting the old one."
    ),
)
async def record_notice(
    body: CallingNumberDeclarationIn, request: Request, session: Session, principal: Recorder
) -> CallingNumberDeclarationOut:
    """Append the declaration, then read the account's position back from the database:
    the gate reads the LATEST row, so the honest answer is that same read."""
    assert principal.tenant_id is not None
    # `client_user_id`, never `user_id` (D-587): `recorded_by` is a `users.id`, and on a
    # view-as session `user_id` is an operator. A declaration with no client behind it is
    # not the sender's statement, so it is refused.
    actor = principal.client_user_id
    if actor is None:
        raise ProblemError.business_rule(
            "a2p_declaration_is_the_senders_own_act",
            "Somebody at your own business has to declare these numbers.",
            remediation="Sign in to your own account and declare them there.",
        )
    row_id = await record_declaration(
        session,
        tenant_id=principal.tenant_id,
        notified_on=body.notified_on,
        notice_reference=body.notice_reference,
        declared_clis=body.declared_clis,
        recorded_by=actor,
        attestation_version=body.attestation_version,
        attestation_sha256=body.attestation_sha256,
        withdraw=body.withdraw,
    )
    # In the same transaction as the row. Counts, never the numbers (hard rule 6).
    await write_audit(
        session,
        action="a2p_declaration.withdrawn" if body.withdraw else "a2p_declaration.recorded",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="autodialer_notice",
        object_id=str(row_id),
        ip=client_request_ip(request),
        summary={
            "notified_on": body.notified_on.isoformat(),
            "numbers": len(body.declared_clis),
            "attestation_version": body.attestation_version,
            "notice_reference_given": bool((body.notice_reference or "").strip()),
        },
    )
    return await _out(session, tenant_id=principal.tenant_id)


__all__ = ["CallingNumberDeclarationIn", "CallingNumberDeclarationOut", "router"]
