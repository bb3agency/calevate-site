"""Client-realm read of this account's own KYC verification (R-11; SURFACES §2b).

The view that explains a disabled dial button, and what we hold about this business.
`compliance.service.check_dispatch` emits `kyc_missing` / `kyc_not_verified`, and the
client's own operator will ask for the same documents before it issues them a connection
at all; without this route a client who hit either had nowhere to look up what we hold,
what state it is in, or what we are waiting for. That is the page somebody opens
precisely when they are already blocked, which is the worst possible moment to have no
page.

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
- **A client still cannot SET their own status** (D-47, narrowed by D-635). A client who
  could mark themselves `verified` would be opening the telecom gate on a verification
  that never happened — the argument that keeps `record_dlt_registration` admin-only, and
  a sharper one here, since this gate stands between an anonymous signup and a phone
  connection (Telecom Act 2023 s.3(7)). What D-635 adds is a client-realm route that
  STARTS a verification: it writes a `kyc_verification_requests` row and nothing else,
  and the only thing that can move `kyc_records` is a signed delivery from the provider.
  The guarantee is unchanged; what enforces it moved from "there is no route" to "the
  route cannot assert the outcome".
- **No audit row.** This discloses no personal data — a business's own verification
  state, to that business — and it is the page a blocked client will refresh. An audit
  chain that grows a row per poll stops being readable.

`number_purchase_available` is on this response rather than on a second endpoint because
it is half of the answer to "can Calevate get me a number": the other half is whether
this product supplies numbers at all, and under Model B it does not — the client buys the
connection on their own operator account and stays the subscriber of record
(`docs/legal/LEGAL-OPS-PLAYBOOK.md` §9). It comes from
`campaigns.provisioning.number_purchase_available()` — the SAME selector
`POST /v1/numbers/purchase` asks — so this screen can never offer a button that route
refuses. It is false for every account in every deployment, and the screen renders a
sentence rather than a control because of it.

Hard rule 1: the session is `deps.db`, so the row is scoped by RLS rather than by a
predicate anyone could forget. `tests/kyc_gate_test.py` proves tenant B sees zero rows
both through this route and on the raw session.

Hard rule 6: `document_ref` is a public business-registry identifier; `signatory_name`
and `verified_name` are the names of the person who signed for the entity and the person
a licensed aggregator attested, both of which that entity already knows. No
identity-document number exists in the schema to leak, and a CHECK on every reference and
name column refuses one being typed in. Names are returned to the account they belong to
and appear in no log line and no audit summary.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.provisioning import number_purchase_available
from apps.api.compliance.audit import write_audit
from apps.api.compliance.kyc import (
    KycRecord,
    mark_digilocker_path,
    read_kyc,
    save_business_details,
    submit_for_manual_review,
)
from apps.api.compliance.kyc_documents import (
    KYC_MAX_DOCUMENT_BYTES,
    RETIRED_AADHAAR_KIND,
    KycDocumentRow,
    aadhaar_copy_not_accepted,
    accept_upload,
    assert_kind_fits_slot,
    current_documents,
    delete_requested_documents,
    mask_pan,
    new_document_id,
    open_document,
    record_document,
    seal_document,
)
from apps.api.compliance.kyc_providers import IdDocument, available_provider
from apps.api.compliance.kyc_verification import (
    VERIFICATION_UNAVAILABLE_REASON,
    apply_outcome,
    expire_stale_runs,
    open_request,
    resolve_request,
)
from apps.api.compliance.models import KYC_ENTITY_TYPES
from apps.api.compliance.trial_access import refuse_on_trial
from apps.api.core.alerting import alert
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.console_links import console_base
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.rbac import permission_meta
from apps.api.db.session import tenant_session, untenanted_session

log = get_logger(__name__)

router = APIRouter(prefix="/v1/compliance/kyc", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py` and this module is `kyc_routes.py` — same situation, same resolution as
# `registration_routes.py`, `dnc_routes.py` and `deletion_routes.py`.
KycReader = Annotated[Principal, Depends(requires("org:read"))]
# STARTING a verification is a mutation of this account's compliance state, so it
# takes the mutating permission — and being in `MUTATING_PERMISSIONS` is also what
# keeps it out of a read-only "view as client" session, which is correct: an operator
# must not begin an identity verification on a client's behalf.
_KycManager = Annotated[Principal, Depends(requires("org:manage"))]


async def _kyc_writer(principal: _KycManager, session: Session) -> Principal:
    """`org:manage`, and not on a free trial: verification opens once the account pays
    (D-697). One dependency for every write, so no write route can skip it; the read stays
    open so the page can say why."""
    if principal.tenant_id is not None:
        await refuse_on_trial(session, tenant_id=principal.tenant_id, locked="kyc")
    return principal


KycWriter = Annotated[Principal, Depends(_kyc_writer)]


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
    # WHO verified, and the aggregator's own reference (D-635). The reference is the
    # liability artefact — a licensed third party can be asked to corroborate it — and
    # `verified_name` is what they attested. Returned to the account they describe and
    # to nobody else.
    verification_source: str | None
    verification_provider: str | None
    verification_reference: str | None
    verified_name: str | None
    is_verified: bool
    # Whether this deployment can run a self-service verification at all. The SAME
    # selector `POST /v1/compliance/kyc/verification` asks, so this screen can never
    # offer a button that route refuses — the discipline `number_purchase_available`
    # already establishes one field down. False on every deployment today.
    self_verification_available: bool
    # Both halves of "can Calevate get me a number": this account being verified AND
    # this product supplying numbers at all. The second half is FALSE BY DECISION and
    # not by omission — Model B, `campaigns/provisioning.py` — so this is false for
    # every account in every deployment.
    number_purchase_available: bool
    # D-692: the path chosen, the business facts, the owner ID used (masked), the admin's
    # DigiLocker requirement, and the documents on file (metadata only).
    kyc_path: str | None
    legal_business_name: str | None
    gst_registered: bool | None
    gstin: str | None
    owner_id_type: str | None
    owner_id_masked: str | None
    name_match: bool | None
    digilocker_required: bool
    digilocker_required_reason: str | None
    # The requirement is set and no run has completed since — outbound is blocked on it.
    digilocker_outstanding: bool
    documents: list[KycDocumentOut]


class KycDocumentOut(BaseModel):
    """One file on record. Metadata only; the bytes are never returned to the client."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    slot: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime
    # False once the file has been deleted (an owner ID after its review is decided).
    held: bool


