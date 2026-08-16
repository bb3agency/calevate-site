"""Capture surface for messaging consent (SEC-COMP §2/§4; migration c2f7a91b4e63).

The reasoning that decides who may call these, and why the number is where it is, lives
in `compliance/consent.py`. Four shapes worth explaining before someone "tidies" them:

- **Both endpoints are POST**, including the lookup. The identifier IS the personal
  data, and a GET writes it into access logs, proxy logs, referrers and browser
  history — the same rule `dnc_routes.py` states and the subject-access export follows.
  There is no route in this module with a phone number anywhere in its path or query.
- **Recording is `leads:dispatch`.** It is the permission that already governs who may
  cause a person to be contacted, and an opt-in is exactly that decision: it is what
  turns an exhausted campaign contact into a message. Reusing it also keeps the
  authority symmetrical with `POST /v1/dnc`, which is the same decision inverted. A new
  permission would be one nobody has been granted and one nothing in `ROLE_PERMISSIONS`
  had to think about.
- **The lookup is `leads:read`**, not `org:manage`: reading whether somebody may be
  messaged is not changing it, and `org:manage` is in `MUTATING_PERMISSIONS`, so D-22
  would make this invisible inside a read-only "view as client" session — the recurring
  bug `tests/impersonation_reads_test.py` exists to stop.
- **Nothing echoes the number back.** The responses carry a status, a source and two
  timestamps. The caller already holds the number they sent; a response repeating it
  only creates another copy to leak.

There is no DELETE. A consent record is not removable — hard rule 4 — and the way to
say "no longer" is `status: "withdrawn"`, which is a new row that supersedes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance import consent
from apps.api.compliance.audit import write_audit
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta
from apps.api.ingest.service import normalize_phone

router = APIRouter(prefix="/v1/compliance/messaging-consent", tags=["compliance"])

Session = Annotated[AsyncSession, Depends(db)]
# `Annotated` aliases rather than `Depends(...)` defaults: B008 is only waived for
# `**/routes.py`, and this module is `consent_routes.py` — same situation, and same
# resolution, as `dnc_routes.py` and `registration_routes.py`.
Recorder = Annotated[Principal, Depends(requires("leads:dispatch"))]
Reader = Annotated[Principal, Depends(requires("leads:read"))]

# Spelled as a Literal rather than derived from the tuple so the generated TypeScript
# client gets a union it can switch on. The tuple in `compliance/models.py` is still the
# source of truth: `tests/messaging_consent_test.py` asserts the two cannot drift.
ConsentSource = Literal[
    "inbound_call_verbal",
    "web_form_optin",
    "offline_form_optin",
    "whatsapp_inbound_message",
    "staff_recorded_request",
]
ConsentStatus = Literal["granted", "declined", "withdrawn"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordConsentIn(Strict):
    # Raw as the client holds it: 10-digit, +91 and spaced forms all arrive here and
    # `normalize_phone` decides, so the stored key matches the campaign contact's.
    phone: str = Field(min_length=8, max_length=20)
    status: ConsentStatus
    source: ConsentSource
    # Required for a spoken opt-in and meaningless otherwise. Enforced in the service
    # (and by a CHECK), not by the type, so the refusal can explain itself.
    call_id: UUID | None = None
    # What the opt-in rests on: the form and the version of the notice shown, the
    # reference of a signed paper form, or the inbound message id. Meta expects a
    # business to be able to produce the source and timestamp of an opt-in when a
    # number is challenged — this is where the source half lives.
    evidence: dict[str, str] | None = Field(default=None, max_length=20)


class LookupConsentIn(Strict):
    phone: str = Field(min_length=8, max_length=20)


class MessagingConsentOut(Strict):
    """Never the number. `status: "none"` means nobody has ever asked this person,
    which is a 200 and the normal state of the world, not a 404."""

    status: str
    source: str | None
    captured_at: datetime | None
    # When this opt-in stops being current (`consent.MESSAGING_CONSENT_VALIDITY_DAYS`).
    # Returned so a console can show "expires in 3 weeks" rather than discovering it as
    # a silent refusal on the day it lapses.
    expires_at: datetime | None
    # The whole question, computed server-side: granted AND not stale. The console must
    # not re-derive it, or it will disagree with the worker on the day it matters.
    messageable: bool


def _out(state: consent.MessagingConsent) -> MessagingConsentOut:
    return MessagingConsentOut(
        status=state.status,
        source=state.source,
        captured_at=state.captured_at,
        expires_at=state.expires_at,
        messageable=state.messageable,
    )


@router.post(
    "",
    response_model=MessagingConsentOut,
    status_code=201,
    openapi_extra=permission_meta("leads:dispatch"),
    summary="Record what a customer said about being messaged (append-only)",
    description=(
        "Appends one row to the consent ledger. A withdrawal is a new row with "
        "`status: withdrawn`, never an edit of the opt-in it supersedes. A grant must "
        "carry evidence, and your own staff may only record an opt-OUT."
    ),
)
async def record(
    payload: RecordConsentIn,
    session: Session,
    request: Request,
    principal: Recorder,
) -> MessagingConsentOut:
    assert principal.tenant_id is not None
    state = await consent.record_messaging_consent(
        session,
        tenant_id=principal.tenant_id,
        raw_phone=payload.phone,
        status=payload.status,
        source=payload.source,
        call_id=payload.call_id,
        evidence=payload.evidence,
    )
    await write_audit(
        session,
        action="messaging_consent.recorded",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="consent_ledger",
        object_id=None,
        ip=client_request_ip(request),
        # The decision, not the subject. The audit log is read by more people than this
        # endpoint, and "who did we newly permit ourselves to message" is not a list
        # that needs numbers in it to be useful.
        summary={
            "status": payload.status,
            "source": payload.source,
            "evidenced": bool(payload.evidence),
        },
    )
    return _out(state)


@router.post(
    "/lookup",
    response_model=MessagingConsentOut,
    openapi_extra=permission_meta("leads:read"),
    summary="May we message this number? (POST: the identifier IS the personal data)",
)
async def lookup(
    payload: LookupConsentIn,
    session: Session,
    principal: Reader,
) -> MessagingConsentOut:
    assert principal.tenant_id is not None
    phone_e164 = normalize_phone(payload.phone)
    if phone_e164 is None:
        # A number we cannot normalise has no ledger key, so it has no consent — the
        # same answer as a number nobody ever asked, and a truthful one.
        return _out(consent.NO_CONSENT)
    return _out(
        await consent.read_messaging_consent(
            session, tenant_id=principal.tenant_id, phone_e164=phone_e164
        )
    )


__all__ = ["router"]
