"""The per-tenant CARRIER compliance application — the reseller stage nothing modelled.

WHAT THIS IS, IN ONE PARAGRAPH
------------------------------
We resell Indian phone numbers to client businesses through a carrier. The carrier
distinguishes a **Direct Brand** — one compliance application, covering the brand's own
calls — from a **Reseller**, which needs *a separate approved compliance application for
each customer*. Calevate sells agents to other businesses, so Calevate is a reseller, and
therefore **every tenant needs its own compliance application, accepted, before that
tenant's number can be rented or assigned**. A purchase then quotes the carrier's
`compliance_application_id`. That is a product finding, not a vendor detail: it puts a
gating, human-signature-bearing stage between "client signs up" and "client has a number",
and before this module none of it existed.
Source: `docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` §5.2.

⚠ EVIDENCE CLASS — READ THIS BEFORE TREATING ANY NUMBER BELOW AS A FACT
-----------------------------------------------------------------------
Everything we believe about the carrier's requirements is

    **REPORTED — research-agent reading, founder-relayed, 12 Sep 2026**

and that is the class the evidence document itself assigns it (§0): `www.plivo.com` is
egress-blocked from this container (re-measured 13 Sep 2026), so **nobody in this
repository has opened the page**, and the carrier account has only just been created.
Under hard rule 11, REPORTED is below VENDOR-PUBLISHED and may not reach money, a wire
value or a client-facing claim without being re-read from the primary source.

Three consequences, and they are the shape of this module rather than a caveat on it:

1. **We model OUR state machine and merely STORE their identifier.** `CarrierStatus` is
   the six states we can know; the carrier's own status strings are mapped onto them by
   `our_status_for_carrier_status`, which REFUSES an unknown one rather than guessing. A
   vendor that renames a status, or a migration to another carrier, then costs one entry
   in that table and no data migration.
2. **Every vendor constraint is ONE named constant with its evidence class and date**, so
   a wrong value is a one-line edit rather than an archaeology exercise. They are grouped
   under "REPORTED CARRIER CONSTRAINTS" below.
3. **What we do NOT know, we do not model.** Their approval SLA is reported as "typically
   5 minutes" for landline series with the 140/160 SLA explicitly *not published* — so
   there is no `expected_decision_at` column and no screen promising a turnaround. A
   promise this repository cannot support is worse than no promise, because a client acts
   on it.

WHY THE STATES ARE THESE SIX
----------------------------
They describe what WE know, which is the only thing a gate of ours may read:

    not_started         a row exists, nothing has been sent
    documents_required  they (or we) came back asking for more
    submitted           sent, waiting on their decision
    accepted            the one state that opens a number
    rejected            refused, with a reason the client can act on
    expired             was accepted and no longer is (a lapse, or the UCC-complaint
                        suspension the evidence document records in §5.6)

`documents_required` and `expired` are the two that a naive design leaves out, and both
are states a client has to be able to SEE: one is "we are waiting on you", the other is
"the thing that used to be true has stopped being true". Collapsing either into `rejected`
would send a client to the wrong next action.

WHAT IS NOT HERE, DELIBERATELY
------------------------------
* **The registry identifier.** `kyc_records.document_ref` already holds this business's
  GSTIN / CIN / Udyam number. Two columns holding one fact is how they start disagreeing,
  so this record says WHICH KIND of document was supplied and where the bytes are, and
  the number on it stays in the one place that already had it.
* **The document bytes.** Object-store keys only, minted by
  `workers/storage.carrier_document_key` — hard rule 2's discipline applied to a client's
  own paperwork. The store is the repo's existing one; there is no second abstraction.
* **A second copy of the carrier's application id beside `phone_numbers`.** A purchase
  knows its tenant, and the tenant is what this row is keyed on.

WHAT A CLIENT MAY DO AND WHAT ONLY OPS MAY DO
---------------------------------------------
A client SUBMITS (they hold the documents; nobody else can produce them). Only an operator
records a DECISION, because the decision is the carrier's and reaches us out of band — a
client who could mark their own application `accepted` would be opening the number gate on
a decision nobody made, which is the same argument that keeps `kyc_routes.py` read-only and
a sharper one here, since the carrier would then refuse at purchase time with our money
already committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.models import CARRIER_APPLICATION_ACCEPTED
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.transition import transition_status

# --------------------------------------------------------------------------------------
# REPORTED CARRIER CONSTRAINTS
#
# Every constant in this block is REPORTED — research-agent reading, founder-relayed,
# 12 Sep 2026, `docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` §5.2 —
# and NOT verified against the carrier's own documentation, which is egress-blocked from
# this container (`www.plivo.com`, measured 13 Sep 2026). They are gathered here, one
# named constant each, so that re-reading the primary source is a small, local edit.
#
# They are enforced AT THE DOOR rather than in the schema on purpose: a CHECK constraint
# carrying a reported number would need a migration to correct, and would keep refusing
# rows long after we learned better.
# --------------------------------------------------------------------------------------

#: The carrier we hold an account with. Stored on every row rather than assumed, because
#: an application identifier is meaningless without knowing whose it is.
CARRIER: Final = "plivo"

#: The largest single document the carrier is reported to accept (~5 MB per file). We
#: refuse above it at the door, while the client still has the file in front of them —
#: accepting it and having the carrier refuse it days later is the same outcome with
#: nobody watching. REPORTED, 12 Sep 2026.
CARRIER_MAX_DOCUMENT_BYTES: Final = 5 * 1024 * 1024

#: The longest filename the carrier is reported to accept (~99 characters). We do not
#: truncate silently: a client who named the file "GST certificate — Hyderabad branch"
#: should be told, not have it renamed behind their back. REPORTED, 12 Sep 2026.
CARRIER_MAX_FILENAME_CHARS: Final = 99

#: The formats the carrier is reported to accept: PDF, JPEG, PNG. Mapped from the file
#: EXTENSION to the content type WE store the object under and WE would declare to the
#: carrier — never the uploader's declared type, for the reason `kb/uploads.py` argues at
#: length: an object store replays the type it was given, and a presigned GET then renders
#: attacker-chosen bytes in the browser of the operator our own console told to click the
#: link. REPORTED, 12 Sep 2026.
CARRIER_DOCUMENT_CONTENT_TYPES: Final[dict[str, str]] = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

#: What the client must supply ONE of. REPORTED, 12 Sep 2026: a GST certificate with an
#: active GSTIN, a Certificate of Incorporation with a CIN, or a Udyam Registration
#: Certificate. **PAN alone is refused** — which is why there is no PAN member, and why
#: `PAN_ALONE_REFUSED_REASON` exists to say so in the client's own words rather than
#: leaving them to discover it from the carrier.
DocumentKind = Literal["gst_certificate", "certificate_of_incorporation", "udyam_registration"]

#: What the first application must carry: the signature of an authorised signatory AND a
#: visible company seal. REPORTED, 12 Sep 2026. Enforced as a REQUIREMENT on the first
#: submission (see `submit_application`) rather than as an image check we cannot perform —
#: no code in this repository can see a seal, and pretending otherwise would be a control
#: in name only.
SIGNED_APPLICATION_REQUIRED_FIRST: Final = True

# --------------------------------------------------------------------------------------
# OUR STATE MACHINE
# --------------------------------------------------------------------------------------

CarrierStatus = Literal[
    "not_started", "documents_required", "submitted", "accepted", "rejected", "expired"
]

#: The edges, in one table (BACKEND-PATTERNS §5: "state machines get a central transition
#: table"). Read it as "from -> the states it may become".
#:
#: `accepted -> expired` is the only exit from acceptance, and it is deliberately not
#: `accepted -> rejected`: a carrier that suspends a live application after unresolved UCC
#: complaints (§5.6) has not re-decided the original application, it has stopped honouring
#: it, and the client's next action ("re-apply") is the one `expired` describes.
#:
#: Every terminal-looking state has a way back to `submitted`, because every one of them
#: is a state a business can remedy — that is the entire point of the client-facing screen.
CARRIER_APPLICATION_TRANSITIONS: Final[dict[CarrierStatus, frozenset[CarrierStatus]]] = {
    "not_started": frozenset({"submitted"}),
    "documents_required": frozenset({"submitted"}),
    "submitted": frozenset({"documents_required", "accepted", "rejected"}),
    "accepted": frozenset({"expired"}),
    "rejected": frozenset({"submitted"}),
    "expired": frozenset({"submitted"}),
}

#: The states a client may submit FROM. Derived from the table above rather than retyped,
#: so an edge added there cannot be missed here — the defect class D-103/D-105 exist for.
SUBMITTABLE_FROM: Final[tuple[CarrierStatus, ...]] = tuple(
    state for state, allowed in CARRIER_APPLICATION_TRANSITIONS.items() if "submitted" in allowed
)

#: The four states an OPERATOR may move an application into. A narrower type than
#: `CarrierStatus` because the other two are not decisions anybody makes: `not_started` is
#: where a row begins and `submitted` is the CLIENT's act. Typing the ops route on this
#: rather than on `CarrierStatus` is what stops "record the carrier's decision: submitted"
#: from being expressible at all.
CarrierDecision = Literal["documents_required", "accepted", "rejected", "expired"]

#: The states an OPERATOR may move an application into, with the states each may come
#: from. Derived from the transition table rather than retyped, for `SUBMITTABLE_FROM`'s
#: reason.
OPERATOR_DECISIONS: Final[dict[CarrierDecision, tuple[CarrierStatus, ...]]] = {
    decision: tuple(
        state for state, allowed in CARRIER_APPLICATION_TRANSITIONS.items() if decision in allowed
    )
    for decision in ("documents_required", "accepted", "rejected", "expired")
}

#: THE CARRIER'S VOCABULARY -> OURS. This is the whole of the translation layer, and it is
#: a table rather than a `str.lower()` because their strings are REPORTED: we have read
#: none of them from an API response, so each entry is a guess we are recording as a guess.
#: `our_status_for_carrier_status` REFUSES an unmapped value instead of storing it, which
#: is what keeps a vendor string out of our truth (hard rule 11 — a value we cannot map is
#: a value we have not verified, and the honest response is to say so, not to pass it on).
CARRIER_STATUS_MAP: Final[dict[str, CarrierStatus]] = {
    "approved": "accepted",
    "accepted": "accepted",
    "rejected": "rejected",
    "denied": "rejected",
    "pending": "submitted",
    "in_review": "submitted",
    "submitted": "submitted",
    "documents_required": "documents_required",
    "incomplete": "documents_required",
    "expired": "expired",
    "suspended": "expired",
}


def our_status_for_carrier_status(carrier_status: str) -> CarrierStatus:
    """Map the carrier's own word onto ours, or REFUSE.

    The refusal is the point. Their strings are REPORTED and unverified, so an unmapped
    value means the carrier said something we have never seen — and the two wrong answers
    available are "store their string as our truth" (hard rule 11) and "guess the nearest
    state" (which, guessed towards `accepted`, opens a number gate on nothing). Refusing
    tells the operator exactly what happened and leaves them the explicit decision route.
    """
    mapped = CARRIER_STATUS_MAP.get(carrier_status.strip().lower())
    if mapped is None:
        raise ProblemError.business_rule(
            "carrier_status_unrecognised",
            f"The carrier reported a status we do not recognise: {carrier_status!r}.",
            remediation=(
                "Record the decision explicitly instead, using the status that matches "
                "what the carrier's console shows — and tell engineering what the carrier "
                "called it, so the mapping can be corrected."
            ),
        )
    return mapped


# --------------------------------------------------------------------------------------
# THE CLIENT-FACING SENTENCES
#
# Defined ONCE and shared by the dial gate, the number-provisioning gate and the client's
# own screen — the discipline `KYC_MISSING_REASON` and `SPEND_CAP_REASON` follow, so one
# condition is never explained three different ways on three screens.
# --------------------------------------------------------------------------------------

CARRIER_APPLICATION_MISSING_REASON: Final = (
    "This business has no carrier compliance application on file. Our carrier approves "
    "each client business separately before a phone number can be rented for them, so "
    "nothing can be dialled from a number we supply until that application is accepted."
)

PAN_ALONE_REFUSED_REASON: Final = (
    "A PAN card on its own is not accepted as proof of business registration. Send a GST "
    "certificate, a Certificate of Incorporation, or a Udyam Registration certificate."
)


def carrier_application_not_accepted_reason(status: str) -> str:
    """Names the state the application is actually in, because the next action differs.

    `submitted` means we are waiting on the carrier; `documents_required` and `rejected`
    mean the client owes us something; `expired` means an approval that existed has
    lapsed. One flat "not accepted" would send all four to the same wrong place — the
    mistake `kyc_not_verified_reason` already avoids.
    """
    return (
        f"This business's carrier compliance application is {status.replace('_', ' ')}. "
        "Our carrier approves each client business separately, and only an accepted "
        "application allows a number we supply to be used."
    )


# --------------------------------------------------------------------------------------
# THE RECORD
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CarrierApplicationRecord:
    """What we know about this tenant's application, for whoever is asking.

    Absence is a VALUE, not an exception: every tenant starts with no row, and a `None`
    return would push each caller into inventing the same "nothing filed yet" shape
    (`kyc.NOT_RECORDED` and `registration.NOT_RECORDED` make the same argument).
    """

    # False = no row at all, the normal state of a new account, and a different fact from
    # `status='not_started'` ("we have begun and are nowhere").
    recorded: bool
    application_id: UUID | None
    carrier: str | None
    status: CarrierStatus | None
    # THEIRS. What a number purchase has to quote; meaningless to us otherwise.
    carrier_application_id: str | None
    document_kind: str | None
    document_filename: str | None
    document_object_ref: str | None
    signed_application_ref: str | None
    rejection_reason: str | None
    submitted_at: datetime | None
    decided_at: datetime | None

    @property
    def is_accepted(self) -> bool:
        """The single predicate every gate asks. Computed here rather than in each caller
        so the dial gate, the provisioning gate, the purchase path and the client's own
        screen can never answer "is `submitted` good enough" differently."""
        return self.status == CARRIER_APPLICATION_ACCEPTED


NOT_RECORDED: Final = CarrierApplicationRecord(
    recorded=False,
    application_id=None,
    carrier=None,
    status=None,
    carrier_application_id=None,
    document_kind=None,
    document_filename=None,
    document_object_ref=None,
    signed_application_ref=None,
    rejection_reason=None,
    submitted_at=None,
    decided_at=None,
)

_SELECT = (
    "SELECT id, carrier, status, carrier_application_id, document_kind, document_filename, "
    "document_object_ref, signed_application_ref, rejection_reason, submitted_at, decided_at "
    "FROM carrier_compliance_applications WHERE tenant_id = :tid AND carrier = :carrier"
)


async def read_carrier_application(
    session: AsyncSession, *, tenant_id: UUID, carrier: str = CARRIER
) -> CarrierApplicationRecord:
    """This tenant's application, on the caller's RLS-scoped session.

    Hard rule 1: `tenant_id` is a predicate AND the session runs under RLS. The predicate
    is not the isolation — the GUC is — but a read whose predicate names the tenant cannot
    silently start returning a neighbour's row if a policy is ever loosened; it returns
    zero rows twice over. A session scoped elsewhere, or one with no GUC at all, gets
    `NOT_RECORDED`, which is the correct answer in both cases: this session cannot see an
    application, so as far as it is concerned there is none.
    """
    row = (await session.execute(text(_SELECT), {"tid": tenant_id, "carrier": carrier})).first()
    if row is None:
        return NOT_RECORDED
    return CarrierApplicationRecord(
        recorded=True,
        application_id=row[0],
        carrier=str(row[1]),
        status=_as_status(str(row[2])),
        carrier_application_id=row[3],
        document_kind=row[4],
        document_filename=row[5],
        document_object_ref=row[6],
        signed_application_ref=row[7],
        rejection_reason=row[8],
        submitted_at=row[9],
        decided_at=row[10],
    )


def _as_status(value: str) -> CarrierStatus:
    """Narrow a status read back from the database to the Literal.

    The CHECK constraint is the enforcement; this is the type checker's share of it. A
    value outside the set means the constraint was changed without this module, which is a
    bug to raise rather than a state to carry.
    """
    if value not in CARRIER_APPLICATION_TRANSITIONS:
        raise ValueError(f"unknown carrier application status in the database: {value!r}")
    return value


# --------------------------------------------------------------------------------------
# WHAT COMES IN THE DOOR
# --------------------------------------------------------------------------------------

#: Path separators and control characters out of a name we store and display. The filename
#: never reaches an object key (`carrier_document_key` builds keys from ids alone), so what
#: this protects is the console and the carrier's own form, not the store.
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def classify_document(filename: str) -> tuple[str, str]:
    """`(extension, content_type)` for an accepted upload, or a refusal they can act on.

    The EXTENSION decides, and the client's declared `Content-Type` is ignored entirely —
    browsers send `application/octet-stream` for half of everything and a hostile client
    can say anything, while the type we store is the type a browser will later be handed.
    One canonical answer, derived from a list we control, closes both.
    """
    _, _, raw = filename.rpartition(".")
    extension = raw.strip().lower()
    content_type = CARRIER_DOCUMENT_CONTENT_TYPES.get(extension)
    if content_type is None:
        raise ProblemError.business_rule(
            "carrier_document_kind_unsupported",
            "The carrier accepts PDF, JPEG and PNG files only.",
            remediation=(
                "Send the certificate as a PDF, or a clear photograph or scan saved as JPEG or PNG."
            ),
        )
    return extension, content_type


def assert_document_within_limits(*, filename: str, size_bytes: int) -> str:
    """Refuse an oversized file or an overlong name, and return the name we will store.

    Both ceilings are the carrier's (REPORTED, above), and both are checked HERE rather
    than after the upload has been stored and the application submitted: a refusal that
    arrives while the client still has the file open costs them ten seconds, and one that
    arrives from the carrier three days later costs them the week.
    """
    if size_bytes > CARRIER_MAX_DOCUMENT_BYTES:
        raise ProblemError(
            kind="validation",
            code="carrier_document_too_large",
            title="That file is too large for the carrier",
            detail=(
                "The carrier accepts files up to about "
                f"{CARRIER_MAX_DOCUMENT_BYTES // (1024 * 1024)} MB each."
            ),
            remediation=(
                "Send a smaller scan — a certificate scanned in black and white at 200 dpi "
                "is usually well under a megabyte."
            ),
        )
    cleaned = _UNSAFE_NAME.sub("", filename).strip()
    if not cleaned:
        raise ProblemError(
            kind="validation",
            code="carrier_document_filename_required",
            title="That file has no usable name",
            detail="The carrier's form needs a filename it can display.",
            remediation=(
                "Rename the file to something like 'gst-certificate.pdf' and send it again."
            ),
        )
    if len(cleaned) > CARRIER_MAX_FILENAME_CHARS:
        raise ProblemError(
            kind="validation",
            code="carrier_document_filename_too_long",
            title="That filename is too long for the carrier",
            detail=(
                "The carrier accepts filenames of up to about "
                f"{CARRIER_MAX_FILENAME_CHARS} characters."
            ),
            # Deliberately not truncated for them: a document that arrives at the carrier
            # under a name the client did not choose is one they cannot find again.
            remediation="Shorten the filename and send it again.",
        )
    return cleaned


# --------------------------------------------------------------------------------------
# THE TRANSITIONS
# --------------------------------------------------------------------------------------

_SUBMIT = """
INSERT INTO carrier_compliance_applications (
    id, tenant_id, carrier, status, document_kind, document_object_ref, document_filename,
    signed_application_ref, rejection_reason, submitted_at, decided_at, created_at, updated_at
) VALUES (
    :id, :tid, :carrier, 'submitted', :kind, :doc_ref, :filename,
    :signed_ref, NULL, now(), NULL, now(), now()
)
ON CONFLICT (tenant_id, carrier) DO UPDATE SET
    status = 'submitted',
    document_kind = EXCLUDED.document_kind,
    document_object_ref = EXCLUDED.document_object_ref,
    document_filename = EXCLUDED.document_filename,
    signed_application_ref = COALESCE(
        EXCLUDED.signed_application_ref, carrier_compliance_applications.signed_application_ref
    ),
    rejection_reason = NULL,
    recorded_by_admin_id = NULL,
    submitted_at = now(),
    decided_at = NULL,
    updated_at = now()