KycRecordOut.model_rebuild()


def documents_out(documents: dict[str, KycDocumentRow]) -> list[KycDocumentOut]:
    return [
        KycDocumentOut(
            id=row.id,
            slot=row.slot,
            kind=row.kind,
            filename=row.filename,
            content_type=row.content_type,
            size_bytes=row.size_bytes,
            uploaded_at=row.created_at,
            held=row.held,
        )
        for row in documents.values()
    ]


def _out(
    record: KycRecord,
    *,
    purchase_available: bool,
    self_verification_available: bool,
    documents: dict[str, KycDocumentRow] | None = None,
) -> KycRecordOut:
    return KycRecordOut(
        kyc_path=record.kyc_path,
        legal_business_name=record.legal_business_name,
        gst_registered=record.gst_registered,
        gstin=record.gstin,
        owner_id_type=record.owner_id_type,
        owner_id_masked=record.owner_id_masked,
        name_match=record.name_match,
        digilocker_required=record.digilocker_required,
        digilocker_required_reason=record.digilocker_required_reason,
        digilocker_outstanding=record.digilocker_outstanding,
        documents=documents_out(documents or {}),
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
        verification_source=record.verification_source,
        verification_provider=record.verification_provider,
        verification_reference=record.verification_reference,
        verified_name=record.verified_name,
        is_verified=record.is_verified,
        self_verification_available=self_verification_available,
        number_purchase_available=purchase_available,
    )


@router.get(
    "",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's identity verification — absence is data, not a 404",
    description=(
        "What Calevate has verified about this business. Read-only: Indian telecom "
        "rules make the subscriber's identity something the provider verifies, never "
        "something the subscriber asserts, so verification is recorded by Calevate "
        "operations. `number_purchase_available` is always false — Calevate does not "
        "supply telephone numbers; the client takes the connection on their own "
        "operator account. A business with nothing on file yet gets `recorded: false` "
        "and a 200."
    ),
)
async def read_kyc_record(
    session: Session,
    principal: KycReader,
) -> KycRecordOut:
    assert principal.tenant_id is not None
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    return _out(
        record,
        purchase_available=record.is_verified and number_purchase_available(),
        self_verification_available=available_provider().available,
        documents=await current_documents(session, tenant_id=principal.tenant_id),
    )


