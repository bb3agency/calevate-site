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
and inventing a permission for one unmounted route is how a role table stops being
readable.

Every call writes `audit_log`, in the same transaction as the read. An export of one
person's personal data is precisely the event `audit_log` exists to make answerable
later, and the audit row carries a `subject_ref` hash rather than the number (hard
rule 6) — so the record of the disclosure never becomes another copy of what was
disclosed.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.export import build_subject_export, subject_ref
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/subject-export", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# The `Annotated` alias form rather than a `Depends()` default: this file is
# `export_routes.py`, not `routes.py`, so it sits outside the B008 per-file ignore in
# pyproject — same situation, and same resolution, as `agents/prompt_routes.py`.
SubjectExportReader = Annotated[Principal, Depends(requires("calls:read_raw"))]


class SubjectExportIn(BaseModel):
    """`extra="forbid"` so a caller cannot smuggle a second selector (a lead id, a
    tenant slug) into a request whose whole security argument is "one phone number"."""

    model_config = ConfigDict(extra="forbid")

    # E.164 (conventions), same pattern as the admin DNC endpoint. A POST rather than a
    # GET for one reason: the identifier IS the personal data, and a GET would write it
    # into access logs, proxy logs and browser history (hard rule 6).
    phone: str = Field(min_length=8, max_length=20, pattern=r"^\+[1-9]\d{7,18}$")


@router.post(
    "",
    openapi_extra=permission_meta("calls:read_raw"),
    summary="DPDP subject access/portability export for one phone number — audited",
)
async def subject_export(
    payload: SubjectExportIn,
    session: Session,
    request: Request,
    principal: SubjectExportReader,
) -> dict[str, Any]:
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
        ip=request.client.host if request.client else None,
        summary={
            "subject_ref": subject_ref(payload.phone),
            "lead_id": lead["id"] if lead else None,
            "calls": counts["calls"],
            "turns": counts["transcript_turns"],
            "consent_records": counts["consent_records"],
        },
    )
    return document


__all__ = ["SubjectExportIn", "router"]
