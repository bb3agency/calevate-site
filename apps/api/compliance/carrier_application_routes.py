"""The three surfaces of the carrier compliance application.

    GET  /v1/compliance/carrier-application                      "why can I not have a number?"
    POST /v1/compliance/carrier-application                      the client sends their documents
    GET  /v1/admin/tenants/{tenant_id}/carrier-application       ops reads one client's state
    POST /v1/admin/tenants/{tenant_id}/carrier-application       ops records the carrier's decision

The gate is worthless without all of them. A stage the client cannot see is a number that
never arrives for reasons the product never explains; a decision ops cannot record is a
client stuck behind a carrier that has already said yes.

**The client SUBMITS and cannot DECIDE.** They hold the documents — nobody else can
produce a GST certificate for their business — so the upload is theirs. The decision is
the CARRIER's and reaches us out of band, so recording it is admin-realm: a client who
could mark their own application `accepted` would open the number gate on a decision
nobody made, and the carrier would then refuse at purchase time with our money already
committed. Same argument that keeps `kyc_routes.py` read-only, one step sharper.

**A missing application is a 200, not a 404.** It is the normal state of every new
account, and the console renders "not started" from `recorded: false`. A 404 arrives at
the fetch layer indistinguishable from a moved route or a lost permission.

**`org:read` to look, `org:manage` to send.** Looking at your own compliance state is not
changing it, and `org:read` keeps this view visible inside a read-only "view as client"
session (D-22) — which is exactly the session a support person is in when the call comes
in. Sending documents is a mutation and takes the mutating permission.

**The ops route names its tenant in the PATH**, like every other
`/v1/admin/tenants/{tenant_id}/...` mutation: an admin-realm mutation that inferred its
tenant from the session would be un-callable under D-22. It is audited on every call, so
an acceptance and a later expiry are two entries in the append-only `audit_log` rather
than one edited row (hard rule 4).

**Hard rule 6.** Nothing logged or audited here is personal data: the audit summary
carries the status, the document KIND and the carrier's application identifier — a
business's own registration paperwork and a vendor reference. The filename a client chose
is stored and shown back to them but is deliberately NOT copied into the audit log, which
is read cross-tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.admin.service import tenant_exists
from apps.api.compliance.audit import write_audit
from apps.api.compliance.carrier_application import (
    CARRIER,
    CARRIER_MAX_DOCUMENT_BYTES,
    OPERATOR_DECISIONS,
    CarrierApplicationRecord,
    CarrierDecision,
    CarrierStatus,
    DocumentKind,
    assert_document_within_limits,
    assert_first_application_is_signed,
    assert_submittable,
    classify_document,
    ensure_application_row,
    our_status_for_carrier_status,
    read_carrier_application,
    record_carrier_decision,
    submit_application,
)
from apps.api.core.auth import client_request_ip, record_admin_tenant_read, requires
from apps.api.core.context import Principal
from apps.api.core.deps import admin_db, db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session

router = APIRouter(prefix="/v1/compliance/carrier-application", tags=["compliance"])
admin_router = APIRouter(prefix="/v1/admin/tenants/{tenant_id}/carrier-application", tags=["admin"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `carrier_application_routes.py` — same situation and
# same resolution as `kyc_routes.py` and `first_campaign_routes.py`.
Session = Annotated[AsyncSession, Depends(db)]
AdminSession = Annotated[AsyncSession, Depends(admin_db)]
ApplicationReader = Annotated[Principal, Depends(requires("org:read"))]
ApplicationSubmitter = Annotated[Principal, Depends(requires("org:manage"))]
CarrierOperator = Annotated[Principal, Depends(requires("admin:tenants", realm="admin"))]

#: One read of the spooled upload. 1 MiB is Starlette's own spool threshold, so this is the
#: size at which its buffer stops being in memory anyway — `kb/routes._read_bounded` picked
#: it for the same reason and this is the same problem.
_READ_CHUNK_BYTES = 1024 * 1024


class CarrierApplicationOut(BaseModel):
    """This account's carrier compliance application, as we last knew it.

    Every field except `recorded` and `is_accepted` is nullable, because all of them are
    genuinely absent before anything is filed. `is_accepted` is computed server-side for
    the reason `KycRecordOut.is_verified` is: "is `submitted` good enough" is a question
    the console must not answer for itself, and this response and the dial gate must never
    disagree.
    """

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    # WHICH carrier. Stored and returned because their application identifier means
    # nothing without it.
    carrier: str | None
    status: CarrierStatus | None
    # THEIR reference, shown so a client (or an operator on the phone to the carrier) can
    # quote it. Present exactly when the application has been accepted — the CHECK
    # constraint guarantees it.
    carrier_application_id: str | None
    document_kind: str | None
    # What the client called the file, so they can tell which document is on file. The
    # bytes themselves are never served from here.
    document_filename: str | None
    signed_application_on_file: bool
    # WHY this account is blocked, when the answer is "the carrier looked and said no".
    # Present exactly when `status = 'rejected'`, so a client is never told "rejected"
    # with no reason.
    rejection_reason: str | None
    submitted_at: datetime | None
    decided_at: datetime | None
    is_accepted: bool


class CarrierDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # EITHER our status, OR the carrier's own word to be mapped onto it. Two fields rather
    # than one because they are two different acts: an operator transcribing what the
    # carrier's console says (`carrier_status`) and an operator deciding what it means
    # (`status`). The mapping refuses a word it does not know rather than guessing.
    status: CarrierDecision | None = None
    carrier_status: str | None = Field(default=None, max_length=64)
    # THEIR identifier. Required for an acceptance by the CHECK constraint, because a
    # number purchase has to quote it.
    carrier_application_id: str | None = Field(default=None, max_length=200)
    # Required for a rejection, for `kyc_records`' reason: "rejected, no reason recorded"
    # is the ticket nobody can close.
    rejection_reason: str | None = Field(default=None, max_length=2000)


class CarrierDecisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    status: CarrierDecision
    carrier_application_id: str | None
    # False when the application was ALREADY in this state: the request is satisfied
    # either way (RFC 9110 §9.2.2), and an operator who clicked twice should not be told
    # they changed something twice.
    changed: bool


def _out(record: CarrierApplicationRecord) -> CarrierApplicationOut:
    return CarrierApplicationOut(
        recorded=record.recorded,
        carrier=record.carrier,
        status=record.status,
        carrier_application_id=record.carrier_application_id,
        document_kind=record.document_kind,
        document_filename=record.document_filename,
        # The KEY is never returned: it is an object-store path, and the only thing a
        # client needs to know is whether the signed form has reached us.
        signed_application_on_file=record.signed_application_ref is not None,
        rejection_reason=record.rejection_reason,
        submitted_at=record.submitted_at,
        decided_at=record.decided_at,
        is_accepted=record.is_accepted,
    )


@router.get(
    "",
    response_model=CarrierApplicationOut,
    openapi_extra=permission_meta("org:read"),
    summary="This account's carrier compliance application — absence is data, not a 404",
    description=(
        "Our telephony carrier approves each client business separately before a number "
        "can be rented for it. This is where that application stands: what was sent, "
        "what the carrier said, and what is needed next. A business with nothing on file "
        "yet gets `recorded: false` and a 200."
    ),
)
async def read_application(
    session: Session,
    principal: ApplicationReader,
) -> CarrierApplicationOut:
    assert principal.tenant_id is not None
    record = await read_carrier_application(session, tenant_id=principal.tenant_id)
    return _out(record)


@router.post(
    "",
    response_model=CarrierApplicationOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Send this business's registration documents to the carrier",
    description=(
        "Upload ONE proof of business registration — a GST certificate, a Certificate of "
        "Incorporation, or a Udyam Registration certificate — as a PDF, JPEG or PNG. A "
        "PAN card on its own is not accepted. The first application must also carry the "
        "signed, sealed application form. Calevate forwards it to the carrier; the "
        "decision appears on this same endpoint."
    ),
)
async def submit(
    session: Session,
    document_kind: Annotated[DocumentKind, Form()],
    document: Annotated[UploadFile, File()],
    principal: ApplicationSubmitter,
    signed_application: Annotated[UploadFile | None, File()] = None,
) -> CarrierApplicationOut:
    """The client's half of the reseller stage.

    **The ordering is deliberate: refuse, then store, then write the row.** Refusing first
    means a client whose application is already with the carrier spends no storage and
    waits for no upload. Storing before the row means a successful submission can never
    point at bytes that are not there — the opposite ordering leaves a row claiming
    documents the store never received, and the carrier would be told we had sent
    something we had not. The CAS inside `submit_application` remains the authority on
    whether this submission is the one that counts.
    """
    assert principal.tenant_id is not None
    # The row id BEFORE the objects, because the object keys are built from it. Creating a
    # `not_started` row costs one INSERT and gives every later reader — the client's
    # screen, the ops console, the gate — something to read.
    application_id = await ensure_application_row(session, tenant_id=principal.tenant_id)
    current = await read_carrier_application(session, tenant_id=principal.tenant_id)
    assert_submittable(current)
    signed_supplied = signed_application is not None and bool(signed_application.filename)
    assert_first_application_is_signed(current, signed_application_supplied=signed_supplied)

    # A fresh submission id per submission: the row is one per tenant and MUTABLE, so a key
    # built from the application alone would have a resubmission overwrite the bytes the
    # carrier refused. See `carrier_document_key`.
    submission_id = uuid7()
    document_filename, document_ref = await _store_one(
        file=document,
        tenant_id=principal.tenant_id,
        application_id=application_id,
        submission_id=submission_id,
        slot="registration",
    )
    signed_ref: str | None = None
    if signed_supplied:
        assert signed_application is not None
        _, signed_ref = await _store_one(
            file=signed_application,
            tenant_id=principal.tenant_id,
            application_id=application_id,
            submission_id=submission_id,
            slot="signed-application",
        )

    await submit_application(
        session,
        tenant_id=principal.tenant_id,
        application_id=application_id,
        document_kind=document_kind,
        document_object_ref=document_ref,
        document_filename=document_filename,
        signed_application_ref=signed_ref,
    )
    return _out(await read_carrier_application(session, tenant_id=principal.tenant_id))


async def _store_one(
    *,
    file: UploadFile,
    tenant_id: UUID,
    application_id: UUID,
    submission_id: UUID,
    slot: str,
) -> tuple[str, str]:
    """Read one uploaded document within its ceiling, store it, return `(name, key)`.

    The two uploads this route takes differ only in their slot, so they share this rather
    than carrying two copies of the read-bound-classify-store sequence — the second copy is
    where one of those four steps silently stops happening.

    The storage import is LOCAL, as it is everywhere else in `apps/api` that touches it:
    `apps.workers.storage` pulls in boto3, and the API's import surface should not pay for
    that on behalf of a route nobody has called yet (`kb/uploads.py` imports it the same
    way for the same reason).
    """
    from apps.workers.storage import carrier_document_key, store_carrier_document

    raw_name = file.filename or ""
    data = await _read_bounded(file)
    filename = assert_document_within_limits(filename=raw_name, size_bytes=len(data))
    extension, content_type = classify_document(filename)
    key = carrier_document_key(
        tenant_id=tenant_id,
        application_id=application_id,
        submission_id=submission_id,
        slot=slot,
        suffix=extension,
    )
    await store_carrier_document(key=key, data=data, content_type=content_type)
    return filename, key


async def _read_bounded(file: UploadFile) -> bytes:
    """The upload body, or a refusal — read in chunks and STOPPED at the ceiling.

    `await file.read()` reads whatever was sent, so the memory one request spends is chosen
    by whoever sent it, and on an ASGI server that is every tenant's process rather than
    only the uploader's. `kb/routes._read_bounded` makes the argument in full; this is the
    same bound against the carrier's own, smaller ceiling.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > CARRIER_MAX_DOCUMENT_BYTES:
            # Stop reading and refuse: the rest of the body is not worth the memory, and
            # the answer cannot change. The refusal is the same one a known-size upload
            # gets, so the client reads one sentence either way.
            assert_document_within_limits(filename=file.filename or "document", size_bytes=total)
        chunks.append(chunk)
    return b"".join(chunks)