# ---------------------------------------------------------------------------
# D-635 — the client verifies THEMSELVES, and the result comes back on a webhook.
#
# D-47 said there is "deliberately no client-realm write" here, and that clause is what
# this supersedes — narrowly. A client still cannot SET their status: `start_verification`
# writes a request row and nothing else, and the only thing that can move `kyc_records` is
# a signed delivery from the provider. The property D-47 was protecting — that a client
# cannot mark the telecom gate green on a verification that never happened — is unchanged
# and is now enforced by a signature rather than by the absence of a route.
# ---------------------------------------------------------------------------


class StartVerificationIn(BaseModel):
    """How the business is constituted — the only thing the client tells us.

    It decides the BRANCH, not the outcome: a sole proprietor's verification completes
    the record, a company's verifies the authorised signatory and leaves the registry
    check to an operator. It is not taken on trust in any way that matters, because a
    company's row cannot reach `verified` on this path at all.
    """

    model_config = ConfigDict(extra="forbid")

    entity_type: str
    # Which DigiLocker record to share: the Aadhaar or the PAN (D-692).
    id_document: Literal["aadhaar", "pan"] = "aadhaar"


class StartVerificationOut(BaseModel):
    """Where to send the client, and what we will know the run by."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_ref: str
    #: The PROVIDER's page. The client authenticates there and their Aadhaar never
    #: touches this system — which is the whole architecture, in one field.
    redirect_url: str


@router.post(
    "/verification",
    response_model=StartVerificationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Begin verifying this business's identity with a licensed aggregator",
    description=(
        "Opens a verification run and returns the provider URL to send the signed-in "
        "user to. Calevate receives only whether it succeeded, the provider's reference "
        "and the verified name — never an Aadhaar number, a PAN or a document. A sole "
        "proprietorship is verified outright; for any other entity type this verifies "
        "the authorised signatory and Calevate operations still checks the business "
        "against its public registry entry."
    ),
)
async def start_verification(
    body: StartVerificationIn,
    request: Request,
    session: Session,
    principal: KycWriter,
) -> StartVerificationOut:
    assert principal.tenant_id is not None
    if body.entity_type not in KYC_ENTITY_TYPES:
        raise ProblemError.business_rule(
            "unknown_entity_type",
            "That is not an entity type we can verify.",
            remediation="Choose how the business is registered and try again.",
        )
    capability = available_provider()
    if capability.provider is None:
        # The SAME selector the read route reports, so a screen can never offer a button
        # this refuses. The machine reason goes in the code; the sentence is the one
        # `kyc_verification.py` defines, so this condition is explained identically
        # wherever it surfaces.
        raise ProblemError.business_rule(
            "self_verification_unavailable",
            VERIFICATION_UNAVAILABLE_REASON,
            remediation="Our operations team will verify this business directly.",
        )
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    if record.is_verified and not record.digilocker_outstanding:
        raise ProblemError.business_rule(
            "kyc_already_verified",
            "This business's identity is already verified.",
            remediation="Nothing further is needed.",
        )
    if record.entity_type is not None and record.entity_type != body.entity_type:
        # THE DECLARATION DOES NOT OVERRULE WHAT IS ON FILE. The entity type decides the
        # BRANCH, and only `sole_proprietorship` reaches `verified` on one person's
        # DigiLocker authentication — so a company declaring itself a proprietorship is
        # the one input on this route that could verify a business nobody checked. Where
        # an operator has already recorded how the business is constituted, a contradiction
        # is refused rather than silently overwritten by `record_kyc`'s upsert.
        raise ProblemError.business_rule(
            "entity_type_on_file_differs",
            "Our record of how this business is registered does not match what you "
            "selected, so we cannot start a verification against it.",
            remediation="Contact support to correct the registered entity type before verifying.",
        )
    # The business certificate and details are needed on this path too (D-692): DigiLocker
    # proves the owner, never the business.
    await _assert_business_on_file(session, tenant_id=principal.tenant_id, record=record)

    provider = capability.provider
    start = await provider.start(
        entity_type=body.entity_type,
        redirect_back_url=await _return_url(session, tenant_id=principal.tenant_id),
        id_document=body.id_document,
    )
    await mark_digilocker_path(session, tenant_id=principal.tenant_id)
    # This tenant's abandoned runs, closed on the way past. One of the two writers of
    # `expired` — the other is the webhook — which is why there is no sweep to schedule.
    await expire_stale_runs(session, tenant_id=principal.tenant_id)
    # The row is committed BEFORE the client can possibly reach the provider, because the
    # webhook has no other way to learn whose run this is. `open_request` argues the
    # ordering in full.
    await open_request(
        session,
        tenant_id=principal.tenant_id,
        provider=provider.name,
        provider_ref=start.provider_ref,
        entity_type=body.entity_type,
        id_document=body.id_document,
    )
    await write_audit(
        session,
        action="kyc.self_verification_started",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kyc_verification_request",
        object_id=start.provider_ref,
        ip=client_request_ip(request),
        summary={
            "provider": provider.name,
            "entity_type": body.entity_type,
            "id_document": body.id_document,
        },
    )
    return StartVerificationOut(
        provider=provider.name, provider_ref=start.provider_ref, redirect_url=start.redirect_url
    )


async def _return_url(session: AsyncSession, *, tenant_id: UUID) -> str:
    """Where the provider sends the client afterwards — built ENTIRELY server-side.

    The slug is read rather than accepted from the request body. A caller-supplied return
    URL on a route that redirects a signed-in user is an open redirect, and one on the
    identity-verification path is the most valuable possible place to have one: the
    phishing page it lands on is the page the user is already expecting to type credentials
    into.
    """
    row = (
        await session.execute(
            text("SELECT slug FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).first()
    slug = str(row[0]) if row is not None else ""
    return f"{console_base('client')}/c/{slug}/verify-business"


def _id_document(value: str) -> IdDocument:
    return "pan" if value == "pan" else "aadhaar"


class CompleteVerificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_ref: str = Field(min_length=1, max_length=128)


class CompleteVerificationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `applied`, `replay`, `expired`, or `pending` while the client has not finished.
    status: str
    record: KycRecordOut


@router.post(
    "/verification/complete",
    response_model=CompleteVerificationOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Finish a DigiLocker verification when the client returns from the provider",
    description=(
        "Asks the provider, with Calevate's own credentials, how this run ended and records "
        "the result. The run must be one this account opened. Calevate keeps the result, "
        "the ID type, the verified name, a masked ID number and the provider's reference — "
        "never the document."
    ),
)
async def complete_verification(
    body: CompleteVerificationIn,
    request: Request,
    session: Session,
    principal: KycWriter,
) -> CompleteVerificationOut:
    """The client's return leg. Under the client's RLS session, so a reference from
    another account resolves to nothing — the run is found only if it is this tenant's."""
    assert principal.tenant_id is not None
    capability = available_provider()
    if capability.provider is None:
        raise ProblemError.business_rule(
            "self_verification_unavailable",
            VERIFICATION_UNAVAILABLE_REASON,
            remediation="Use document upload instead.",
        )
    run = await resolve_request(
        session, provider=capability.provider.name, provider_ref=body.provider_ref
    )
    if run is None or run.tenant_id != principal.tenant_id:
        raise ProblemError.not_found("verification run")
    outcome = await capability.provider.fetch_outcome(
        provider_ref=body.provider_ref, id_document=_id_document(run.id_document)
    )
    status = "pending"
    if outcome is not None:
        status = await apply_outcome(
            session, request=run, provider=capability.provider.name, outcome=outcome
        )
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    return CompleteVerificationOut(
        status=status,
        record=_out(
            record,
            purchase_available=record.is_verified and number_purchase_available(),
            self_verification_available=True,
            documents=await current_documents(session, tenant_id=principal.tenant_id),
        ),
    )


