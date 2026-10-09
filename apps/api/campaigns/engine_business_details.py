"""A client's business details, sent to its own ThinnestAI workspace (D-693).

India's numbering authority needs the business behind a number, so ThinnestAI rents an
Indian number only once the workspace's business details are approved (`thinnest-findings/
mirror/snapshots/2026-10-08/pages/api-reference/phone-numbers/send-business-details.md:7`).
With one workspace per client, those are the CLIENT's details, and the numbers are rented in
its own name.

What is sent is the KYC lane's submission bundle (`compliance/kyc.
numbering_submission_bundle`, D-692): the verified legal name, the GST flag, and the one
business certificate the client uploaded, in the vendor's `documentKind` vocabulary. Nothing
is sent for a record that is not verified, so no application in a client's name rests on
unchecked paperwork.

When it is sent: as soon as both the workspace is active and the KYC record is verified
(whichever happens second queues it), when the client or an admin resubmits after a
rejection, and automatically when an approved application expires. The vendor keeps one
live application per workspace: a send while one is being checked or after approval is a
409, which we read back rather than treat as a failure (:7).

The status is the vendor's; `tenant_engine_workspaces.business_*` is our last reading of it,
refreshed by the daily sweep and on every screen that asks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.kyc import NumberingSubmission, numbering_submission_bundle
from apps.api.compliance.kyc_documents import current_documents, open_document
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_numbers import (
    BusinessDetails,
    BusinessDocument,
    thinnest_numbers,
)
from apps.api.engine.thinnest_workspace import workspace_not_provisioned
from apps.api.engine.vendor_http import EngineRejectedError
from apps.api.reliability.service import enqueue_outbox
from apps.api.tenancy.engine_workspace import engine_has_workspaces, resolve_workspace

log = get_logger(__name__)

SUBMIT_JOB: Final = "submit_engine_business_details"

#: Writes an audit row for a send, in the session that records the vendor's answer.
AuditSent = Callable[[AsyncSession, BusinessDetails], Awaitable[None]]

#: States in which a new send is what moves the application on. Not `suspended` (approval
#: withdrawn): the vendor documents a resend after `rejected` (corrected in place) and
#: `expired` (a new application) and none for a suspension, so the client is told to
#: contact us (`phone-numbers/send-business-details.md:7`, `get-business-details.md:430-434`).
RESUBMITTABLE: Final = frozenset({"none", "draft", "rejected", "expired"})

#: The vendor's review note is a sentence about our client's paperwork; it is shown to the
#: client and the admin, bounded like the column that holds it.
_NOTE_MAX: Final = 2000


def _kyc_not_ready() -> ProblemError:
    return ProblemError.business_rule(
        "business_details_kyc_not_verified",
        "Your business has to be verified before its details can be sent for phone numbers.",
        remediation="Finish Verify your business first. The details are sent automatically.",
    )


async def store_business_details(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    details: BusinessDetails,
    document_id: UUID | None = None,
) -> None:
    """Record the vendor's answer as our last reading, in the caller's tenant session."""
    await session.execute(
        text(
            "UPDATE tenant_engine_workspaces SET business_status = :status, "
            "business_can_rent = :can_rent, business_review_note = :note, "
            "business_submitted_at = COALESCE(:submitted, business_submitted_at), "
            "business_checked_at = now(), "
            "business_document_id = COALESCE(:doc, business_document_id), updated_at = now() "
            "WHERE tenant_id = :tid"
        ),
        {
            "status": details.status,
            "can_rent": details.can_rent,
            "note": (details.review_note or None) and details.review_note[:_NOTE_MAX],
            "submitted": details.submitted_at,
            "doc": document_id,
            "tid": tenant_id,
        },
    )


async def queue_business_details_submission(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Owe this tenant a submission, in the caller's transaction. False off an engine
    without customer workspaces. The job decides whether there is anything to send."""
    if not engine_has_workspaces():
        return False
    await enqueue_outbox(session, job=SUBMIT_JOB, payload={"tenant_id": str(tenant_id)})
    return True


@dataclass(frozen=True, slots=True)
class _Prepared:
    workspace: str
    bundle: NumberingSubmission
    document: BusinessDocument


async def _prepare(tenant_id: UUID) -> _Prepared:
    from apps.workers.storage import read_kb_object

    async with tenant_session(tenant_id) as session:
        workspace = await resolve_workspace(session, tenant_id)
        if workspace is None:
            raise workspace_not_provisioned()
        bundle = await numbering_submission_bundle(session, tenant_id=tenant_id)
        if bundle is None:
            raise _kyc_not_ready()
        row = (await current_documents(session, tenant_id=tenant_id)).get("business")
    if row is None or row.id != bundle.document_id:
        raise _kyc_not_ready()
    ciphertext = await read_kb_object(bundle.object_key)
    if ciphertext is None:
        raise ProblemError.business_rule(
            "business_document_unavailable",
            "The business certificate on file could not be read.",
            remediation="Upload the certificate again under Verify your business.",
        )
    data = open_document(tenant_id=tenant_id, document_id=row.id, envelope=row.envelope(ciphertext))
    return _Prepared(
        workspace=workspace,
        bundle=bundle,
        document=BusinessDocument(
            filename=bundle.filename, content_type=bundle.content_type, data=data
        ),
    )


async def submit_business_details(
    tenant_id: UUID, *, audit: AuditSent | None = None
) -> BusinessDetails:
    """Send the client's verified details to its own workspace, and record the answer.

    Opens its own sessions and holds none across the vendor call. A 409 means an application
    is already being checked or approved: the current one is read back and recorded.
    `audit` writes the caller's audit row last in the transaction that records the answer,
    so a send is audited only once it happened and the two commit together.
    """
    prepared = await _prepare(tenant_id)
    numbers = thinnest_numbers()
    try:
        details = await numbers.send_business_details(
            prepared.workspace,
            business_name=prepared.bundle.legal_business_name,
            gst_registered=prepared.bundle.gst_registered,
            document_kind=prepared.bundle.document_kind,
            document=prepared.document,
        )
    except EngineRejectedError as exc:
        if exc.vendor_status != 409:
            raise
        details = await numbers.business_details(prepared.workspace)
    async with tenant_session(tenant_id) as session:
        await store_business_details(
            session,
            tenant_id=tenant_id,
            details=details,
            document_id=prepared.bundle.document_id,
        )
        if audit is not None:
            await audit(session, details)
    log.info(
        "engine_business_details_sent",
        extra={"tenant_id": str(tenant_id), "status": details.status},
    )
    return details


async def refresh_business_details(tenant_id: UUID) -> BusinessDetails:
    """Read the application's status from the vendor and record it."""
    async with tenant_session(tenant_id) as session:
        workspace = await resolve_workspace(session, tenant_id)
    if workspace is None:
        raise workspace_not_provisioned()
    details = await thinnest_numbers().business_details(workspace)
    async with tenant_session(tenant_id) as session:
        await store_business_details(session, tenant_id=tenant_id, details=details)
    return details


__all__ = [
    "RESUBMITTABLE",
    "SUBMIT_JOB",
    "AuditSent",
    "queue_business_details_submission",
    "refresh_business_details",
    "store_business_details",
    "submit_business_details",
]
