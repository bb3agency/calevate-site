"""An operator's decision on a client's identity verification — one implementation behind
the KYC review screen (`POST /v1/admin/tenants/{tenant_id}/kyc/review`) and the admin
assistant's `admin_kyc_review` action (D-698).

The decision promises the client's email (`workers/kyc_notices`) in its own transaction.
The caller opens the tenant's session, writes the `kyc.reviewed` audit row with the
outcome below, and schedules the owner-ID file deletion after commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.compliance.kyc import (
    KycRecord,
    lock_kyc,
    read_kyc,
    record_kyc,
    record_owner_pan_check,
)
from apps.api.compliance.kyc_documents import (
    PendingDeletion,
    current_documents,
    request_owner_id_deletion,
)
from apps.api.core.errors import ProblemError
from apps.api.reliability.service import enqueue_outbox_once

#: The ARQ name of `workers/kyc_notices.notify_kyc_decision`: the client's email after a
#: reviewer approves or rejects.
KYC_DECISION_NOTICE_JOB: Final = "notify_kyc_decision"

#: The public registry a business certificate is checked against, by certificate kind.
REGISTRY_KIND: Final[dict[str, str]] = {"gst": "gstin", "incorporation": "cin", "udyam": "udyam"}

KycDecision = Literal["approve", "reject"]


@dataclass(frozen=True, slots=True)
class WaitingReview:
    tenant_id: UUID
    name: str
    slug: str
    status: str
    kyc_path: str | None
    owner_id_type: str | None
    digilocker_required: bool
    submitted_at: datetime | None


#: One query for every organization's waiting record (migration c7e1a4d9b2f6): the scan
#: re-scopes `app.tenant_id` to each organization in turn, so each record is read under its
#: own policy without a session per client.
_WAITING_SCAN: Final = (
    "SELECT scanned_tenant_id, status, kyc_path, owner_id_type, digilocker_required, "
    "submitted_at FROM kyc_waiting_scan()"
)
_NAMES: Final = "SELECT id, name, slug FROM organizations WHERE id = ANY(:ids)"


async def waiting_reviews(directory: AsyncSession) -> list[WaitingReview]:
    """Every record waiting for a reviewer, oldest submission first.

    `directory` is an admin session, whose GUC lists organizations; each record is read
    under its OWN tenant's policy inside `kyc_waiting_scan()`, so no policy is widened to let
    an admin session read `kyc_records`. Two queries, not a session per client (A7-21): the
    review queue, the admin bell and the overdue-review alarm (`workers/kyc_notices`) share
    it. The names are a second statement rather than a JOIN, so `organizations` is never
    read in the statement whose scan re-scopes the tenant GUC."""
    rows = (await directory.execute(text(_WAITING_SCAN))).all()
    names = {
        UUID(str(r[0])): (str(r[1]), str(r[2]))
        for r in await directory.execute(text(_NAMES), {"ids": [row[0] for row in rows]})
    }
    found = [
        WaitingReview(
            tenant_id=UUID(str(row[0])),
            name=names[UUID(str(row[0]))][0],
            slug=names[UUID(str(row[0]))][1],
            status=str(row[1]),
            kyc_path=row[2],
            owner_id_type=row[3],
            digilocker_required=bool(row[4]),
            submitted_at=row[5],
        )
        for row in rows
    ]
    found.sort(key=lambda w: (w.submitted_at is None, w.submitted_at or datetime.min))
    return found


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
    await lock_kyc(scoped, tenant_id=tenant_id)
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
    # The client's email, promised in the decision's transaction: a rolled-back decision
    # tells nobody. Keyed on the submission, so a resubmission decided again is told again.
    submitted = record.submitted_at.isoformat() if record.submitted_at else "unsubmitted"
    await enqueue_outbox_once(
        scoped,
        job=KYC_DECISION_NOTICE_JOB,
        payload={"tenant_id": str(tenant_id), "decision": decision},
        dedupe_key=f"kyc-decision:{tenant_id}:{submitted}",
    )
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
    "KYC_DECISION_NOTICE_JOB",
    "REGISTRY_KIND",
    "KycDecision",
    "KycReviewOutcome",
    "WaitingReview",
    "assert_awaiting_review",
    "decide_kyc_review",
    "review_audit_summary",
    "waiting_reviews",
]
