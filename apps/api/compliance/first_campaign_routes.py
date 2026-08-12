"""The two surfaces of the first-campaign hold: the client's view and ops's release.

    GET  /v1/compliance/first-campaign-review                  "why can I not launch?"
    POST /v1/admin/tenants/{tenant_id}/first-campaign-review   the human release

R-11's last mitigation is worthless without both halves. A hold nobody can release is an
outage with a compliance justification; a hold the client cannot see is a launch button
that fails for reasons the product never explains, which is how a control becomes a
support queue.

**The client route reads, and cannot write.** Releasing an account is something a person
at Calevate does after reading the campaign — a client who could release itself would be
marking the gate green on a review nobody performed, which is the same argument that
keeps `kyc_routes.py` read-only and a sharper one here, because this control exists
precisely for accounts we have never met. `org:read`, not `org:manage`: looking at your
own compliance state is not changing it, and `org:manage` is in `MUTATING_PERMISSIONS`,
so requiring it would hide this view from the read-only "view as client" session (D-22)
that support is in when the call comes.

**A missing decision is a 200, not a 404.** It is the normal state of every new account,
and the console renders "held for review" from `held: true`.

**The ops route is admin-realm and names its tenant in the PATH**, like every other
`/v1/admin/tenants/{tenant_id}/...` mutation: an admin-realm mutation that inferred its
tenant from the session would be un-callable under D-22. It is audited on every call, so
a release and a later withdrawal are two entries in the append-only `audit_log` rather
than one edited row (hard rule 4).

**The ops QUEUE lives elsewhere, and widened nothing.** Listing every held account is a
cross-tenant read of a tenant table, and `admin_session` widens `USING` on
`organizations` and nothing else (migration b57e2f9c4a13). That gap was closed ONCE, for
this hold and for KYC together, in `apps/api/admin/holds.py`: the directory under
`app.admin`, then each tenant's own RLS session asking `first_campaign_hold_blocker` —
so no policy changed, the flag rides the existing tenant directory, and
`GET /v1/admin/compliance/holds` is that same predicate ordered for triage.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.first_campaign import (
    read_first_campaign_review,
    record_first_campaign_decision,
)
from apps.api.compliance.service import first_campaign_hold_blocker
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/compliance/first-campaign-review", tags=["compliance"])
admin_router = APIRouter(
    prefix="/v1/admin/tenants/{tenant_id}/first-campaign-review", tags=["admin"]
)

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `first_campaign_routes.py` — same situation and same
# resolution as `kyc_routes.py` and `registration_routes.py`.
Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
HoldReader = Annotated[Principal, Depends(requires("org:read"))]
Reviewer = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]


class FirstCampaignHoldOut(BaseModel):
    """Whether this account's campaigns are waiting on a human, and what was decided.

    `held` and `reason` come from the SAME predicate the launch gate calls
    (`first_campaign_hold_blocker`), so this screen cannot tell a client they are clear
    while the launch button says otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    held: bool
    # The launch gate's own rule name when held (`first_campaign_review_pending` /
    # `first_campaign_review_rejected`), so this screen and `/launch-check` speak one
    # vocabulary about one fact.
    rule: str | None
    reason: str | None
    # `null` until a human has decided: absence is "nobody has looked yet", not a status.
    status: str | None
    # What the reviewer said — present for a rejection by construction, because a refusal
    # that cannot be explained is a ticket nobody can close.
    decision_note: str | None
    reviewed_campaign_id: UUID | None
    decided_at: datetime | None


class FirstCampaignDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    # What was reviewed, or why it was refused. NOT NULL in the schema with a length
    # CHECK behind it: a release nobody can account for later is the audit finding this
    # record exists to avoid.
    note: str = Field(max_length=2000)
    # WHICH campaign the operator read. Evidence, not mechanism — the hold is on the
    # account, and deleting this campaign changes nothing about it.
    reviewed_campaign_id: UUID | None = None


class FirstCampaignDecisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: str
    reviewed_campaign_id: UUID | None
    decided_at: datetime


@router.get(
    "",
    response_model=FirstCampaignHoldOut,
    openapi_extra=permission_meta("org:read"),
    summary="Is this account's first campaign still waiting on a human? (R-11)",
    description=(
        "Calevate reviews the first campaign of every self-serve account before it "
        "dials — the contact list, the script and the disclosure line. This says "
        "whether that review is still outstanding, and what was decided once it is "
        "done. An account nobody has reviewed yet gets `held: true` with a null "
        "`status` and a 200; managed accounts are never held. Read-only: the release "
        "is recorded by Calevate operations."
    ),
)
async def read_hold(session: Session, principal: HoldReader) -> FirstCampaignHoldOut:
    assert principal.tenant_id is not None
    held = await first_campaign_hold_blocker(session, tenant_id=principal.tenant_id)
    review = await read_first_campaign_review(session, tenant_id=principal.tenant_id)
    return FirstCampaignHoldOut(
        held=held is not None,
        rule=held[0] if held else None,
        reason=held[1] if held else None,
        status=review.status,
        decision_note=review.decision_note,
        reviewed_campaign_id=review.reviewed_campaign_id,
        decided_at=review.decided_at,
    )


