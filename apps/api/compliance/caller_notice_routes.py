"""The client's own caller-notice draft (LEGAL-SURFACE F-8, D-179).

    GET /v1/compliance/caller-notice

DPDP Rule 3 wants an ITEMISED description of the personal data collected, and for a
Calevate client that list is their extraction schema — which only we hold. This hands it
back in the shape the rule asks for, as a draft for their counsel. The reasoning, and
everything it deliberately refuses to do, is in `compliance/caller_notice.py`; this module
is the surface.

Four shapes, and each one is the same decision the erasure surfaces next door made:

- **`org:read`, not `org:manage`.** Reading your own configuration back is not changing
  it, and `org:manage` is in `MUTATING_PERMISSIONS`, so requiring it would hide this from
  the read-only "view as client" session (D-22) that support is in when a client rings
  asking how to write their privacy notice. That is the call this exists for.
- **A GET, unlike the erasure and export surfaces.** Those are keyed by a phone number, so
  a GET would write personal data into access logs, proxy logs and browser history (hard
  rule 6). This response is about the ACCOUNT's configuration and carries no caller's
  data — no number, no transcript, no extracted value, only field labels the client wrote
  themselves.
- **Not audited.** Same reason the erasure status read is not: it discloses no personal
  data, it is a screen a client may reload, and an audit chain that grows a row per page
  view stops being readable.
- **A 200 on an empty account.** A client with no published agent still gets the draft,
  with the inherent items a phone call always collects and their retention rows. "You have
  not launched yet" is not an answer to "what will I be collecting?" — and the wizard's
  last step is exactly where somebody asks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.caller_notice import DRAFT_WARNING, build_caller_notice
from apps.api.core.auth import requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/caller-notice", tags=["compliance"])

# The `Annotated` alias form rather than a `Depends()` default: B008 is waived only for
# `**/routes.py`, and this module is `caller_notice_routes.py` — same situation and same
# resolution as `deletion_routes.py`.
Session = Annotated[AsyncSession, Depends(db)]
NoticeReader = Annotated[Principal, Depends(requires("org:read"))]


class CollectedItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what: str
    why: str


class RetentionLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what: str
    days: int


class CallerNoticeOut(BaseModel):
    """The draft, structured and rendered.

    Both halves ship on purpose: a screen renders the structure into its own layout, and
    `text` is what a client actually pastes into their website. Rebuilding the prose on
    the client side would put the wording — the part counsel reviews — outside the thing
    that was reviewed.
    """

    model_config = ConfigDict(extra="forbid")

    #: Repeated in the response AND at the top of `text`. A disclaimer that lives only in
    #: the envelope does not travel with the document once it is copied out.
    disclaimer: str
    collected: list[CollectedItemOut]
    retention: list[RetentionLineOut]
    #: Named, not counted: with an announcement switched off, the client's own notice is
    #: where the obligation lands, and they need to know which agent it is.
    ai_disclosure_off: list[str]
    recording_notice_off: list[str]
    open_questions: list[str]
    text: str


@router.get(
    "",
    response_model=CallerNoticeOut,
    openapi_extra=permission_meta("org:read"),
    summary="A draft of the privacy notice you owe your own callers",
    description=(
        "Indian data-protection law requires you to tell your callers, item by item, "
        "what you collect from them and how long you keep it. For a Calevate account "
        "that list is the fields your agents capture, your retention settings and your "
        "announcement settings — which live here. This generates a DRAFT from them, "
        "with blanks marked where only you can answer. It is not legal advice and must "
        "be reviewed by your own advocate before you publish it."
    ),
)
async def read_caller_notice(session: Session, principal: NoticeReader) -> CallerNoticeOut:
    assert principal.tenant_id is not None
    draft = await build_caller_notice(session, tenant_id=principal.tenant_id)
    return CallerNoticeOut(
        disclaimer=DRAFT_WARNING,
        collected=[CollectedItemOut(what=item.what, why=item.why) for item in draft.collected],
        retention=[RetentionLineOut(what=line.what, days=line.days) for line in draft.retention],
        ai_disclosure_off=draft.ai_disclosure_off,
        recording_notice_off=draft.recording_notice_off,
        open_questions=draft.open_questions,
        text=draft.text,
    )