# ---------------------------------------------------------------------------
# D-692 — what the client declares and uploads, on either path.
# ---------------------------------------------------------------------------

_GSTIN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"


class BusinessDetailsIn(BaseModel):
    """The legal facts a numbering application in the client's own name needs."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_type: str
    legal_business_name: str = Field(min_length=2, max_length=200)
    gst_registered: bool
    gstin: str | None = Field(default=None, pattern=_GSTIN)
    # The owner or authorised signatory, as on their ID.
    owner_name: str = Field(min_length=2, max_length=120)


@router.put(
    "/details",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Save this business's legal name, GST status and owner name",
    description=(
        "Needed on both verification paths. Locked once a reviewer has the record or it is "
        "verified. A GSTIN is required when the business is GST-registered."
    ),
)
async def save_details(
    body: BusinessDetailsIn,
    request: Request,
    session: Session,
    principal: KycWriter,
) -> KycRecordOut:
    assert principal.tenant_id is not None
    if body.entity_type not in KYC_ENTITY_TYPES:
        raise ProblemError.business_rule(
            "unknown_entity_type",
            "That is not an entity type we can verify.",
            remediation="Choose how the business is registered and try again.",
        )
    if body.gst_registered and not body.gstin:
        raise ProblemError(
            kind="validation",
            code="kyc_gstin_required",
            title="Enter the GSTIN",
            detail="A GST-registered business needs its 15-character GSTIN on record.",
            remediation="Type the GSTIN exactly as it appears on the GST certificate.",
        )
    if any(char.isdigit() for char in body.owner_name):
        raise ProblemError(
            kind="validation",
            code="kyc_owner_name_invalid",
            title="Enter the owner's name, not a number",
            detail="The owner name is the person's name as it appears on their ID.",
            remediation="Type the name and leave out any ID number.",
        )
    await save_business_details(
        session,
        tenant_id=principal.tenant_id,
        entity_type=body.entity_type,
        legal_business_name=body.legal_business_name,
        gst_registered=body.gst_registered,
        gstin=body.gstin,
        owner_name=body.owner_name,
    )
    await write_audit(
        session,
        action="kyc.details_saved",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kyc_record",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        # The business's own public facts; the owner's name is not copied here.
        summary={"entity_type": body.entity_type, "gst_registered": body.gst_registered},
    )
    return await _current_out(session, tenant_id=principal.tenant_id)


@router.post(
    "/documents",
    response_model=KycDocumentOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Upload the business certificate or the owner's ID",
    description=(
        "`slot` is `business` (kind `gst`, `incorporation` or `udyam`) or `owner_id` (kind "
        "`pan_card`; an Aadhaar copy is refused, D-696). PDF, JPEG or PNG, at most 5 MB, "
        "a filename of at most 99 characters. Files are encrypted before storage. The "
        "owner's ID is deleted once a reviewer decides, or after 30 days if nobody does."
    ),
)
async def upload_document(
    request: Request,
    session: Session,
    principal: KycWriter,
    tasks: BackgroundTasks,
    slot: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> KycDocumentOut:
    assert principal.tenant_id is not None
    # A `users.id` (D-587); an operator in a view-as session cannot upload a client's
    # identity documents for them.
    uploader = principal.client_user_id
    if uploader is None:
        assert_view_as_may(principal, "compliance.kyc_documents")
        raise ProblemError.business_rule(
            "kyc_documents_are_the_clients_own",
            "Verification documents have to be uploaded by somebody at your own business.",
            remediation="Sign in to your own account and upload them there.",
        )
    checked_slot = assert_kind_fits_slot(slot=slot, kind=kind)
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    if record.is_verified:
        raise ProblemError.business_rule(
            "kyc_documents_locked",
            "Your business is verified, so the certificate can no longer be changed."
            if checked_slot == "business"
            else "Your business is verified, so these documents can no longer be changed.",
            remediation="Contact support if your registration details have changed.",
        )
    if record.status in ("submitted", "in_review"):
        raise ProblemError.business_rule(
            "kyc_documents_locked",
            "These documents are with our review team, so they cannot be replaced here.",
            remediation="Contact support if a document needs replacing.",
        )
    data = await _read_bounded(file)
    accepted = accept_upload(filename=file.filename or "", data=data)

    from apps.workers.storage import kyc_document_key, store_kyc_document

    document_id = new_document_id()
    sealed = seal_document(tenant_id=principal.tenant_id, document_id=document_id, data=data)
    key = kyc_document_key(
        tenant_id=principal.tenant_id, document_id=document_id, suffix=accepted.suffix
    )
    # Ciphertext only; the store's SSE applies on top (`_put_document`).
    await store_kyc_document(key=key, data=sealed.ciphertext, content_type=_CIPHERTEXT_TYPE)
    # Written and COMMITTED in its own transaction, as `review_kyc` does, rather than on the
    # request session: that one commits only after the response's background tasks have run,
    # and the task below must find the superseded rows committed (and must never delete a
    # file a rolled-back supersede would have left current).
    #
    # The object is stored before its row exists, and no sweep looks for an object with no
    # row, so a failure from here on (a concurrent upload losing the current-per-slot index,
    # the audit write, the commit) takes the object down with the request.
    try:
        async with tenant_session(principal.tenant_id) as writer:
            replaced = await record_document(
                writer,
                tenant_id=principal.tenant_id,
                document_id=document_id,
                slot=checked_slot,
                kind=kind,
                object_key=key,
                accepted=accepted,
                sealed=sealed,
                uploaded_by_user_id=uploader,
            )
            await write_audit(
                writer,
                action="kyc.document_uploaded",
                actor=principal,
                tenant_id=principal.tenant_id,
                object_type="kyc_document",
                object_id=str(document_id),
                ip=client_request_ip(request),
                # Slot, kind and size; never the filename, which the client chose and may
                # name a person (hard rule 6).
                summary={"slot": checked_slot, "kind": kind, "size_bytes": accepted.size_bytes},
            )
    except Exception:
        await _discard_unrecorded_upload(key, document_id=document_id)
        raise
    if replaced:
        tasks.add_task(delete_requested_documents, principal.tenant_id, replaced)
    rows = await current_documents(session, tenant_id=principal.tenant_id)
    return documents_out({checked_slot: rows[checked_slot]})[0]


#: The extension a downloaded file is named with, from the content type `accept_upload`
#: recorded. Shared with the operator's download in `kyc_admin_routes`.
DOCUMENT_SUFFIX = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


@router.get(
    "/documents/{document_id}",
    response_class=Response,
    openapi_extra=permission_meta("org:read"),
    summary="Open this business's own certificate",
    description=(
        "The business certificate on file, decrypted, so the account can see what it sent "
        "at any time. Only the `business` slot: the owner's ID is never handed back, and is "
        "deleted once a reviewer decides. Every view is audited."
    ),
    responses={200: {"content": {"application/octet-stream": {}}}},
)
async def download_own_certificate(
    document_id: UUID,
    request: Request,
    principal: KycReader,
) -> Response:
    """The client twin of the operator's download: decrypted in memory, never a presigned
    URL (the stored object is ciphertext under our key), and audited inside the same
    transaction that reads the row, so the bytes are never handed out without the audit
    row committed."""
    assert principal.tenant_id is not None
    from apps.workers.storage import read_kb_object

    async with tenant_session(principal.tenant_id) as scoped:
        row = (await current_documents(scoped, tenant_id=principal.tenant_id)).get("business")
        if row is None or row.id != document_id or not row.held:
            raise ProblemError.not_found("Document")
        ciphertext = await read_kb_object(row.object_key)
        if ciphertext is None:
            raise ProblemError.not_found("Document")
        plaintext = open_document(
            tenant_id=principal.tenant_id, document_id=row.id, envelope=row.envelope(ciphertext)
        )
        await write_audit(
            scoped,
            action="kyc.document_viewed",
            actor=principal,
            tenant_id=principal.tenant_id,
            object_type="kyc_document",
            object_id=str(document_id),
            ip=client_request_ip(request),
            summary={"slot": row.slot, "kind": row.kind},
        )
    return Response(
        content=plaintext,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="certificate-{row.id}.'
            f'{DOCUMENT_SUFFIX.get(row.content_type, "bin")}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


class ManualSubmitIn(BaseModel):
    """The PAN the uploaded PAN card shows.

    `owner_id_type` still accepts `aadhaar` so a screen from before D-696 gets the sentence
    telling the client to upload their PAN card, rather than a bare schema error."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    owner_id_type: Literal["aadhaar", "pan"]
    # The full PAN: validated, then only its masked form is kept.
    owner_id_number: str = Field(min_length=4, max_length=10)


