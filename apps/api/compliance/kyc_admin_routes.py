"""The operator's side of KYC (D-692): the review queue, the decision, and the override.

    GET  /v1/admin/kyc/reviews                                  records waiting for a reviewer
    GET  /v1/admin/tenants/{tenant_id}/kyc                      one client's record, files, pledge
    GET  /v1/admin/tenants/{tenant_id}/kyc/documents/{id}       one file, decrypted, as a download
    POST /v1/admin/tenants/{tenant_id}/kyc/review               approve or reject the manual path
    POST /v1/admin/tenants/{tenant_id}/kyc/digilocker-requirement   require or clear DigiLocker

`admin:tenants`, tenant in the PATH, and every write done inside `tenant_session(tenant_id)`,
the shape `carrier_application_routes` and `record_kyc_verification` share. Every action is
audited; every read of one client's rows records an admin tenant read.

NO STEP-UP, deliberately, matching `record_kyc_verification`: each of these is reversible on
the same screen by the same operator (a rejected client resubmits; a requirement is cleared
or set again), and the step-up census (`tests/authn_stepup_test.py`) reserves the gate for
acts that outlive the session or cannot be undone.

THE OWNER'S ID IS DELETED WHEN THE DECISION IS MADE (founder, 8 Oct 2026). The row is
marked purged in the decision's transaction and the object is deleted by a background task
after it commits, so a rolled-back decision never loses the file it was about.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import (
    KycRecord,
    read_kyc,
    record_kyc,
    set_digilocker_requirement,
)
from apps.api.compliance.kyc_documents import (
    current_documents,
    delete_quietly,
    open_document,
    purge_owner_id,
)
from apps.api.compliance.kyc_routes import KycDocumentOut, documents_out
from apps.api.compliance.outbound_pledge import PLEDGE_VERSION, read_pledge
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/admin", tags=["admin"])

AdminSession = Annotated[AsyncSession, Depends(admin_db)]
KycOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: The business certificate's kind -> the registry document a verified operator record
#: names (`compliance.models.KYC_DOCUMENT_KINDS`).
_REGISTRY_KIND = {"gst": "gstin", "incorporation": "cin", "udyam": "udyam"}


class KycReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str
    slug: str
    status: str
    kyc_path: str | None
    # Which owner ID the client used — `aadhaar` or `pan` — so a reviewer knows what to
    # expect before opening the file.
    owner_id_type: str | None
    digilocker_required: bool
    submitted_at: datetime | None


#: The directory, through the admin GUC (organizations only, migration b57e2f9c4a13).
_DIRECTORY = "SELECT id, name, slug FROM organizations WHERE deleted_at IS NULL ORDER BY created_at"
_WAITING = (
    "SELECT status, kyc_path, owner_id_type, digilocker_required, submitted_at "
    "FROM kyc_records WHERE tenant_id = :tid AND status IN ('submitted', 'in_review')"
)


@router.get(
    "/kyc/reviews",
    response_model=list[KycReviewItem],
    openapi_extra=permission_meta("admin:tenants"),
    summary="Clients whose identity verification is waiting for a reviewer",
)
async def kyc_review_queue(
    session: AdminSession,
    principal: KycOperator,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[KycReviewItem]:
    """Built the way `admin/holds.held_tenants` is: the admin GUC lists organizations, and
    each tenant's record is read under its OWN RLS session, so no policy is widened to
    let an admin session read `kyc_records`. Oldest submission first."""
    del principal
    directory = (await session.execute(text(_DIRECTORY))).all()
    items: list[KycReviewItem] = []
    for org in directory:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            row = (await scoped.execute(text(_WAITING), {"tid": tenant_id})).first()
        if row is None:
            continue
        items.append(
            KycReviewItem(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                status=str(row[0]),
                kyc_path=row[1],
                owner_id_type=row[2],
                digilocker_required=bool(row[3]),
                submitted_at=row[4],
            )
        )
    items.sort(
        key=lambda item: (
            item.submitted_at is None,
            item.submitted_at.isoformat() if item.submitted_at else "",
        )
    )
    return items[:limit]


class AdminKycOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    recorded: bool
    status: str | None
    kyc_path: str | None
    entity_type: str | None
    legal_business_name: str | None
    gst_registered: bool | None
    gstin: str | None
    owner_name: str | None
    owner_id_type: str | None
    owner_id_masked: str | None
    verified_name: str | None
    name_match: bool | None
    verification_provider: str | None
    verification_reference: str | None
    rejection_reason: str | None
    submitted_at: datetime | None
    verified_at: datetime | None
    is_verified: bool
    digilocker_required: bool
    digilocker_required_reason: str | None
    digilocker_required_at: datetime | None
    digilocker_verified_at: datetime | None
    digilocker_outstanding: bool
    documents: list[KycDocumentOut]
    pledge_accepted_version: int | None
    pledge_accepted_at: datetime | None
    pledge_current_version: int


def _admin_out(
    tenant_id: UUID,
    record: KycRecord,
    documents: list[KycDocumentOut],
    pledge_version: int | None,
    pledge_at: datetime | None,
) -> AdminKycOut:
    return AdminKycOut(
        tenant_id=tenant_id,
        recorded=record.recorded,
        status=record.status,
        kyc_path=record.kyc_path,
        entity_type=record.entity_type,
        legal_business_name=record.legal_business_name,
        gst_registered=record.gst_registered,
        gstin=record.gstin,
        owner_name=record.signatory_name,
        owner_id_type=record.owner_id_type,
        owner_id_masked=record.owner_id_masked,
        verified_name=record.verified_name,
        name_match=record.name_match,
        verification_provider=record.verification_provider,
        verification_reference=record.verification_reference,
        rejection_reason=record.rejection_reason,
        submitted_at=record.submitted_at,
        verified_at=record.verified_at,
        is_verified=record.is_verified,
        digilocker_required=record.digilocker_required,
        digilocker_required_reason=record.digilocker_required_reason,
        digilocker_required_at=record.digilocker_required_at,
        digilocker_verified_at=record.digilocker_verified_at,
        digilocker_outstanding=record.digilocker_outstanding,
        documents=documents,
        pledge_accepted_version=pledge_version,
        pledge_accepted_at=pledge_at,
        pledge_current_version=PLEDGE_VERSION,
    )


async def _load(tenant_id: UUID) -> AdminKycOut:
    async with tenant_session(tenant_id) as scoped:
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        record = await read_kyc(scoped, tenant_id=tenant_id)
        documents = documents_out(await current_documents(scoped, tenant_id=tenant_id))
        pledge = await read_pledge(scoped, tenant_id=tenant_id)
    return _admin_out(tenant_id, record, documents, pledge.accepted_version, pledge.accepted_at)


@router.get(
    "/tenants/{tenant_id}/kyc",
    response_model=AdminKycOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's identity verification, documents on file and pledge",
)
async def read_tenant_kyc(
    tenant_id: UUID, session: AdminSession, request: Request, principal: KycOperator
) -> AdminKycOut:
    out = await _load(tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return out


@router.get(
    "/tenants/{tenant_id}/kyc/documents/{document_id}",
    response_class=Response,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Download one KYC file, decrypted, for review",
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_kyc_document(
    tenant_id: UUID,
    document_id: UUID,
    request: Request,
    principal: KycOperator,
) -> Response:
    """Decrypted in memory and returned as an attachment; never via a presigned URL,
    because the stored object is ciphertext and the key is ours. The view is audited on
    the tenant's own session, so a file is never handed out without its audit row."""
    from apps.workers.storage import read_kb_object

    async with tenant_session(tenant_id) as scoped:
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        row = next(
            (
                doc
                for doc in (await current_documents(scoped, tenant_id=tenant_id)).values()
                if doc.id == document_id
            ),
            None,
        )
        if row is None or row.purged_at is not None:
            raise ProblemError.not_found("Document")
        ciphertext = await read_kb_object(row.object_key)
        if ciphertext is None:
            raise ProblemError.not_found("Document")
        plaintext = open_document(
            tenant_id=tenant_id, document_id=row.id, envelope=row.envelope(ciphertext)
        )
        await write_audit(
            scoped,
            action="kyc.document_viewed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kyc_document",
            object_id=str(document_id),
            ip=client_request_ip(request),
            summary={"slot": row.slot, "kind": row.kind},
        )
    return Response(
        content=plaintext,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="kyc-{row.slot}-{row.id}.'
            f'{_SUFFIX.get(row.content_type, "bin")}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


_SUFFIX = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


class KycReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approve", "reject"]
    # The public registry number the reviewer checked (GSTIN / CIN / LLPIN / Udyam).
    # Defaults to the GSTIN on file for a GST-registered business.
    document_ref: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


@router.post(
    "/tenants/{tenant_id}/kyc/review",
    response_model=AdminKycOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Approve or reject a client's identity verification",
    description=(
        "Approving records the business as verified against its certificate and registry "
        "number; rejecting needs a reason the client is shown. Either way the owner's ID "
        "file is deleted and only its type and masked number are kept."
    ),
)
async def review_kyc(
    tenant_id: UUID,
    body: KycReviewIn,
    session: AdminSession,
    request: Request,
    principal: KycOperator,
    tasks: BackgroundTasks,
) -> AdminKycOut:
    assert principal.user_id is not None
    async with tenant_session(tenant_id) as scoped:
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        record = await read_kyc(scoped, tenant_id=tenant_id)
        if record.status not in ("submitted", "in_review"):
            raise ProblemError.business_rule(
                "kyc_not_awaiting_review",
                f"This client's verification is {record.status or 'not started'}, not "
                "waiting for review.",
                remediation="Refresh the page; it may already have been decided.",
            )
        documents = await current_documents(scoped, tenant_id=tenant_id)
        business = documents.get("business")
        if body.decision == "approve":
            if business is None:
                raise ProblemError.business_rule(
                    "kyc_business_document_missing",
                    "There is no business certificate on file to approve against.",
                    remediation="Reject with a reason asking for the certificate.",
                )
            document_kind = _REGISTRY_KIND[business.kind]
            if document_kind == "cin" and record.entity_type == "llp":
                document_kind = "llpin"
            document_ref = body.document_ref or (record.gstin if business.kind == "gst" else None)
            if not document_ref:
                raise ProblemError(
                    kind="validation",
                    code="kyc_document_required",
                    title="Enter the registry number you checked",
                    detail="Approving needs the CIN, LLPIN or Udyam number from the certificate.",
                    remediation="Type the number from the certificate and approve again.",
                )
            await record_kyc(
                scoped,
                tenant_id=tenant_id,
                status="verified",
                entity_type=record.entity_type,
                document_kind=document_kind,
                document_ref=document_ref,
                evidence_ref=f"kyc_document:{business.id}",
                verified_by_admin_id=principal.user_id,
            )
        else:
            if not body.reason:
                raise ProblemError(
                    kind="validation",
                    code="kyc_rejection_reason_required",
                    title="A rejection must say why",
                    detail="The client is shown this reason and needs it to fix the problem.",
                    remediation="Say what was missing or wrong.",
                )
            await record_kyc(
                scoped, tenant_id=tenant_id, status="rejected", rejection_reason=body.reason
            )
        held_owner_id = await purge_owner_id(scoped, tenant_id=tenant_id)
        await write_audit(
            scoped,
            action="kyc.reviewed",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kyc_record",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={
                "decision": body.decision,
                "owner_id_type": record.owner_id_type,
                "owner_id_file_deleted": held_owner_id is not None,
            },
        )
    if held_owner_id is not None:
        tasks.add_task(delete_quietly, [held_owner_id])
    return await _load(tenant_id)


class DigiLockerRequirementIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    required: bool
    # Why — shown to operators and recorded; required when requiring.
    reason: str | None = Field(default=None, max_length=500)


@router.post(
    "/tenants/{tenant_id}/kyc/digilocker-requirement",
    response_model=AdminKycOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Require (or stop requiring) a DigiLocker verification for this client",
    description=(
        "Requiring blocks this client's OUTBOUND calls until a DigiLocker verification "
        "completes after this moment; inbound calls are unaffected. Clearing lifts it."
    ),
)
async def set_tenant_digilocker_requirement(
    tenant_id: UUID,
    body: DigiLockerRequirementIn,
    session: AdminSession,
    request: Request,
    principal: KycOperator,
) -> AdminKycOut:
    assert principal.user_id is not None
    if body.required and not body.reason:
        raise ProblemError(
            kind="validation",
            code="kyc_digilocker_reason_required",
            title="Say why DigiLocker is required",
            detail="The reason is recorded with the requirement.",
            remediation="Add a short reason and save again.",
        )
    async with tenant_session(tenant_id) as scoped:
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        await set_digilocker_requirement(
            scoped,
            tenant_id=tenant_id,
            required=body.required,
            reason=body.reason,
            admin_id=principal.user_id,
        )
        await write_audit(
            scoped,
            action="kyc.digilocker_required" if body.required else "kyc.digilocker_cleared",
            actor=principal,
            tenant_id=tenant_id,
            object_type="kyc_record",
            object_id=str(tenant_id),
            ip=client_request_ip(request),
            summary={"required": body.required},
        )
    return await _load(tenant_id)


__all__ = ["router"]
