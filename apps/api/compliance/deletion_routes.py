"""Client-realm endpoints for a DPDP erasure request and its certificate (SEC-COMP §4).

The twin of `export_routes.py`, and shaped the same way on purpose. A data principal
asks the CLIENT to erase them; the client — the Data Fiduciary, we are their Processor —
asks us. So this is a client-realm surface, and the certificate it returns is the
client's to hand on.

This router is NOT mounted in `main.py` — the integrator mounts it. The variable is
`router`, as everywhere else in this package.

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

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import deletion, deletion_proof
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import requires
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
    # destroy. NULLABLE and required: `None` means the proof was written by an erasure
    # job that did not record it, and the certificate says so in words rather than
    # certifying a zero it cannot support (`deletion_proof._floor_sentence`). The job
    # counts them today (`floor_recordings=` on its result) but stores them nowhere;
    # `deletion.FLOOR_COUNT_KEY` is the name both halves of that change use.
    recordings_within_trai_floor: int | None


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
        ip=request.client.host if request.client else None,
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
    "ErasureLimitationOut",
    "ErasureProofOut",
    "ErasureScopeOut",
    "router",
]
