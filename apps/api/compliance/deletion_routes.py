"""Client-realm endpoints for a DPDP erasure request and its certificate (SEC-COMP §4).

The twin of `export_routes.py`, and shaped the same way on purpose. A data principal
asks the CLIENT to erase them; the client — the Data Fiduciary, we are their Processor —
asks us. So this is a client-realm surface, and the certificate it returns is the
client's to hand on.

The variable is `router`, as everywhere else in this package, and `main.py` mounts it
alongside the other compliance surfaces (this docstring used to say it did not — it was
written before the router was wired in, and a compliance module claiming to be unreachable
is exactly the sentence a reviewer must not have to check for themselves).

Four shapes worth explaining before someone "tidies" them:

- **`proof` is RENDERED from the stored row, not returned as it was written.** The row in
  `deletion_requests.proof` is the worker's record of facts; the certificate is what a
  client detaches and files, and a document that lists what it cleared while saying
  nothing about what survived is the overclaim SEC-COMP §4 warns about. Everything under
  `not_erased`/`limitations` is built by `compliance/deletion_proof.py` from the register
  in `compliance/deletion.py` — read that module before changing this one, particularly
  the part about never splatting a durable row into an `extra="forbid"` model.
- **Filing a request is a POST**, and the status read is keyed by an opaque request id
  rather than the number. Same reason as the subject-access export and the DNC check:
  the identifier IS the personal data, and a GET would write it into access logs, proxy
  logs, referrers and browser history (hard rule 6). A UUID in a URL is safe; a phone
  number never is.
- **Filing is `org:manage`, reading a status is `org:read`.** The reasoning — including
  why the export's `calls:read_raw` is disqualified here, and why D-22's refusal of
  mutating permissions to an impersonating admin is the feature rather than the
  obstacle — is in `compliance/deletion.py`'s docstring, next to the rest of the
  design.
- **The LIST carries hashes, never numbers.** `GET ""` exists because a request reachable
  only by its opaque id is an obligation a client loses the handle on the moment they
  close the tab. It is the one read on this surface that returns many subjects at once,
  which is exactly why it does not select `phone_e164` — see the route's own docstring.
- **A duplicate is a 200, not a 409.** The caller's intent, "erase this person", is
  already satisfied by the request in flight; an error would tell a support agent that
  something went wrong when nothing did. `already_open` is on the body so a typed client
  can say "an erasure for this person is already running" without inspecting the status
  line.

Filing writes `audit_log` in the same transaction as the request row, under the SAME
`subject_ref` the subject-access export uses — so an auditor can line up both rights for
one person while neither record carries their number. The status read is deliberately
NOT audited: it discloses no personal data, it is the question support is asked most
often, and an audit chain that grows a row per poll stops being readable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import deletion, deletion_proof
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/deletion-requests", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# The `Annotated` alias form rather than a `Depends()` default: B008 is only waived for
# `**/routes.py`, and this module is `deletion_routes.py` — same situation, and same
# resolution, as `export_routes.py` and `dnc_routes.py`.
ErasureRequester = Annotated[Principal, Depends(requires("org:manage"))]
StatusReader = Annotated[Principal, Depends(requires("org:read"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeletionRequestIn(Strict):
    """`extra="forbid"` so a caller cannot smuggle a second selector — a lead id, a
    narrower `scope` — into a request whose whole security argument is "one phone
    number". `scope` in particular is refused rather than ignored: the worker honours no
    narrower scope, so accepting one would record a promise nothing keeps."""

    # E.164, the same gate as the subject-access export. A number we cannot dial is a
    # number we cannot match, and an erasure that silently matches nothing is worse than
    # a 422.
    phone: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")


class ErasureScopeOut(Strict):
    """WHAT was erased, by hash and count — never by id and never by number.

    `calls` and `leads` are lists of hashes rather than uuids on purpose: an auditor
    needs to see that the scope was non-empty and stable across a re-run, and a hash
    proves both without handing the reader a set of primary keys to go and look up.
    """

    calls: list[str]
    leads: list[str]
    transcript_turns_erased: int
    call_extractions_erased: int
    # How many of those calls still had a recording inside the TRAI 90-day floor when
    # the erasure ran — i.e. how many audio files this request could NOT lawfully
    # destroy. NULLABLE and required: a recorded `0` is the claim "none were", while
    # `None` means the proof predates the job recording it at all, and the certificate
    # says those two things in different words rather than collapsing them
    # (`deletion_proof._floor_sentence`). Hard rule 4 is why the older rows stay `None`:
    # they are not back-filled.
    recordings_within_trai_floor: int | None
    # How many audio files this request actually DESTROYED — the ones past the floor,
    # where no law required their retention (DPDP §12(3)). Nullable on the same
    # reasoning as the field above.
    recordings_destroyed: int | None
    # The instant the LAST deferred recording is destroyed on, as the worker recorded it.
    # A string rather than a datetime: it is passed through from a durable JSON document
    # this API does not own, and re-parsing it here would turn a proof written by an
    # older worker into a 500 on the one endpoint whose subject is a person who asked to
    # be erased. Null when nothing was deferred, and also null on every proof written
    # before a deferral had a date at all — the certificate distinguishes the two in
    # words (`deletion_proof._floor_sentence`).
    recording_hold_until: str | None
    # How many of this tenant's knowledge-base documents mention the subject's number
    # (D-179). NULLABLE on the same reasoning as the two counts above, and here it is the
    # difference between "we searched and found none" (`0`) and "this erasure predates the
    # search entirely" (`None`) — the certificate says those in different words
    # (`deletion_proof._kb_sentence`). Never a list of documents: the count is what makes
    # the client's manual step actionable, and which document is a question they answer on
    # their own knowledge screen.
    knowledge_base_documents_matched: int | None
    # How many SEARCHABLE PROJECTIONS of this person's words this erasure destroyed, and
    # how many remembered facts about them (D-503). NULLABLE and required, on the reasoning
    # every count above uses: a recorded `0` is the claim "there were none", and `None`
    # means the proof predates the vector store — the certificate says those in different
    # sentences (`deletion_proof._caller_sentences`) rather than collapsing them.
    #
    # First-class fields rather than a line in `actions` because this is the copy a reader
    # cannot check by eye: a transcript that still held the words would be obvious on the
    # client's own screen, and an embedding that still held them would be obvious nowhere.
    caller_vectors_erased: int | None
    caller_memories_erased: int | None


class ErasureLimitationOut(Strict):
    """One thing the erasure did NOT destroy, and the rule that stopped it.

    Modelled rather than left as prose because this is the part of the certificate a
    regulator tabulates: `outcome` is the machine-readable verdict
    (`retained_under_legal_floor`, `unconfirmed`, ...), `why` and `authority` are
    written for a reader with no access to this codebase, and `count` is populated
    where the erasure could count the affected rows and `None` where it could not.
    """

    what: str
    outcome: str
    why: str
    authority: str
    count: int | None


class ErasureProofOut(Strict):
    """The certificate the subject can be shown. Carries no personal data by
    construction: a subject hash, timestamps, counts, and plain statements of what was
    done to each table.

    `engine_deletion` is a status string rather than a boolean because the honest answer
    today is neither true nor false — Bolna's deletion API is undocumented (a pilot
    gate), and a certificate that claimed an engine-side deletion we cannot demonstrate
    would be the one lie a compliance document must not contain.

    The last four fields are why this is a certificate and not a database row. The proof
    is the DURABLE artifact — filed, forwarded to a regulator, read years later by
    someone who cannot ask us what it meant — so it has to state its own limits. It used
    to state only what it cleared, with `limitations` riding the envelope beside it;
    anyone who filed the proof alone filed a document that says the recording pointer was
    cleared and is silent about the audio still existing. `deletion_proof.certificate`
    builds all four from `deletion.ERASURE_LIMITATIONS`/`ERASURE_EXCEPTIONS`.
    """

    subject_hash: str
    executed_at: str
    scope: ErasureScopeOut
    # Table name -> what was done to it. `dict[str, str]`, not `Any`: the values are
    # sentences we wrote, and the guardrail can see that they are strings.
    actions: dict[str, str]
    engine_deletion: str
    # The same facts as `scope`, in sentences someone without a schema can read.
    erased: list[str]
    not_erased: list[ErasureLimitationOut]
    # The notice text verbatim, so the filed artifact is complete without the response
    # that carried it. Equal to `DeletionRequestOut.limitations` by construction.
    limitations: list[str]
    # Derived from the notice text itself. Hard rule 4: a widened notice produces a NEW
    # statement rather than a correction of an old one, and two copies of a certificate
    # for the same erasure are told apart by this.
    limitations_version: str


class DeletionRequestOut(Strict):
    """The response model IS the output whitelist (BACKEND-PATTERNS §1), and what it
    leaves out is the point: there is no `phone_e164` field, so the number the row keeps
    cannot reach a client through this surface."""

    request_id: UUID
    # The same hash the subject-access export files its audit rows under.
    subject_ref: str
    status: Literal["pending", "completed"]
    requested_at: datetime
    completed_at: datetime | None
    # The worker's proof certificate. TYPED, not a free-form dict: the redaction
    # guardrail inspects response MODELS, so a `dict[str, Any]` here would be a field it
    # is structurally blind to — on the one endpoint whose entire subject is a person
    # who asked to be erased. The shape is built in exactly one place
    # (`workers/retention.execute_deletion_request`), so there is nothing to guess.
    proof: ErasureProofOut | None
    # What the erasure cannot do, stated rather than hidden.
    limitations: list[str]


class DeletionRequestAcceptedOut(DeletionRequestOut):
    already_open: bool


class DeletionRequestSummaryOut(Strict):
    """One row of the index — what the client needs to FIND a request again, and nothing
    else. The docstring on the route below says what is excluded and why.

    `has_certificate` rather than the certificate itself: the list exists to hand back a
    handle, and shipping every proof on the account to render an index would make the
    cheapest read on this surface the largest. It is a separate field rather than inferred
    from `status` because "completed with no proof recorded" is a real state the screen
    must be able to warn about (`deletion_routes` has always modelled `proof` as
    nullable), and a list that inferred it would hide exactly that case.
    """

    request_id: UUID
    subject_ref: str
    status: Literal["pending", "completed"]
    requested_at: datetime
    completed_at: datetime | None
    has_certificate: bool


def _out(record: deletion.DeletionRequestRecord) -> dict[str, Any]:
    # The stored proof is RENDERED, never handed over raw. Two reasons: a raw row
    # validated against `ErasureProofOut` (extra="forbid") turns the day a worker records
    # one more fact into a 500 on this endpoint — which is how an earlier attempt at this
    # change failed — and the row on its own states what was cleared while saying nothing
    # about what survived it.
    return {
        "request_id": record.id,
        "subject_ref": record.subject_ref,
        "status": record.status,
        "requested_at": record.requested_at,
        "completed_at": record.completed_at,
        "proof": deletion_proof.certificate(record.proof),
        "limitations": list(deletion.ERASURE_LIMITATIONS),
    }


@router.post(
    "",
    response_model=DeletionRequestAcceptedOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="File a DPDP erasure request for one phone number — queued, audited, proved",
)
async def request_erasure(
    payload: DeletionRequestIn,
    session: Session,
    request: Request,
    response: Response,
    principal: ErasureRequester,
) -> DeletionRequestAcceptedOut:
    """Write the request, queue the erasure, record that it was asked for.

    A number we hold nothing about is accepted just the same, and produces an
    empty-but-valid certificate. The client cannot know in advance whether they hold
    anything, and "we found nothing" is a complete answer to an erasure request that
    they are entitled to be able to give in writing.
    """
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session

    record = await deletion.request_erasure(
        session, tenant_id=principal.tenant_id, phone_e164=payload.phone
    )

    # In the SAME transaction as the row and the queued job, so there is no state in
    # which an erasure was set in motion without the record of who set it in motion.
    # A deduplicated ask is audited too: a data principal asking twice is a fact about
    # the request history, and "who asked, and what were they told?" has an answer
    # either way.
    await write_audit(
        session,
        action="dpdp.deletion_requested",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="data_subject",
        # The subject is named by hash, never by number — and by the SAME hash the
        # subject-access export uses, so both rights for one person line up.
        object_id=record.subject_ref,
        ip=client_request_ip(request),
        summary={
            "subject_ref": record.subject_ref,
            "request_id": str(record.id),
            "already_open": record.already_open,
            "scope": deletion.DELETION_SCOPE,
        },
    )

    if record.already_open:
        response.status_code = 200
    return DeletionRequestAcceptedOut(**_out(record), already_open=record.already_open)


@router.get(
    "",
    response_model=list[DeletionRequestSummaryOut],
    openapi_extra=permission_meta("org:read"),
    summary="Every erasure request this account has filed — hashes and timestamps only",
)
async def list_requests(
    session: Session,
    _: StatusReader,
    limit: int = Query(default=100, ge=1, le=deletion.MAX_LIST),
) -> list[DeletionRequestSummaryOut]:
    """The account's own register of erasure obligations, newest first.

    Without it a filed request was reachable only by its opaque id, so closing the tab
    lost the handle on an in-flight legal obligation with a statutory clock on it.

    **What this returns and what it deliberately does not.** Data minimisation is the
    whole subject of the feature, so the list is the narrowest thing that answers "which
    erasures do I owe an answer on, and which are done?":

    - `request_id`, `requested_at`, `completed_at`, `status` — the handle and the clock.
    - `has_certificate` — whether the proof exists yet, so the screen can distinguish
      "done, here is the document" from "marked done with no proof recorded", which is
      the one state on this surface a client must not report to a data principal as
      finished.
    - `subject_ref` — the hash, because a client with several erasures in flight needs to
      tell one row from another and match it to their own case file. It is pseudonymous
      rather than anonymous (`deletion.list_requests` says why), which is precisely why it
      is here and the number is not.
    - **NOT `phone_e164`.** An open row still holds the number so the worker can find the
      subject; returning it in a LIST would hand back every number this account has been
      asked to erase in one read — an index of the people who exercised the right, which
      is the inverse of what the right is for (hard rule 6). The column is not selected
      at all.
    - **NOT the proof certificate.** It is available per request from the read below; an
      index that carried every certificate would make the cheapest read the largest.

    `org:read`, matching the single-request read: this discloses no personal data, and an
    admin who may not *cause* an erasure (D-22 refuses `org:manage` while impersonating)
    should still be able to confirm one. Read-as, never act-as.
    """
    return [
        DeletionRequestSummaryOut(
            request_id=summary.id,
            subject_ref=summary.subject_ref,
            # `status` is a Literal on the model and a plain string on the record: the
            # model is the boundary that proves the two spellings still agree.
            status="pending" if summary.status == deletion.STATUS_PENDING else "completed",
            requested_at=summary.requested_at,
            completed_at=summary.completed_at,
            has_certificate=summary.has_certificate,
        )
        for summary in await deletion.list_requests(session, limit=limit)
    ]


@router.get(
    "/{request_id}",
    response_model=DeletionRequestOut,
    openapi_extra=permission_meta("org:read"),
    summary="Has this erasure been executed? Returns the proof certificate once it has",
)
async def read_request(
    request_id: UUID,
    session: Session,
    _: StatusReader,
) -> DeletionRequestOut:
    """The answer to "has my data been erased?", without a support ticket.

    RLS scopes the lookup, so another tenant's request is not found — the same answer a
    nonexistent id gets, deliberately.
    """
    record = await deletion.get_request(session, request_id=request_id)
    return DeletionRequestOut(**_out(record))


__all__ = [
    "DeletionRequestAcceptedOut",
    "DeletionRequestIn",
    "DeletionRequestOut",
    "DeletionRequestSummaryOut",
    "ErasureLimitationOut",
    "ErasureProofOut",
    "ErasureScopeOut",
    "router",
]