@admin_router.get(
    "",
    response_model=CarrierApplicationOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="One client's carrier compliance application",
    description=(
        "What this client has sent the carrier and where it stands. Read-only; the "
        "decision is recorded by POST to the same path."
    ),
)
async def read_for_tenant(
    tenant_id: UUID,
    session: AdminSession,
    request: Request,
    principal: CarrierOperator,
) -> CarrierApplicationOut:
    """Ops's read, through the tenant's OWN RLS session rather than a widened policy.

    `admin_session()` widens `USING` on `organizations` and nothing else (migration
    b57e2f9c4a13), so a cross-tenant read of a tenant table is not available and is not
    wanted: entering the tenant's session is the same route `admin/holds.py` takes for the
    KYC and first-campaign queues, and it means this endpoint reads exactly what the
    client's own screen reads.

    **AND IT RECORDS THE READ** (SEC-COMP §5, D-482 L-1). This is an admin-realm GET of one
    client's tenant-scoped rows outside impersonation, which is the shape that has to leave
    a trail: a business's registration paperwork is their data, and "who looked at this
    account and when" is not answerable afterwards unless the read says so itself. Written
    LATE, in the same transaction, so the row and the read commit together.
    """
    async with tenant_session(tenant_id) as scoped:
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        record = await read_carrier_application(scoped, tenant_id=tenant_id)
    await record_admin_tenant_read(
        session, request=request, principal=principal, tenant_id=tenant_id
    )
    return _out(record)