@router.post(
    "/submit",
    response_model=KycRecordOut,
    openapi_extra=permission_meta("org:manage"),
    summary="Send the uploaded documents for review",
    description=(
        "The manual path: needs the business details, the business certificate and the "
        "owner's PAN card on file. Send the full PAN; only a masked form is kept. "
        "`owner_id_type: aadhaar` is refused (D-696): Aadhaar is accepted only through "
        "DigiLocker."
    ),
)
async def submit_for_review(
    body: ManualSubmitIn,
    request: Request,
    session: Session,
    principal: KycWriter,
) -> KycRecordOut:
    assert principal.tenant_id is not None
    record = await read_kyc(session, tenant_id=principal.tenant_id)
    if record.is_verified:
        raise ProblemError.business_rule(
            "kyc_already_verified",
            "This business's identity is already verified.",
            remediation="Nothing further is needed.",
        )
    if record.status in ("submitted", "in_review"):
        raise ProblemError.business_rule(
            "kyc_already_submitted",
            "Your documents are already with our review team.",
            remediation="We will tell you when the review is done.",
        )
    if body.owner_id_type == RETIRED_AADHAAR_KIND:
        raise aadhaar_copy_not_accepted()
    documents = await _assert_business_on_file(
        session, tenant_id=principal.tenant_id, record=record
    )
    # A held owner-ID file is a PAN card: migration c5e9a2d71b48's CHECK keeps any Aadhaar
    # copy from before D-696 out of the held set.
    owner = documents.get("owner_id")
    if owner is None or not owner.held:
        raise ProblemError.business_rule(
            "kyc_owner_id_missing",
            "Upload the owner's PAN card first.",
            remediation="Add the PAN card, then send for review.",
        )
    masked = mask_pan(body.owner_id_number)
    await submit_for_manual_review(
        session,
        tenant_id=principal.tenant_id,
        owner_id_type=body.owner_id_type,
        owner_id_masked=masked,
    )
    await write_audit(
        session,
        action="kyc.submitted_for_review",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="kyc_record",
        object_id=str(principal.tenant_id),
        ip=client_request_ip(request),
        summary={"owner_id_type": body.owner_id_type},
    )
    return await _current_out(session, tenant_id=principal.tenant_id)


