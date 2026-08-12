"""Client-realm read of this account's own KYC verification (R-11; SURFACES §2b).

The view that explains a disabled dial button and a disabled "buy a number" button.
`compliance.service.check_dispatch` emits `kyc_missing` / `kyc_not_verified` and
`campaigns.provisioning` refuses a purchase on the same two facts; without this route a
client who hit either had nowhere to look up what we hold, what state it is in, or what
we are waiting for. That is the page somebody opens precisely when they are already
blocked, which is the worst possible moment to have no page.

Four shapes, each deliberate — the same four `registration_routes.py` argues for, so
that a client's two compliance screens behave identically:

- **`org:read`, not `org:manage`.** Looking at your own compliance state is not changing
  it. `org:manage` is in `MUTATING_PERMISSIONS`, so requiring it would make this
  invisible to a support person inside a read-only "view as client" session (D-22) —
  exactly the person on the call when the account is blocked, and exactly the recurring
  bug `tests/impersonation_reads_test.py` exists to stop.
- **A missing record is a 200, not a 404.** It is the normal state of every new account.
  The console renders "not verified yet" from `recorded: false`; a 404 arrives at the
  fetch layer indistinguishable from a moved route or a lost permission.
- **No client write.** Verification is something WE do, recorded by ops through
  `POST /v1/admin/tenants/{tenant_id}/kyc`. A client who could set their own status to
  `verified` would be marking the telecom gate green on a verification that never
  happened — the same argument that keeps `record_dlt_registration` admin-only, and a
  much sharper one here, since this gate is what stands between an anonymous signup and
  a phone connection (Telecom Act 2023 s.3(7)).
- **No audit row.** This discloses no personal data — a business's own verification
  state, to that business — and it is the page a blocked client will refresh. An audit
  chain that grows a row per poll stops being readable.

`number_purchase_available` is on this response rather than on a second endpoint because
it is half of the answer to "why can I not buy a number": the other half is this
deployment having a telephony provider at all. It comes from
`campaigns.provisioning.number_purchase_available()` — the SAME selector the purchase
route asks — so this screen cannot offer a button that route refuses.

Hard rule 1: the session is `deps.db`, so the row is scoped by RLS rather than by a
predicate anyone could forget. `tests/kyc_gate_test.py` proves tenant B sees zero rows
both through this route and on the raw session.

Hard rule 6: nothing here is personal data. `document_ref` is a public business-registry
identifier and `signatory_name` is the name of the person who signed for the entity,
which that entity already knows. No identity-document number exists in the schema to
leak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.provisioning import number_purchase_available
from apps.api.compliance.kyc import KycRecord, read_kyc
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/kyc", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this module is `kyc_routes.py` — same situation, same resolution as
# `registration_routes.py`, `dnc_routes.py` and `deletion_routes.py`.
KycReader = Annotated[Principal, Depends(requires("org:read"))]


class KycRecordOut(BaseModel):
    """This account's identity verification, as ops last recorded it.

    Every field except `recorded`, `is_verified` and `number_purchase_available` is
    nullable, because all of them are genuinely absent before anything is filed.
    `is_verified` is computed server-side for the same reason `PeRegistrationOut`'s
    `is_active` is: "is `in_review` good enough" is a question the console must not
    answer for itself, and this response and the dispatch gate must never disagree.
    """

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    status: str | None
    entity_type: str | None
    # WHAT was checked and its public registry reference — CIN, LLPIN, GSTIN, Udyam. The
    # document itself is never held by us; `evidence_ref` says where the pack is filed.
    document_kind: str | None
    document_ref: str | None
    signatory_name: str | None
    evidence_ref: str | None
    # WHY this account is blocked, when the answer is "we looked and said no". Present
    # exactly when `status = 'rejected'` — the CHECK constraint guarantees it is not
    # null in that state, so a client is never told "rejected" with no reason.
    rejection_reason: str | None
    submitted_at: datetime | None
    # When WE verified it, stamped by the database at the moment of the write — not a
    # date an operator typed.
    verified_at: datetime | None
    is_verified: bool
    # Both halves of "can I buy a number": this account being verified AND this
    # deployment having a telephony provider with an adapter behind it. False today for
    # every account, because no provider is configured anywhere (D-05 is a decision, not
    # a credential) — see `campaigns/provisioning.py`.
    number_purchase_available: bool


def _out(record: KycRecord, *, purchase_available: bool) -> KycRecordOut:
    return KycRecordOut(
        recorded=record.recorded,
        status=record.status,
        entity_type=record.entity_type,
        document_kind=record.document_kind,
        document_ref=record.document_ref,
        signatory_name=record.signatory_name,
        evidence_ref=record.evidence_ref,
        rejection_reason=record.rejection_reason,
        submitted_at=record.submitted_at,
        verified_at=record.verified_at,
        is_verified=record.is_verified,
        number_purchase_available=purchase_available,
    )


@router.get(
    "",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's identity verification — absence is data, not a 404",
    description=(
        "What Calevate has verified about this business, and whether that is enough to "
        "buy a phone number. Read-only: Indian telecom rules make the subscriber's "
        "identity something the provider verifies, never something the subscriber "
        "asserts, so verification is recorded by Calevate operations. A business with "
        "nothing on file yet gets `recorded: false` and a 200."
    ),
)
async def read_kyc_record(
    session: Session,
    principal: KycReader,
) -> KycRecordOut:
    assert principal.tenant_id is not None
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    return _out(record, purchase_available=record.is_verified and number_purchase_available())


__all__ = ["router"]