@admin_router.post(
    "",
    response_model=FirstCampaignDecisionOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Release (or refuse) a self-serve account's campaign calling — R-11's hold",
    description=(
        "Records that a person at Calevate reviewed this account's first campaign. "
        "`approved` releases the account: this rule never blocks another of its "
        "campaigns. `rejected` keeps it held and shows the client the reason. Upserts, "
        "so a release can be withdrawn when complaints arrive and granted again "
        "afterwards — every call writes its own audit entry, so the history is the "
        "ledger rather than this row."
    ),
)
async def decide(
    tenant_id: UUID,
    payload: FirstCampaignDecisionIn,
    session: AdminSession,
    request: Request,
    principal: Reviewer,
) -> FirstCampaignDecisionOut:
    """Ops's half of BRD §245's "manual review of the first campaign".

    Same family, permission and shape as `record_kyc_verification`: `admin:tenants`,
    tenant in the PATH, and the work done inside `tenant_session(tenant_id)` so RLS is
    what isolates it rather than a WHERE clause.

    The note check duplicates the CHECK constraint on purpose — the database is the
    enforcement, and this exists so an operator gets a problem+json naming the field
    instead of a 500 out of an IntegrityError.
    """
    # `requires(..., realm="admin")` resolved this principal against `admin_users`, so
    # the id is present — and the CHECK constraint behind this write refuses an operator
    # decision that cannot name its operator, so a None here would be an IntegrityError
    # at the end of a transaction rather than a clear failure at the top of it.
    assert principal.user_id is not None
    if len(payload.note.strip()) < 3:
        raise ProblemError(
            kind="validation",
            code="first_campaign_review_note_required",
            title="A review decision must say what was reviewed",
            detail=(
                "Releasing or refusing an account without recording what was looked at "
                "leaves a decision nobody can account for afterwards."
            ),
            remediation=(
                "Send a note describing the list, the script and the disclosure line you "
                "checked — or, for a refusal, what was wrong with them."
            ),
        )

    async with tenant_session(tenant_id) as scoped:
        if payload.reviewed_campaign_id is not None:
            # RLS scopes this read to the tenant, so naming another tenant's campaign as
            # the evidence for this release is a 404 rather than a stored cross-tenant
            # pointer. The foreign key alone would have accepted it.
            exists = (
                await scoped.execute(
                    text("SELECT 1 FROM campaigns WHERE id = :cid"),
                    {"cid": payload.reviewed_campaign_id},
                )
            ).first()
            if exists is None:
                raise ProblemError.not_found("Campaign")
        await record_first_campaign_decision(
            scoped,
            tenant_id=tenant_id,
            status=payload.decision,
            note=payload.note,
            decided_by_admin_id=principal.user_id,
            reviewed_campaign_id=payload.reviewed_campaign_id,
        )
        decided_at = (
            await scoped.execute(
                text("SELECT decided_at FROM first_campaign_reviews WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        ).scalar_one()

    await write_audit(
        session,
        action="first_campaign_review.decided",
        actor=principal,
        tenant_id=tenant_id,
        object_type="first_campaign_review",
        object_id=str(tenant_id),
        ip=request.client.host if request.client else None,
        # The note travels with the entry into the audit LOG STREAM (`audit_log` has no
        # summary column — the row carries the hash chain, the summary is emitted
        # alongside it keyed by entry id, BACKEND-PATTERNS §7). It is copied rather than
        # left only in the mutable row because "why was this account released" is
        # exactly the question asked after a reversal has overwritten the row. Hard rule
        # 6 holds: this is ops prose about a campaign — no phone number, no transcript,
        # no extraction payload — and `redact_mapping` runs over it regardless.
        summary={
            "decision": payload.decision,
            "note": payload.note.strip(),
            "reviewed_campaign_id": (
                str(payload.reviewed_campaign_id) if payload.reviewed_campaign_id else None
            ),
        },
    )
    return FirstCampaignDecisionOut(
        tenant_id=tenant_id,
        status=payload.decision,
        reviewed_campaign_id=payload.reviewed_campaign_id,
        decided_at=decided_at,
    )


__all__ = ["admin_router", "router"]