async def _assert_business_on_file(
    session: AsyncSession, *, tenant_id: UUID, record: KycRecord
) -> dict[str, KycDocumentRow]:
    """Both paths need the business details and the business certificate (D-692)."""
    if not record.legal_business_name or record.gst_registered is None or not record.entity_type:
        raise ProblemError.business_rule(
            "kyc_details_missing",
            "Add your business's legal name, how it is registered and its GST status first.",
            remediation="Fill in the business details, then continue.",
        )
    documents = await current_documents(session, tenant_id=tenant_id)
    business = documents.get("business")
    if business is None:
        raise ProblemError.business_rule(
            "kyc_business_document_missing",
            "Upload your business certificate first: the GST certificate if you are "
            "GST-registered, otherwise the Certificate of Incorporation or Udyam certificate.",
            remediation="Add the certificate, then continue.",
        )
    expected = "gst" if record.gst_registered else None
    if expected is not None and business.kind != expected:
        raise ProblemError.business_rule(
            "kyc_business_document_kind_mismatch",
            "A GST-registered business must upload its GST certificate.",
            remediation="Upload the GST certificate in place of the current document.",
        )
    if record.gst_registered is False and business.kind == "gst":
        raise ProblemError.business_rule(
            "kyc_business_document_kind_mismatch",
            "You said the business is not GST-registered, but uploaded a GST certificate.",
            remediation="Correct the GST status, or upload the incorporation or Udyam certificate.",
        )
    return documents


