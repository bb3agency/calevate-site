"""An operator's decision on a client's identity verification — one implementation behind
the KYC review screen (`POST /v1/admin/tenants/{tenant_id}/kyc/review`) and the admin
assistant's `admin_kyc_review` action (D-698).

The caller opens the tenant's session, writes the `kyc.reviewed` audit row with the
outcome below, and schedules the owner-ID file deletion after commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.compliance.kyc import KycRecord, read_kyc, record_kyc, record_owner_pan_check
from apps.api.compliance.kyc_documents import (
    PendingDeletion,
    current_documents,
    request_owner_id_deletion,
)
from apps.api.core.errors import ProblemError

#: The public registry a business certificate is checked against, by certificate kind.
REGISTRY_KIND: Final[dict[str, str]] = {"gst": "gstin", "incorporation": "cin", "udyam": "udyam"}

KycDecision = Literal["approve", "reject"]


@dataclass(frozen=True, slots=True)
class KycReviewOutcome:
    record: KycRecord
    held_owner_id: PendingDeletion | None


async def assert_awaiting_review(scoped: AsyncSession, *, tenant_id: UUID) -> KycRecord:
    """The record, or the refusal for a client that does not exist or is not waiting."""
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
    return record


async def decide_kyc_review(
    scoped: AsyncSession,
    *,
    tenant_id: UUID,
    decision: KycDecision,
    document_ref: str | None,
    reason: str | None,
    pan_checked: bool,
    admin_id: UUID,
) -> KycReviewOutcome:
    """Approve or reject, under the tenant's own session. D-696: approving a manual-path
    record needs `pan_checked` — the reviewer's statement that the PAN, name and date of
    birth matched at Income Tax — and stores who checked and when."""
    record = await assert_awaiting_review(scoped, tenant_id=tenant_id)
    documents = await current_documents(scoped, tenant_id=tenant_id)
    business = documents.get("business")
    if decision == "approve":
        if business is None:
            raise ProblemError.business_rule(
                "kyc_business_document_missing",
                "There is no business certificate on file to approve against.",
                remediation="Reject with a reason asking for the certificate.",
            )
        document_kind = REGISTRY_KIND[business.kind]
        if document_kind == "cin" and record.entity_type == "llp":
            document_kind = "llpin"
        resolved_ref = document_ref or (record.gstin if business.kind == "gst" else None)
        if not resolved_ref:
            raise ProblemError(
                kind="validation",
                code="kyc_document_required",
                title="Enter the registry number you checked",
                detail="Approving needs the CIN, LLPIN or Udyam number from the certificate.",
                remediation="Type the number from the certificate and approve again.",
            )
        if record.kyc_path == "manual" and not pan_checked:
            raise ProblemError(
                kind="validation",
                code="kyc_pan_check_required",
                title="Check the PAN at Income Tax first",
                detail="Approving a document review needs the PAN, full name and date of "
                "birth to match at the Income Tax 'Verify Your PAN' service.",
                remediation="Run the check, tick that the details matched, and approve "
                "again. If they did not match, reject with a reason.",
            )
        await record_kyc(
            scoped,
            tenant_id=tenant_id,
            status="verified",
            entity_type=record.entity_type,
            document_kind=document_kind,
            document_ref=resolved_ref,
            evidence_ref=f"kyc_document:{business.id}",
            verified_by_admin_id=admin_id,
        )
        if record.kyc_path == "manual":
            await record_owner_pan_check(scoped, tenant_id=tenant_id, admin_id=admin_id)
    else:
        if not reason:
            raise ProblemError(
                kind="validation",
                code="kyc_rejection_reason_required",
                title="A rejection must say why",
                detail="The client is shown this reason and needs it to fix the problem.",
                remediation="Say what was missing or wrong.",
            )
        await record_kyc(scoped, tenant_id=tenant_id, status="rejected", rejection_reason=reason)
    held_owner_id = await request_owner_id_deletion(scoped, tenant_id=tenant_id)
    return KycReviewOutcome(record=record, held_owner_id=held_owner_id)


def review_audit_summary(outcome: KycReviewOutcome, *, decision: KycDecision) -> dict[str, object]:
    """The `kyc.reviewed` row's summary, the same from both doors."""
    return {
        "decision": decision,
        "owner_id_type": outcome.record.owner_id_type,
        "owner_id_file_deletion_requested": outcome.held_owner_id is not None,
        "pan_matched_at_income_tax": decision == "approve" and outcome.record.kyc_path == "manual",
    }


__all__ = [
    "REGISTRY_KIND",
    "KycDecision",
    "KycReviewOutcome",
    "assert_awaiting_review",
    "decide_kyc_review",
    "review_audit_summary",
]
