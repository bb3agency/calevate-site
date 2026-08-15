"""Admin-realm endpoints for a TENANT erasure and its certificate (FLOWS §9, SEC-COMP §4).

The offboarding trigger SURFACES §1 has promised since v1.0 ("plan changes … cap raises,
suspend/reactivate, **offboarding trigger**"), and the writer `organizations.deleted_at`
never had. Read `compliance/tenant_erasure.py` first: it argues the state model, why this
is not a `deletion_requests` row, and what the two keys on the write are for.

ADMIN REALM, not client. A client cannot erase itself for the same reason it cannot clear
its own suspension (`web/src/lib/api/commercials.ts` says this about the lifecycle
switch): the instruction is the end of a commercial relationship, it is irreversible, and
it is executed by us. A client exercising an individual's §12 right against their own
caller records is the OTHER surface, `/v1/compliance/deletion-requests`, and the two are
kept apart deliberately.

Three shapes worth explaining before someone tidies them:

- **Nothing here goes through `admin.service.tenant_exists`.** That predicate answers
  "is this a LIVE organization" and treats a soft-deleted tenant as absent, which is
  correct for every other route in the admin realm and exactly wrong for the one surface
  whose subject is the deletion. If these routes used it, the certificate would become
  unreachable at the instant the erasure that produced it succeeded.
  `tenant_erasure.assert_erasable` is the predicate for the WRITE and it refuses an
  already-erased tenant by name; the reads refuse nothing.
- **The write declares `admin:tenants` and additionally checks `ops:manage` + a step-up.**
  Precedent: `admin/routes.py::record_commercial_terms`. The role check runs FIRST — a
  step-up header is a confirmation, not an authorisation, so an operator who may not do
  this at all is told that rather than asked to confirm. The declared permission is in
  `MUTATING_PERMISSIONS`, so D-22 refuses it to an impersonating admin; a read-only "view
  as client" session must never be able to erase the client it is viewing.
- **A duplicate is a 200, not a 409.** The caller's intent is already satisfied by the
  erasure in flight. `already_open` is on the body so a screen can say so.

The audit row is written by the FILING, in the same transaction as the request row and
the queued job — "who set the most destructive operation in the product in motion, and
why". The EXECUTION's durable record is the proof on the request row, not a second audit
entry, which is the same division `execute_deletion_request` uses: the certificate is the
append-only artifact of an erasure, and no worker in this repo writes to the hash chain
(the chain lock is held to COMMIT, and a worker holding it across a tenant-wide erasure
would queue every audit writer in the fleet behind it).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from apps.api.compliance import tenant_erasure
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta, role_has
from apps.api.core.stepup import require_step_up
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/erasure", tags=["admin"])

# `core.deps.db` resolves the tenant from the PRINCIPAL, and an admin principal has
# none — so every route here opens `tenant_session(tenant_id)` on the path parameter by
# hand, which is the house pattern for admin-realm work on one client (`admin/routes.py`
# does it in every mutation) and the only shape D-22 leaves callable.
#
# `audit_log` is not tenant-policied (registry.RLS_EXEMPT_TENANT_COLUMNS), so the audit
# row rides that same tenant transaction rather than a second session.

Eraser = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]
# `org:read` rather than `admin:tenants`: D-22 forbids gating a GET on a mutating
# permission, and an operator who may not CAUSE an erasure should still be able to
# CONFIRM one. The certificate carries counts and timestamps and no personal data.
CertificateReader = Annotated[Principal, Depends(requires("org:read", realm="admin"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantErasureIn(Strict):
    """`extra="forbid"` so a caller cannot smuggle a narrower scope into an operation
    that honours none. The worker erases everything it can reach for the tenant."""

    # Goes into the audit row and onto the request row verbatim. Required, and for the
    # reason the lifecycle switch requires one on a suspend: "why was this client's data
    # destroyed" is a question somebody will have to answer years later, and an empty
    # answer is the ticket nobody can close.
    reason: str = Field(min_length=3, max_length=500)


class TenantErasureScopeOut(Strict):
    """WHAT was erased, by count. Never by id, never by number.

    Every field is NULLABLE AND REQUIRED. Nullable because absent is not zero: a proof
    written by a worker that did not record a fact must not be rendered as the claim
    that the fact was zero, and hard rule 4 forbids back-filling the row to make it so.
    Required — no Pydantic default — because a field with a default generates an OPTIONAL
    TypeScript property, and this repo has been bitten by that four times.
    """

    calls_erased: int | None
    transcript_turns_erased: int | None
    call_extractions_erased: int | None
    leads_erased: int | None
    recordings_destroyed: int | None
    recordings_within_trai_floor: int | None
    webhook_bodies_erased: int | None


class TenantErasureLimitationOut(Strict):
    """One thing this erasure did NOT destroy, and the rule that stopped it."""

    what: str
    outcome: str
    why: str
    authority: str


class TenantErasureProofOut(Strict):
    """The certificate. Carries no personal data by construction: an organisation id,
    timestamps, counts and plain statements of what was done to each store."""

    tenant_id: str
    executed_at: str
    scope: TenantErasureScopeOut
    # The instant the LAST deferred recording is destroyed on, as the worker recorded it.
    # A string rather than a datetime, for the reason the per-subject certificate gives:
    # it is passed through from a durable JSON document this API does not own, and
    # re-parsing it here would turn a proof written by an older worker into a 500.
    recording_hold_until: str | None
    actions: dict[str, str]
    engine_deletion: str
    not_erased: list[TenantErasureLimitationOut]
    limitations: list[str]
    limitations_version: str


class TenantErasureOut(Strict):
    """The response model IS the output whitelist (BACKEND-PATTERNS §1)."""

    request_id: UUID
    tenant_id: UUID
    status: Literal["pending", "completed"]
    reason: str
    requested_at: datetime
    completed_at: datetime | None
    proof: TenantErasureProofOut | None
    limitations: list[str]


class TenantErasureAcceptedOut(TenantErasureOut):
    already_open: bool


def _out(record: tenant_erasure.TenantErasureRecord) -> dict[str, Any]:
    return {
        "request_id": record.id,
        "tenant_id": record.tenant_id,
        "status": record.status,
        "reason": record.reason,
        "requested_at": record.requested_at,
        "completed_at": record.completed_at,
        "proof": tenant_erasure.certificate(record.proof),
        "limitations": list(tenant_erasure.TENANT_ERASURE_LIMITATIONS),
    }


@router.post(
    "",
    response_model=TenantErasureAcceptedOut,
    status_code=201,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Erase this client's data — irreversible, superadmin, step-up confirmed",
    description=(
        "Executes the tenant-level erasure FLOWS §9 ends the offboarding with, and is "
        "the only thing in this product that sets `organizations.deleted_at`. After it "
        "completes the client is gone from every screen, no membership resolves, no "
        "dial is permitted and no invitation can be issued or redeemed. It cannot be "
        "undone. The account must ALREADY be closed (`churned`) — 409 `tenant_not_closed` "
        "otherwise, and 409 `tenant_already_erased` if it has been erased before. Needs "
        "a superadmin AND the header `X-Confirm-Action: erase_tenant_data:<tenant_id>`. "
        "Filing twice returns 200 with `already_open: true` rather than erasing twice. "
        "Export the client's data BEFORE calling this: nothing here produces the bundle."
    ),
)
async def request_tenant_erasure(
    tenant_id: UUID,
    payload: TenantErasureIn,
    request: Request,
    response: Response,
    principal: Eraser,
    x_confirm_action: Annotated[str | None, Header()] = None,
) -> TenantErasureAcceptedOut:
    """Both keys, then the row, the job and the audit entry in one transaction.

    THE ROLE CHECK RUNS FIRST and the step-up second, the order
    `record_commercial_terms` established: a confirmation is not an authorisation, so an
    operator who may not do this at all is told so rather than asked to type a header.
    Both run before `assert_erasable` reads anything, so a caller who is refused knows
    nothing about the tenant they named — including whether it exists.

    `ops:manage` is the superadmin marker `core/rbac.py`'s role table uses ("the
    dangerous switches … each of which additionally needs step-up confirmation"). It is
    checked rather than declared, because declaring it would take the STATUS read below
    away from the operators whose job is offboarding.
    """
    if principal.role is None or not role_has(principal.role, "ops:manage"):
        raise ProblemError.forbidden(
            "Erasing a client's data needs a superadmin. Closing the account does not."
        )
    require_step_up(x_confirm_action, tenant_erasure.tenant_erasure_confirmation(tenant_id))

    async with tenant_session(tenant_id) as scoped:
        record = await tenant_erasure.request_tenant_erasure(
            scoped, tenant_id=tenant_id, reason=payload.reason
        )
        # LAST, INSIDE THE SAME TRANSACTION as the request row and the queued job —
        # the shape `invite_member` above argues, and for a sharper version of the same
        # reason. There must be no state in which the most destructive operation in the
        # product was set in motion with nothing saying who set it in motion.
        # `write_audit` appends in the caller's transaction by design and `audit_log` is
        # not tenant-RLS'd, so the tenant session is the right one to write it on.
        #
        # A deduplicated ask is audited too: two operators filing the same offboarding
        # an hour apart is a fact about the history, and "who asked, and what were they
        # told?" has an answer either way.
        await write_audit(
            scoped,
            action="tenant.erasure_requested",
            actor=principal,
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            ip=request.client.host if request.client else None,
            summary={
                "request_id": str(record.id),
                "reason": payload.reason,
                "already_open": record.already_open,
            },
        )

    if record.already_open:
        response.status_code = 200
    return TenantErasureAcceptedOut(**_out(record), already_open=record.already_open)


@router.get(
    "",
    response_model=list[TenantErasureOut],
    openapi_extra=permission_meta("org:read"),
    summary="This client's erasure record and its certificate — readable after erasure",
)
async def list_tenant_erasures(
    tenant_id: UUID,
    _: CertificateReader,
    limit: int = Query(default=tenant_erasure.MAX_LIST, ge=1, le=tenant_erasure.MAX_LIST),
) -> list[TenantErasureOut]:
    """Newest first, and deliberately still answerable once the tenant is erased.

    `tenant_id` is in the path and RLS scopes the read; it is not named in the SQL. The
    parameter is what makes the caller's scope explicit at the call site and is what the
    session is opened on.
    """
    async with tenant_session(tenant_id) as scoped:
        records = await tenant_erasure.list_tenant_erasures(scoped, limit=limit)
    return [TenantErasureOut(**_out(record)) for record in records]


@router.get(
    "/{request_id}",
    response_model=TenantErasureOut,
    openapi_extra=permission_meta("org:read"),
    summary="One erasure record and its certificate",
)
async def read_tenant_erasure(
    tenant_id: UUID,
    request_id: UUID,
    _: CertificateReader,
) -> TenantErasureOut:
    """RLS scopes the lookup, so another tenant's record is not found — the same answer
    a nonexistent id gets, deliberately."""
    async with tenant_session(tenant_id) as scoped:
        record = await tenant_erasure.get_tenant_erasure(scoped, request_id=request_id)
    return TenantErasureOut(**_out(record))


__all__ = [
    "TenantErasureAcceptedOut",
    "TenantErasureIn",
    "TenantErasureLimitationOut",
    "TenantErasureOut",
    "TenantErasureProofOut",
    "TenantErasureScopeOut",
    "router",
]