async def _current_out(session: AsyncSession, *, tenant_id: UUID) -> KycRecordOut:
    record = await read_kyc(session, tenant_id=tenant_id)
    return _out(
        record,
        purchase_available=record.is_verified and number_purchase_available(),
        self_verification_available=available_provider().available,
        documents=await current_documents(session, tenant_id=tenant_id),
    )


#: What the object store is told the bytes are: they are ciphertext, not the document.
_CIPHERTEXT_TYPE = "application/octet-stream"


async def _discard_unrecorded_upload(key: str, *, document_id: UUID) -> None:
    """Delete an object whose row was never written. A delete that fails is logged with
    the document id: the object stays under the tenant's prefix, which the account
    erasure removes."""
    from apps.workers.storage import StorageUnavailableError, delete_objects

    try:
        await delete_objects([key])
    except StorageUnavailableError:
        log.error("kyc_unrecorded_upload_left", extra={"document_id": str(document_id)})


async def _read_bounded(file: UploadFile) -> bytes:
    """Read at most one byte past the limit, so an oversized upload is refused without
    being held whole in memory."""
    data = await file.read(KYC_MAX_DOCUMENT_BYTES + 1)
    return data


# --- The receiver -----------------------------------------------------------

webhook_router = APIRouter(prefix="/hooks/v1/kyc", tags=["compliance"])


class VerificationAck(BaseModel):
    """What the provider is told. Deliberately says nothing about the tenant or the
    person — an ack is read by whoever can reach the endpoint, which is everyone."""

    model_config = ConfigDict(extra="forbid")

    status: str


