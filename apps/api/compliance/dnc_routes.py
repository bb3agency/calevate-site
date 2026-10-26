"""Do-not-call endpoints (SEC-COMP §3, hard rule 5).

This router is NOT mounted here — the integrator mounts it.

Two shapes worth explaining before someone "tidies" them:

- **Checking a number is a POST**, not `GET /v1/dnc/check?phone=…`. The identifier IS
  the personal data, and a GET writes it into access logs, proxy logs, referrers and
  browser history — the same reasoning as the subject-access export.
- **Adding is `leads:dispatch`**, the permission that already governs who may cause a
  call to be placed. Suppressing a number is the same decision in the other direction,
  so it needs the same authority — not a new permission nobody has been granted.

Removal is narrow rather than privileged: the client may delete an entry they typed in
themselves, and may not delete one that records a consumer's opt-out (see
`REMOVABLE_SOURCES` in `compliance/dnc.py`). Making removal admin-realm instead would
have produced an unreachable route — `admin:tenants` is a MUTATING permission and D-22
refuses those while impersonating, so no admin principal both sees a tenant's rows and
may write them.

A consumer's opt-out is RESTORED rather than removed (`POST /{id}/restore`): a separate
route that takes an attested ground, refuses on a newer opt-out the client was not shown,
and is withheld from a view-as session. `GET /{id}/evidence` shows what was recorded first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import dnc
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import assert_view_as_may, client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/dnc", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is only waived for
# `**/routes.py`, and this module is `dnc_routes.py` (same situation as
# `agents/prompt_routes.py`).
Dispatcher = Annotated[Principal, Depends(requires("leads:dispatch"))]
Reader = Annotated[Principal, Depends(requires("leads:read"))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddNumbersIn(Strict):
    # Raw as pasted: 10-digit Indian mobiles, +91 forms and spaced-out numbers all
    # arrive here and `normalize_phone` decides. What it cannot normalize is counted
    # malformed rather than dialled on a guess.
    numbers: list[str] = Field(min_length=1, max_length=dnc.MAX_NUMBERS_PER_ADD)
    source: Literal["customer_request", "call_optout", "manual", "regulator"] = "manual"


class AddNumbersOut(Strict):
    """Counts, never numbers — see the module docstring in `compliance/dnc.py`."""

    added: int
    already_suppressed: int
    malformed: int


class DncEntryOut(Strict):
    id: UUID
    #: In full (D-436). A suppression list a client cannot read back is a list they
    #: cannot check against the caller who is complaining at them.
    phone_e164: str
    scope: str
    source: str | None
    added_at: datetime
    # False for global entries: the UI should not offer a button that RLS will refuse.
    removable: bool
    # A person-sourced opt-out that may be restored on an attested ground (`dnc.restore_optout`).
    restorable: bool


class CheckIn(Strict):
    phone: str = Field(min_length=8, max_length=20)


class CheckOut(Strict):
    valid: bool
    suppressed: bool
    scope: str | None


@router.post(
    "",
    response_model=AddNumbersOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Suppress numbers — live before the next dispatch tick (hard rule 5)",
)
async def add_numbers(
    payload: AddNumbersIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> AddNumbersOut:
    assert principal.tenant_id is not None
    result = await dnc.add_numbers(
        session,
        tenant_id=principal.tenant_id,
        raw_numbers=payload.numbers,
        source=payload.source,
    )
    await write_audit(
        session,
        action="dnc.added",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="dnc_list",
        object_id=None,
        ip=client_request_ip(request),
        # Counts and the reason. The numbers are the sensitive part of this request and
        # the audit row is read by more people than the endpoint.
        summary={
            "added": result.added,
            "already_suppressed": result.already_suppressed,
            "malformed": result.malformed,
            "source": payload.source,
        },
    )
    return AddNumbersOut(
        added=result.added,
        already_suppressed=result.already_suppressed,
        malformed=result.malformed,
    )


@router.get(
    "",
    response_model=list[DncEntryOut],
    openapi_extra=permission_meta("leads:read"),
    summary="The suppression list — this tenant's entries and the global ones",
)
async def list_entries(
    session: Session,
    _: Reader,
    limit: int = Query(default=100, ge=1, le=dnc.MAX_LIST),
) -> list[DncEntryOut]:
    entries = await dnc.list_entries(session, limit=limit)
    return [
        DncEntryOut(
            id=entry.id,
            phone_e164=entry.phone_e164,
            scope=entry.scope,
            source=entry.source,
            added_at=entry.added_at,
            removable=entry.removable,
            restorable=entry.restorable,
        )
        for entry in entries
    ]


@router.post(
    "/check",
    response_model=CheckOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Is this number suppressed? (POST: the identifier IS the personal data)",
)
async def check(
    payload: CheckIn,
    session: Session,
    principal: Reader,
) -> CheckOut:
    assert principal.tenant_id is not None
    result = await dnc.check_number(session, tenant_id=principal.tenant_id, raw=payload.phone)
    return CheckOut(valid=result.valid, suppressed=result.suppressed, scope=result.scope)


@router.delete(
    "/{entry_id}",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Undo a hand-added suppression — never a consumer opt-out, always audited",
)
async def remove(
    entry_id: UUID,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> None:
    """204, and the two alternatives were both worse.

    `{"status": "removed"}` said nothing a 200 on a DELETE did not already say, in a
    shape the generated TypeScript client cannot describe and the redaction guardrail
    cannot inspect — the whole class of defect D-71 and D-75 fixed elsewhere. Echoing
    the entry back was the other option and is the one to avoid hardest: the row we
    just deleted holds a phone number, and the response to "please forget this" is not
    the place to repeat it. What `remove_entry` returns is for the AUDIT row, which is
    where "who un-suppressed what, and what kind of entry it was" belongs.

    `subject_ref` rides along with `source` (D-185): the entry id alone stops answering
    "which number was released" the moment the row is gone, and the one-way handle
    answers it for an auditor holding the number without writing a number into the
    ledger (hard rule 6). See `dnc.Removal` for why this is not a tombstoned row.

    Same shape as `DELETE /v1/lead-sources/{id}` and `DELETE /v1/leads/views/{id}`,
    which is the answer this repo already gives for a delete with nothing to report.
    """
    assert principal.tenant_id is not None
    removal = await dnc.remove_entry(session, tenant_id=principal.tenant_id, entry_id=entry_id)
    await write_audit(
        session,
        action="dnc.removed",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="dnc_list",
        object_id=str(entry_id),
        ip=client_request_ip(request),
        summary={"source": removal.source, "subject_ref": removal.subject_ref},
    )


class OptOutEvidenceOut(Strict):
    """One recorded opt-out behind a list entry, shown before anyone restores it."""

    id: UUID
    recorded_at: datetime
    #: The call it was recorded on, for a link to that call's page; None when unknown.
    call_id: UUID | None
    #: `in_call_tool` and `engine_platform` mean the agent recorded it during the call;
    #: `post_call_transcript` means our check of the transcript found the words.
    detected_by: str | None
    #: The caller's words as stored, redacted. None when the agent recorded it without them.
    matched_redacted: str | None


class EntryEvidenceOut(Strict):
    restorable: bool
    #: Newest first, at most `dnc.MAX_OPTOUT_EVIDENCE`.
    records: list[OptOutEvidenceOut] = Field(max_length=dnc.MAX_OPTOUT_EVIDENCE)


class RestoreIn(Strict):
    ground: Literal["never_asked", "asked_to_be_called"]
    #: Required for `asked_to_be_called`: how and when they asked. Redacted before it is kept.
    note: str | None = Field(default=None, max_length=dnc.RESTORE_NOTE_MAX * 2)
    #: The newest record the person restoring was shown (None when there was none), so a
    #: newer opt-out recorded meanwhile is refused rather than undone unseen.
    latest_evidence_id: UUID | None


@router.get(
    "/{entry_id}/evidence",
    response_model=EntryEvidenceOut,
    openapi_extra=permission_meta("leads:read"),
    summary="Why this number is on the list — the recorded opt-outs behind it",
)
async def evidence(entry_id: UUID, session: Session, _: Reader) -> EntryEvidenceOut:
    found = await dnc.optout_evidence(session, entry_id=entry_id)
    return EntryEvidenceOut(
        restorable=found.restorable,
        records=[
            OptOutEvidenceOut(
                id=record.id,
                recorded_at=record.recorded_at,
                call_id=record.call_id,
                detected_by=record.detected_by,
                matched_redacted=record.matched,
            )
            for record in found.records
        ],
    )


@router.post(
    "/{entry_id}/restore",
    status_code=204,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Restore a person's opt-out recorded by mistake or since withdrawn — attested",
)
async def restore(
    entry_id: UUID,
    payload: RestoreIn,
    session: Session,
    request: Request,
    principal: Dispatcher,
) -> None:
    """204, for `remove`'s reason: the row just deleted holds a phone number.

    The ground is an attestation by a named person at the client, so a view-as session may
    not make it (`rbac.VIEW_AS_WITHHELD_ACTS["compliance.dnc_optout_restore"]`).
    """
    assert_view_as_may(principal, "compliance.dnc_optout_restore")
    assert principal.tenant_id is not None
    restoration = await dnc.restore_optout(
        session,
        tenant_id=principal.tenant_id,
        entry_id=entry_id,
        ground=payload.ground,
        note=payload.note,
        latest_evidence_id=payload.latest_evidence_id,
    )
    await write_audit(
        session,
        action=dnc.restore_audit_action(payload.ground),
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="dnc_list",
        object_id=str(entry_id),
        ip=client_request_ip(request),
        summary={
            "source": restoration.source,
            "subject_ref": restoration.subject_ref,
            "ground": payload.ground,
            "note": restoration.note,
        },
    )


__all__ = ["router"]
