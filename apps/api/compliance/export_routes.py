"""Client-realm endpoint for a DPDP subject access / portability request (SEC-COMP §4).

The flow this serves: a data principal asks the CLIENT "what do you hold about me?";
the client — who is the Data Fiduciary, we are their Processor — asks us. So this is a
client-realm route, and the answer it returns is the client's to hand on.

MOUNTED, and reachable from a screen. This paragraph used to say the opposite — "not
mounted in `main.py` yet … mounting it is a one-line change" — and it was already false:
`main.py` imports and includes this router, and `/c/[slug]/data-rights` now calls it.
`deletion_routes.py` corrected the same sentence in its own docstring and states why it
is worth the edit: a compliance module claiming to be unreachable is exactly the sentence
a reviewer must not have to check for themselves. The delivery channel that paragraph was
waiting on was settled by NOT having one — the document is handed to the caller as a file
and never rendered into the console, so nothing here emails a person's data around.

**Permission: `calls:read_raw`.** Confirmed in `apps/api/core/rbac.py` — it is held by
`owner` in the client realm and `superadmin` in the admin realm, and by nobody else;
`staff` and `operator` do not have it. That is the right gate, and the alternatives are
worse:

- `calls:read` / `leads:read` include `staff`, and this response is a strictly greater
  disclosure than either surface those permissions guard — it is every call, every
  transcript, the lead record and the consent history for one identified human being,
  assembled into a single file that then leaves the building. Whatever the threshold
  for that is, it is not the threshold for viewing a call list.
- `org:manage` is owner-only too but sits in `MUTATING_PERMISSIONS`, which would make
  an impersonating admin refuse it (D-22). This is a read; classifying it as a mutation
  to borrow a stricter check would corrupt what that set means.

`calls:read_raw` is the only permission in the table that already means "you may see
the most sensitive artefact we hold about a caller, and your having seen it is
recorded". The name is a slight stretch — we return the REDACTED transcript here, on
purpose (`export.py`, decision 1) — but the authority it represents is exactly right,
and inventing a permission for a single route is how a role table stops being readable.
("for one unmounted route", this used to say — a leftover from the paragraph above it,
and wrong twice over now: the route is mounted, and the argument never depended on it.)

Every call writes `audit_log`, in the same transaction as the read. An export of one
person's personal data is precisely the event `audit_log` exists to make answerable
later, and the audit row carries a `subject_ref` hash rather than the number (hard
rule 6) — so the record of the disclosure never becomes another copy of what was
disclosed.

**The response is MODELLED, not a free dict**, for the reason `deletion_routes.py` gives
about its own `proof`: `scripts/check_redaction_exposure.py` inspects response MODELS, so
a `dict[str, Any]` is not a field the guardrail judges safe — it is a field the guardrail
cannot see at all. This was the one endpoint in the product whose payload is an entire
named human being, and it was the one endpoint structurally invisible to the check that
exists to keep raw personal data out of responses. Modelling it also gives the generated
TypeScript client something to say about the document (`counts`), which an opaque
`{ [key: string]: unknown }` could not.

The models are `extra="forbid"`, which `deletion_routes.py` warns against for its stored
`proof` — and the distinction is the point. That proof is a DURABLE ROW written by a
worker, so a forbidding model turns "the worker recorded one more fact" into a 500 on a
read. This document is built in one function in this repository
(`compliance/export.build_subject_export`), in the same release as these models, so drift
between the two is a code change rather than old data arriving — and a loud failure in
tests beats `extra="ignore"` silently DROPPING a newly added field from a disclosure that
is supposed to be complete. `tests/subject_export_test.py` pins the two together.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.export import build_subject_export, subject_ref
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/subject-export", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# The `Annotated` alias form rather than a `Depends()` default: this file is
# `export_routes.py`, not `routes.py`, so it sits outside the B008 per-file ignore in
# pyproject — same situation, and same resolution, as `agents/prompt_routes.py`.
SubjectExportReader = Annotated[Principal, Depends(requires("calls:read_raw"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubjectExportIn(Strict):
    """`extra="forbid"` so a caller cannot smuggle a second selector (a lead id, a
    tenant slug) into a request whose whole security argument is "one phone number"."""

    # E.164 (conventions), same pattern as the admin DNC endpoint. A POST rather than a
    # GET for one reason: the identifier IS the personal data, and a GET would write it
    # into access logs, proxy logs and browser history (hard rule 6).
    phone: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")


# --- the document ------------------------------------------------------------------
#
# Timestamps are ISO-8601 STRINGS rather than `datetime`, and ids are strings rather than
# `UUID`, because `export.py` builds them that way on purpose: the document is serialized
# to a file and handed to a person outside this system, and "portable" means readable
# without our code. Retyping them here would silently reformat what leaves the building.


class SubjectExportLeadOut(Strict):
    """The CRM record, as the client holds it.

    `phone_e164` is the subject's OWN number and appears unmasked — `export.py` decision
    3: masking the identifier the subject asked about produces a document they cannot
    check is about them. It is declared here rather than hidden in a dict so
    `check_redaction_exposure` judges it against a named, reasoned allowance instead of
    never seeing it.
    """

    id: str
    phone_e164: str
    name: str | None
    status: str | None
    source: str | None
    # The schema-driven extraction fields (TRD §7) — a per-tenant shape by definition, so
    # this is the one place the document cannot declare its own properties. Acknowledged
    # in `check_redaction_exposure.ACKNOWLEDGED_PASSTHROUGH` with the reason.
    data: dict[str, Any]
    schema_version: int | None
    call_count: int | None
    is_repeat_caller: bool
    created_at: str | None
    updated_at: str | None


class SubjectExportCallOut(Strict):
    """One call, with the audio reported as a fact rather than as a link.

    `recording_available` is a boolean and never a URL (`export.py` decision 2): a
    presigned URL inside a document that gets emailed and forwarded is a bearer
    credential travelling with it.
    """

    call_id: str
    direction: str | None
    started_at: str | None
    duration_s: int | None
    outcome_tag: str | None
    # Model-written prose about the conversation, with every phone-shaped run that is NOT
    # the subject's own masked by `export.mask_foreign_numbers` before it ships.
    summary: str | None
    recording_available: bool


class SubjectExportTurnOut(Strict):
    """One transcript turn. `text` carries `text_redacted`, never the raw column — hard
    rule 5, reinforced rather than relaxed here because this is the one response that
    leaves the client's own screen (`export.py` decision 1). A turn that has not been
    through the redaction pass yet says so (`export.REDACTION_PENDING`) rather than
    falling back to raw."""

    idx: int
    speaker: str | None
    text: str


class SubjectExportTranscriptOut(Strict):
    call_id: str
    turns: list[SubjectExportTurnOut]


class SubjectExportConsentOut(Strict):
    """One consent-ledger entry. `evidence_recorded` is a boolean for the same reason
    the recording is: the evidence is a transcript SPAN, raw by construction, and it
    stays behind the audited raw-transcript path."""

    call_id: str | None
    purpose: str | None
    status: str | None
    captured_at: str | None
    evidence_recorded: bool


class SubjectExportErasureOut(Strict):
    """A completed erasure for this subject, and the audio it is still lawfully holding.

    Present because everything else in this document is keyed on the phone number and an
    erasure destroys every column that carries it — so once one has run, the rest of the
    disclosure is empty and says, in effect, "we hold nothing about you". That is untrue
    while an under-floor recording is sitting on a scheduled destruction, and a §11 answer
    that under-reports is the same defect as one that over-reports.

    `null` on the parent field means no erasure has been completed for this number. It is
    NOT the same as this object with `recordings_pending_destruction = 0`, which means one
    ran and is finished down to the bytes.
    """

    completed_at: str | None
    recordings_pending_destruction: int
    recordings_destroyed_by: str | None


class SubjectExportCountsOut(Strict):
    """What the document contains, stated in the document.

    `leads` is the TRUE number of lead rows this number matched while `lead` carries only
    the most recently updated one, so a second row (a tenant running two agents) is
    visible in the answer rather than silently dropped from it.
    """

    leads: int
    calls: int
    transcript_turns: int
    consent_records: int
    recordings_available: int


class SubjectExportOut(Strict):
    """The whole disclosure, and therefore the whole output whitelist
    (BACKEND-PATTERNS §1)."""

    # The number the request asked about, echoed back unmasked so the recipient can check
    # the document is about them (`export.py` decision 3).
    phone_e164: str
    generated_at: str
    # See `SubjectExportErasureOut` — null means nobody has asked for this number to be
    # erased, and is a different answer from an erasure with nothing left outstanding.
    erasure: SubjectExportErasureOut | None
    lead: SubjectExportLeadOut | None
    calls: list[SubjectExportCallOut]
    transcripts: list[SubjectExportTranscriptOut]
    consent: list[SubjectExportConsentOut]
    counts: SubjectExportCountsOut


@router.post(
    "",
    response_model=SubjectExportOut,
    openapi_extra=permission_meta("calls:read_raw"),
    summary="DPDP subject access/portability export for one phone number — audited",
)
async def subject_export(
    payload: SubjectExportIn,
    session: Session,
    request: Request,
    principal: SubjectExportReader,
) -> SubjectExportOut:
    """Build the document, record that it was built, return it.

    A number we hold nothing about returns an empty-but-valid document, not a 404 —
    and it is audited just the same. "We hold no data about you" is itself a disclosure
    the client made to a data principal, and the useful question six months later is
    "who asked, and what were they told?", which has an answer either way.
    """
    assert principal.tenant_id is not None  # guaranteed by the tenant-scoped session

    document = await build_subject_export(
        session, tenant_id=principal.tenant_id, phone_e164=payload.phone
    )
    # Validated BEFORE the audit write, not after: a document that fails validation is
    # never disclosed, so recording that it was would put a disclosure in the audit trail
    # that never happened — and `audit_log` is append-only (hard rule 4), so that row
    # could only ever be corrected by a compensating entry.
    #
    # `model_validate` rather than a hand-built constructor call: the document is one dict
    # built in one place, and validating it whole means a field added to
    # `build_subject_export` and not declared here FAILS here instead of being quietly
    # dropped from a disclosure that is supposed to be complete.
    modelled = SubjectExportOut.model_validate(document)
    counts = document["counts"]
    lead = document["lead"]

    # AFTER the build, so the audit row can state what was actually disclosed, and in
    # the SAME transaction, so there is no window where a person's data left the system
    # without the record of it (the pattern the raw-transcript route uses).
    await write_audit(
        session,
        action="dpdp.subject_export",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="data_subject",
        # The subject is identified by a hash, never by their number — the audit trail
        # must not become a searchable index of everyone who ever exercised a right.
        object_id=subject_ref(payload.phone),
        ip=client_request_ip(request),
        summary={
            "subject_ref": subject_ref(payload.phone),
            "lead_id": lead["id"] if lead else None,
            "calls": counts["calls"],
            "turns": counts["transcript_turns"],
            "consent_records": counts["consent_records"],
        },
    )
    return modelled


__all__ = [
    "SubjectExportCallOut",
    "SubjectExportConsentOut",
    "SubjectExportCountsOut",
    "SubjectExportIn",
    "SubjectExportLeadOut",
    "SubjectExportOut",
    "SubjectExportTranscriptOut",
    "SubjectExportTurnOut",
    "router",
]