@webhook_router.post(
    "/{provider}",
    response_model=VerificationAck,
    summary="Verification outcome from the configured identity aggregator",
    description=(
        "Signed webhook. The signature is verified over the raw bytes before anything is "
        "parsed; the tenant is resolved from the run Calevate opened, never from the "
        "payload; and a redelivery is acknowledged without changing anything."
    ),
)
async def receive_verification_outcome(provider: str, request: Request) -> VerificationAck:
    """An unauthenticated endpoint that can mark a client VERIFIED — so it fails closed
    at every step, and each step refuses for its own reason.

    Nothing durable is written until the signature verifies AND the run resolves, so a
    forged or misaddressed delivery leaves no row at all — not even a trace it could
    later be replayed from.

    The body is NOT bounded here: `core/middleware`'s body-size middleware bounds every
    route in the app, including the ones nobody thought to bound, and a second cap on
    this one would be a second mechanism for a solved problem that could later disagree
    with the first.
    """
    capability = available_provider()
    if capability.provider is None:
        # A deployment with no configured, credentialled provider has no verification
        # feed, and something is POSTing to it. 404 rather than 503: an unconfigured
        # endpoint should not confirm to a prober that it exists and is merely waiting
        # for a secret.
        alert("ROUTE_HANDLER", "kyc_webhook_unconfigured", reason=capability.reason or "unknown")
        raise ProblemError.not_found("verification endpoint")
    if provider != capability.provider.name:
        # The path names a provider this deployment is not on. Refused rather than
        # ignored: it is either a stale endpoint still configured at an old vendor, or
        # somebody trying every provider name to find one that answers.
        alert("ROUTE_HANDLER", "kyc_webhook_wrong_provider", provider=provider)
        raise ProblemError.not_found("verification endpoint")

    raw = await request.body()
    if not capability.provider.verify_webhook(raw=raw, headers=_lowercased(request.headers)):
        # The one refusal that must never be softened. A forged delivery here marks an
        # arbitrary account verified, which defeats the entire control and the liability
        # case built on it.
        alert("ROUTE_HANDLER", "kyc_webhook_bad_signature", provider=provider)
        raise ProblemError.unauthorized("Signature verification failed.")

    try:
        outcome = capability.provider.parse_outcome(raw=raw)
    except (ValueError, KeyError):
        # Past the signature the sender is genuine, so an unreadable body is OUR problem
        # to see rather than theirs to retry into silence.
        alert("ROUTE_HANDLER", "kyc_webhook_unreadable_payload", provider=provider)
        raise ProblemError.business_rule(
            "verification_payload_unreadable", "That verification result could not be read."
        ) from None

    async with untenanted_session() as lookup:
        run = await resolve_request(lookup, provider=provider, provider_ref=outcome.provider_ref)
    if run is None:
        # A correctly-signed outcome for a run we never opened. There is no race that
        # produces this — the row is committed before the client can reach the provider —
        # so it is either a replay against a purged row or a vendor misconfiguration
        # pointing another customer's traffic at us. Either way there is no tenant, and
        # inventing one is the only truly unrecoverable mistake available here.
        alert("ROUTE_HANDLER", "kyc_webhook_unknown_reference", provider=provider)
        raise ProblemError.not_found("verification run")

    if not capability.provider.webhook_is_authoritative:
        # A doorbell: the delivery named the run, and the facts come from our own
        # authenticated read of it (D-692).
        pulled = await capability.provider.fetch_outcome(
            provider_ref=outcome.provider_ref, id_document=_id_document(run.id_document)
        )
        if pulled is None:
            return VerificationAck(status="pending")
        outcome = pulled

    async with tenant_session(run.tenant_id) as session:
        result = await apply_outcome(session, request=run, provider=provider, outcome=outcome)
    if result == "expired":
        # Post-signature, so the provider is genuine and something is reporting on a run
        # that outlived its window. Either their delivery is days late or somebody is
        # spending an old reference; both are worth a person's attention, and neither
        # verified anybody.
        alert("ROUTE_HANDLER", "kyc_webhook_expired_run", provider=provider)
    return VerificationAck(status=result)


def _lowercased(headers: Mapping[str, str]) -> dict[str, str]:
    """Header names, case-folded once. HTTP header names are case-insensitive and an
    adapter that compared them raw would work against one provider's capitalisation and
    fail against the next one's."""
    return {key.lower(): value for key, value in headers.items()}


__all__ = ["router", "webhook_router"]