@admin_router.post(
    "",
    response_model=CarrierDecisionOut,
    openapi_extra=permission_meta("admin:tenants"),
    summary="Record what the carrier decided about this client's compliance application",
    description=(
        "Records the carrier's own decision. `accepted` is the only state that lets a "
        "number be rented for this client, and it requires the carrier's "
        "`compliance_application_id` — the reference a number purchase has to quote. "
        "`rejected` requires the carrier's reason, which the client is shown. "
        "`documents_required` sends the client back for more paperwork, and `expired` "
        "records an approval that has lapsed or been suspended. There is deliberately no "
        "client-facing twin: a business that could accept its own application would be "
        "opening the number gate on a decision nobody made."
    ),
)
async def record_decision(
    tenant_id: UUID,
    payload: CarrierDecisionIn,
    session: AdminSession,
    request: Request,
    principal: CarrierOperator,
) -> CarrierDecisionOut:
    """Ops's half of the reseller stage.

    Same family, permission and shape as `record_kyc_verification` and the first-campaign
    release: `admin:tenants`, tenant in the PATH, and the work done inside
    `tenant_session(tenant_id)` so RLS is what isolates it rather than a WHERE clause
    somebody can forget.

    The two validations below duplicate CHECK constraints on purpose: the database is the
    enforcement, and these exist so an operator reads a problem+json naming the missing
    field instead of a 500 out of an IntegrityError.
    """
    # `requires(..., realm="admin")` resolved this principal against `admin_users`, so the
    # id is present — and the CHECK behind this write refuses a decision that cannot name
    # its operator, so a None here would surface as an IntegrityError at the end of a
    # transaction rather than a clear failure at the top of one.
    assert principal.user_id is not None
    status = _resolved_status(payload)
    if status == "accepted" and not (payload.carrier_application_id or "").strip():
        raise ProblemError(
            kind="validation",
            code="carrier_application_id_required",
            title="An accepted application must carry the carrier's reference",
            detail=(
                "The carrier's compliance application id is what a number purchase has to "
                "quote, so an acceptance without it cannot be used."
            ),
            remediation=(
                "Copy the application reference from the carrier's console and record it "
                "with the acceptance."
            ),
        )
    if status == "rejected" and not (payload.rejection_reason or "").strip():
        raise ProblemError(
            kind="validation",
            code="carrier_rejection_reason_required",
            title="A rejection must say why",
            detail=(
                "A rejected application with no reason recorded is a client who cannot "
                "tell which document to replace."
            ),
            remediation=(
                "Record why the carrier refused it, in their own words where possible — "
                "the client is shown this and is the only person who can fix it."
            ),
        )

    async with tenant_session(tenant_id) as scoped:
        # A mistyped tenant uuid is a 404, not a 500 — `carrier_compliance_applications`
        # carries an FK to `organizations`, so an id no organization holds would otherwise
        # reach the upsert and surface as `internal_error` with an operator alert attached,
        # for a typo the operator could fix themselves (D-133's family).
        if not await tenant_exists(scoped, tenant_id):
            raise ProblemError.not_found("Client")
        application_id = await ensure_application_row(scoped, tenant_id=tenant_id)
        changed = await record_carrier_decision(
            scoped,
            tenant_id=tenant_id,
            application_id=application_id,
            status=status,
            recorded_by_admin_id=principal.user_id,
            carrier_application_id=payload.carrier_application_id,
            rejection_reason=payload.rejection_reason,
        )

    await write_audit(
        session,
        action="carrier_application.decided",
        actor=principal,
        tenant_id=tenant_id,
        object_type="carrier_compliance_application",
        object_id=str(tenant_id),
        ip=client_request_ip(request),
        # The carrier's reference is the point of the entry: it is what a regulator or the
        # carrier itself asks us to evidence. The client's filename is deliberately not
        # copied — it adds nothing an auditor needs and the audit log is read cross-tenant.
        summary={
            "carrier": CARRIER,
            "status": status,
            "carrier_application_id": payload.carrier_application_id,
            "changed": changed,
        },
    )
    return CarrierDecisionOut(
        tenant_id=tenant_id,
        status=status,
        carrier_application_id=payload.carrier_application_id,
        changed=changed,
    )