WHERE carrier_compliance_applications.status IN :from_states
RETURNING id
"""


#: `IN :from_states` as an EXPANDING bind rather than an interpolated tuple: the states are
#: our own source text either way, but binding them means the guard is a parameter of one
#: compiled statement instead of a string built per call — which is also the shape
#: `check_raw_sql` wants every value to enter SQL through.
_SUBMIT_STMT = text(_SUBMIT).bindparams(bindparam("from_states", expanding=True))


async def submit_application(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    application_id: UUID,
    document_kind: DocumentKind,
    document_object_ref: str,
    document_filename: str,
    signed_application_ref: str | None,
    carrier: str = CARRIER,
) -> UUID:
    """Record that this tenant has sent us their carrier paperwork. Returns the row id.

    **ONE STATEMENT, AND THE GUARD IS IN IT** (BACKEND-PATTERNS §5). The upsert's
    `DO UPDATE ... WHERE status IN (...)` is the compare-and-swap: two clients pressing
    submit at the same moment both reach the database and exactly one row is written, with
    no window between reading the status and acting on it. A read-then-write here would let
    a second submission overwrite the document references of a first one that was already
    in front of the carrier, and "what did we actually send them" would stop being
    answerable.

    Zero rows means the guard refused, and the discriminating read below says which of the
    two refusals it was — the shape `db/transition.transition_status` uses, open-coded here
    because that helper CASes an existing row by id and this statement has to create the
    row when there is none. It runs only on the losing path and writes nothing, so it
    cannot reintroduce the race.

    `application_id` is supplied by the caller rather than minted here because the object
    keys are built from it: the documents are stored BEFORE the row is written, so that a
    successful submission can never point at bytes that are not there. The cost of the
    other ordering is a row claiming documents the store never received; the cost of this
    one is an orphaned object when the CAS loses, which is a prefix listing away from being
    cleaned and harms nobody.

    `rejection_reason` and `recorded_by_admin_id` are CLEARED: they belong to the decision
    that has just been superseded, and a resubmitted application still showing the last
    refusal is a screen that lies to the client about where they stand.
    """
    row = (
        await session.execute(
            _SUBMIT_STMT,
            {
                "from_states": list(SUBMITTABLE_FROM),
                "id": application_id,
                "tid": tenant_id,
                "carrier": carrier,
                "kind": document_kind,
                "doc_ref": document_object_ref,
                "filename": document_filename,
                "signed_ref": signed_application_ref,
            },
        )
    ).first()
    if row is not None:
        return UUID(str(row[0]))

    current = await read_carrier_application(session, tenant_id=tenant_id, carrier=carrier)
    assert_submittable(current)
    # Submittable, yet the CAS matched nothing: the row moved between the two statements,
    # which is the ordinary lost-race answer and not a state to report as a bug.
    raise ProblemError.conflict(  # pragma: no cover - requires losing a race in-flight
        "carrier_application_not_submittable",
        "This business's compliance application changed while it was being sent.",
        remediation="Reload the page and try again — someone else may have changed it.",
    )


def assert_first_application_is_signed(
    record: CarrierApplicationRecord, *, signed_application_supplied: bool
) -> None:
    """Refuse a FIRST application that carries no signed, sealed form.

    REPORTED, 12 Sep 2026: the first application must be signed by an authorised signatory
    and carry a visible company seal, and PAN alone is refused. Only the first — a later
    resubmission may be a replacement certificate — so "first" is read as "we hold no
    signed form for this application yet", which is the fact the column actually records.

    **What this does NOT claim to check is the seal.** No code in this repository can look
    at an image and see one, and a control that pretended to would be worse than none: it
    would let a reviewer believe the check had happened. What is enforced is that the form
    is PRESENT, with the requirement stated in words the client can act on, and a human at
    the carrier is the thing that reads it.
    """
    if not SIGNED_APPLICATION_REQUIRED_FIRST:  # pragma: no cover - constant, one edit
        return
    if signed_application_supplied or record.signed_application_ref is not None:
        return
    raise ProblemError(
        kind="validation",
        code="carrier_signed_application_required",
        title="The first application needs the signed form",
        detail=(
            "The carrier requires a business's first compliance application to be signed "
            "by an authorised signatory and to carry a visible company seal."
        ),
        remediation=(
            "Print the application form, have an authorised signatory sign it, stamp it "
            "with the company seal, and send a scan alongside the registration "
            "certificate. " + PAN_ALONE_REFUSED_REASON
        ),
    )


def assert_submittable(record: CarrierApplicationRecord) -> None:
    """Raise if this application may not be (re)submitted right now.

    ONE implementation of the two refusals, called from TWO places on purpose. The route
    asks it BEFORE storing any bytes, so a client whose application is already with the
    carrier is refused without spending storage on documents nobody will read; the CAS in
    `submit_application` asks it again afterwards and remains the authority, because only
    the CAS can tell a stale read from a current one. Sharing the function is what keeps
    the two answers identical — the alternative is a screen that refuses in two different
    sentences depending on how fast the client clicked.
    """
    if record.status == "submitted":
        raise ProblemError.conflict(
            "carrier_application_in_review",
            "This business's compliance application is already with the carrier.",
            remediation=(
                "Wait for the carrier's decision. If a document needs replacing, tell us "
                "and we will ask the carrier to reopen the application."
            ),
        )
    if record.status == CARRIER_APPLICATION_ACCEPTED:
        raise ProblemError.conflict(
            "carrier_application_already_accepted",
            "This business's compliance application has already been accepted.",
            remediation=(
                "Nothing further is needed. Numbers can be arranged for this account now."
            ),
        )


async def record_carrier_decision(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    application_id: UUID,
    status: CarrierDecision,
    recorded_by_admin_id: UUID,
    carrier_application_id: str | None = None,
    rejection_reason: str | None = None,
) -> bool:
    """Move the application into the state the CARRIER put it in. True when this call moved it.

    CAS, through the repo's one state-transition primitive (`db/transition.py`): the
    allowed source states go into the WHERE clause, so an operator recording a decision on
    an application a colleague has already decided gets a 409 naming the state found rather
    than overwriting it. Idempotent when the row already holds the target state — the
    second click of a button, or the retry of a request whose response was lost.

    `decided_at` is stamped by the DATABASE, in the same statement, and only for the states
    that ARE a decision. An operator who could supply the date on which the carrier decided
    could supply any date, and the whole value of the column to an auditor is that it is the
    moment the system observed the fact (`kyc_records.verified_at` means the same thing for
    the same reason).

    The CHECK constraints behind this write are the real enforcement of "an acceptance
    names the carrier's id" and "a rejection names its reason"; the route pre-empts them so
    an operator reads a problem+json naming the missing field instead of a 500 out of an
    IntegrityError.
    """
    from_statuses = OPERATOR_DECISIONS[status]
    decided = status in ("accepted", "rejected", "expired")
    return await transition_status(
        session,
        table="carrier_compliance_applications",
        entity="Carrier compliance application",
        row_id=application_id,
        to_status=status,
        from_statuses=from_statuses,
        extra_set=(
            "carrier_application_id = COALESCE(:carrier_ref, carrier_application_id), "
            "rejection_reason = :reason, "
            "recorded_by_admin_id = :admin_id, "
            f"decided_at = {'now()' if decided else 'NULL'}"
        ),
        # Belt and braces beside RLS: the row id is the caller's and the tenant is the
        # session's, and a mismatch must be "no such application" rather than a write.
        visible_where="tenant_id = :tid",
        params={
            "carrier_ref": carrier_application_id,
            "reason": rejection_reason,
            "admin_id": recorded_by_admin_id,
            "tid": tenant_id,
        },
    )


async def assert_carrier_application_accepted(
    session: AsyncSession, *, tenant_id: UUID, carrier: str = CARRIER
) -> None:
    """The acquisition-side gate. Raises; writes nothing.

    Asked wherever a number would be RENTED FOR or RECORDED AGAINST this tenant on our
    carrier account — `campaigns/number_supply.buy_number` before a rupee is spent, and
    `agents/service.provision_number` when the row being written says the number is ours
    (`engine_owned`). The carrier's rule is that a reseller's customer must have an
    accepted application of their own before a number can be purchased, and that the
    purchase then carries the application's identifier; buying first and discovering the
    refusal afterwards spends money on a number that cannot be used.

    Tier-blind, and unlike the dial-time blocker it does not ask which numbers the tenant
    already holds: this is the moment a number would BECOME one of ours, so there is
    nothing yet to scope it by. `compliance/kyc.py` draws the same line between its own
    two gates and for the same reason — the provisioning gate closes the risk, the dial
    gate must not halt clients whose paperwork was never in question.

    ONE machine code for both failures — `carrier_application_not_accepted` — because the
    operator's next action is the same either way (get the client's application through);
    the DETAIL distinguishes "nothing filed" from "filed and not accepted", which is what
    `GET /v1/compliance/carrier-application` then shows in full. The dial gate splits them
    into two rule NAMES instead, because a launch screen lists blockers by rule and the
    person reading that list wants the two states apart. `assert_kyc_verified_for_
    provisioning` makes exactly this trade, and this follows it deliberately rather than
    inventing a third convention.
    """
    record = await read_carrier_application(session, tenant_id=tenant_id, carrier=carrier)
    if record.is_accepted:
        return
    detail = (
        CARRIER_APPLICATION_MISSING_REASON
        if not record.recorded or record.status == "not_started"
        else carrier_application_not_accepted_reason(str(record.status))
    )
    raise ProblemError.business_rule(
        "carrier_application_not_accepted",
        detail,
        remediation=(
            "Send the client's business registration document — a GST certificate, a "
            "Certificate of Incorporation or a Udyam Registration certificate — with the "
            "signed, sealed application form, and record the carrier's decision before "
            "arranging a number."
        ),
    )


async def ensure_application_row(
    session: AsyncSession, *, tenant_id: UUID, carrier: str = CARRIER
) -> UUID:
    """The row id for this tenant's application, creating a `not_started` one if needed.

    What ops needs before they can record anything: the decision path CASes an existing
    row, and an operator relaying a carrier decision for a client who applied by email
    would otherwise have nothing to CAS. `ON CONFLICT DO NOTHING` then a read, so two
    operators opening the same client at once cannot mint two rows — the UNIQUE on
    `(tenant_id, carrier)` is the authority, not a probe.
    """
    await session.execute(
        text(
            "INSERT INTO carrier_compliance_applications "
            "(id, tenant_id, carrier, status, created_at, updated_at) "
            "VALUES (:id, :tid, :carrier, 'not_started', now(), now()) "
            "ON CONFLICT (tenant_id, carrier) DO NOTHING"
        ),
        {"id": uuid7(), "tid": tenant_id, "carrier": carrier},
    )
    row = (
        await session.execute(
            text(
                "SELECT id FROM carrier_compliance_applications "
                "WHERE tenant_id = :tid AND carrier = :carrier"
            ),
            {"tid": tenant_id, "carrier": carrier},
        )
    ).first()
    if row is None:  # pragma: no cover - RLS would have to hide a row we just inserted
        raise ProblemError.not_found("Carrier compliance application")
    return UUID(str(row[0]))


__all__ = [
    "CARRIER",
    "CARRIER_APPLICATION_MISSING_REASON",
    "CARRIER_APPLICATION_TRANSITIONS",
    "CARRIER_DOCUMENT_CONTENT_TYPES",
    "CARRIER_MAX_DOCUMENT_BYTES",
    "CARRIER_MAX_FILENAME_CHARS",
    "CARRIER_STATUS_MAP",
    "NOT_RECORDED",
    "OPERATOR_DECISIONS",
    "PAN_ALONE_REFUSED_REASON",
    "SUBMITTABLE_FROM",
    "CarrierApplicationRecord",
    "CarrierDecision",
    "CarrierStatus",
    "DocumentKind",
    "assert_carrier_application_accepted",
    "assert_document_within_limits",
    "assert_first_application_is_signed",
    "assert_submittable",
    "carrier_application_not_accepted_reason",
    "classify_document",
    "ensure_application_row",
    "our_status_for_carrier_status",
    "read_carrier_application",
    "record_carrier_decision",
    "submit_application",
]