def _resolved_status(payload: CarrierDecisionIn) -> CarrierDecision:
    """Exactly one of `status` / `carrier_status`, resolved to OUR vocabulary.

    Refusing both-or-neither rather than preferring one: an operator who sent both means
    two different things by them, and silently picking would record a decision they did
    not make.
    """
    if (payload.status is None) == (payload.carrier_status is None):
        raise ProblemError(
            kind="validation",
            code="carrier_decision_status_required",
            title="Say what the carrier decided",
            detail=(
                "Send either `status` (our own word for it) or `carrier_status` (the "
                "carrier's own word, which we map) — not both, and not neither."
            ),
            remediation=(
                "Use `status` when you are deciding how to record it, and `carrier_status` "
                "when you are transcribing what the carrier's console shows."
            ),
        )
    if payload.status is not None:
        return payload.status
    assert payload.carrier_status is not None
    mapped = our_status_for_carrier_status(payload.carrier_status)
    if mapped not in OPERATOR_DECISIONS:
        # The carrier's word maps onto a state that is not a decision — "pending", which
        # is where the application already is. Recording it would be a no-op dressed as an
        # action, and the operator would leave believing something had been filed.
        raise ProblemError.business_rule(
            "carrier_decision_not_a_decision",
            f"The carrier still has this application: it reports {payload.carrier_status!r}.",
            remediation=(
                "There is nothing to record until the carrier accepts it, refuses it, or "
                "asks for more documents."
            ),
        )
    return mapped


__all__ = ["admin_router", "router"]
