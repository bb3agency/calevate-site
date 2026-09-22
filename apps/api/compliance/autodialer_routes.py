"""Where a sender records the autodialler notice every outbound dial depends on.

    GET  /v1/compliance/autodialer-notice   "why is none of my outbound going out?"
    POST /v1/compliance/autodialer-notice   the sender records the notice, or withdraws it

**THE DEFECT THIS CLOSES.** `autodialer_notice_blocker` was wired into `check_dispatch`
and refuses every outbound dial for a tenant with no notice on file — and nothing in the
product could write one. `record_autodialer_notice` had no caller anywhere: no route, no
client screen, no admin screen. The gate was therefore unconditional and unclearable, and
the readiness row told a client to "record the date here" for a *here* that did not exist.
A blocker with no remedy is worse than no blocker: it is a product that refuses to work
and blames the customer.

**CLIENT-REALM, AND THERE IS NO ADMIN TWIN — deliberately, unlike the carrier
application.** The carrier's DECISION arrives out of band and only ops can know it, so
that gate needs an admin route. This is the opposite shape: the notice is a letter between
the client's business and the client's own access provider, the client is the only party
to it, and `compliance/autodialer.py` states in terms that Calevate does not notify on a
client's behalf. An operator route that let somebody at Calevate record it would let us
open an outbound gate on a declaration the sender never made — the same defect as a client
marking their own carrier application `accepted`, pointed the other way. If a support
person is helping over the phone, the client still clicks it; that is the point.

**`org:read` to look, `org:manage` to record.** Looking keeps it visible inside a
read-only view-as session (D-22), which is exactly the session support is in when the
client rings asking why nothing dials. Recording is the sender's own act and takes the
mutating permission, which D-22 withholds from view-as for that reason.

**A tenant with nothing on file is a 200 with `recorded: false`, never a 404.** It is the
state of every new account, and a 404 reaches the fetch layer indistinguishable from a
moved route or a lost session.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.compliance.autodialer import (
    MAX_ACCESS_PROVIDER_CHARS,
    MAX_NOTICE_REFERENCE_CHARS,
    MAX_OBJECTIVE_CHARS,
    AutodialerNotice,
    read_autodialer_notice,
    record_autodialer_notice,
)
from apps.api.core.auth import client_request_ip, requires
from apps.api.core.context import Principal
from apps.api.core.deps import db
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import permission_meta

router = APIRouter(prefix="/v1/compliance/autodialer-notice", tags=["compliance"])

# `Annotated` aliases rather than `Depends(...)` defaults: B008 is waived only for
# `**/routes.py`, and this module is `autodialer_routes.py` — the same situation and the
# same resolution as `carrier_application_routes.py` beside it.
Session = Annotated[AsyncSession, Depends(db)]
NoticeReader = Annotated[Principal, Depends(requires("org:read"))]
NoticeRecorder = Annotated[Principal, Depends(requires("org:manage"))]


class AutodialerNoticeOut(BaseModel):
    """What this account has on file, and whether it is carrying outbound today."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool
    state: str | None
    access_provider: str | None
    objective: str | None
    notified_on: date | None
    notice_reference: str | None
    #: DERIVED from the same predicate the dial gate uses, never a second reading of it.
    #: A notice dated in the future is recorded and `notified` and still not effective,
    #: which is three facts a screen has to tell apart to say anything useful.
    effective: bool


class AutodialerNoticeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The operator that supplies the outbound line — the client's own carrier
    #: relationship, which Model B means we hold no account with and may never see.
    access_provider: str = Field(min_length=1, max_length=MAX_ACCESS_PROVIDER_CHARS)
    objective: str = Field(min_length=1, max_length=MAX_OBJECTIVE_CHARS)
    #: What the letter is dated, in the client's own calendar. A future date is accepted
    #: and the gate holds outbound until it arrives — see `record_autodialer_notice`.
    notified_on: date
    notice_reference: str | None = Field(default=None, max_length=MAX_NOTICE_REFERENCE_CHARS)
    #: A withdrawal is a NEW row carrying the same three facts, never an edit of the
    #: notice it retracts (hard rule 4) — the history has to keep showing that the notice
    #: was live while last month's calls were placed.
    withdraw: bool = False


def _out(notice: AutodialerNotice) -> AutodialerNoticeOut:
    return AutodialerNoticeOut(
        recorded=notice.recorded,
        state=notice.state,
        access_provider=notice.access_provider,
        objective=notice.objective,
        notified_on=notice.notified_on,
        notice_reference=notice.notice_reference,
        effective=notice.is_effective(),
    )


@router.get(
    "",
    response_model=AutodialerNoticeOut,
    openapi_extra=permission_meta("org:read"),
    summary="The autodialler notice this account has on file",
    description=(
        "Every outbound call Calevate places for you is dialled automatically, and the "
        "rules put one duty on the sender of such calls: tell your own telecom access "
        "provider, in writing and in advance, that you use an automated dialler and what "
        "the calls are for. You are the sender, so the notice is yours to give and ours "
        "to record. Until this says `effective`, no outbound call goes out. Answering "
        "incoming calls is unaffected. An account with nothing on file gets "
        "`recorded: false` and a 200."
    ),
)
async def read_notice(session: Session, principal: NoticeReader) -> AutodialerNoticeOut:
    assert principal.tenant_id is not None
    return _out(await read_autodialer_notice(session, tenant_id=principal.tenant_id))


@router.post(
    "",
    response_model=AutodialerNoticeOut,
    status_code=201,
    openapi_extra=permission_meta("org:manage"),
    summary="Record that you have given your access provider the notice, or withdraw it",
    description=(
        "Record the notice after you have sent it — this is where you tell us it exists, "
        "not where it is sent. Name the provider you sent it to, what the calls are for, "
        "and the date on the letter. If you dated it in the future, that is fine: it is "
        "recorded now and your outbound starts on that date. Withdrawing files a new "
        "record rather than deleting the old one, so the history still shows the notice "
        "was live while earlier calls were placed."
    ),
)
async def record_notice(
    body: AutodialerNoticeIn, request: Request, session: Session, principal: NoticeRecorder
) -> AutodialerNoticeOut:
    """Append the notice, then read the account's position back from the database.

    READ BACK rather than construct the answer from `body`: the gate reads the LATEST row
    for the tenant, so the only honest answer to "where do I stand now" is that same read.
    Building the response from what was just submitted would agree with itself by
    construction and would be wrong the moment two people record in one second.
    """
    assert principal.tenant_id is not None
    # `client_user_id`, NEVER `user_id` (D-587). `recorded_by` is a `users.id` foreign
    # key, and on an impersonated session `user_id` is an `admin_users.id` — storing it
    # would be an FK violation at best and a silent id-space mixture at worst. The
    # operator answer is `None`, and it is refused here rather than stored as "no person":
    # a notice is a declaration by the sender, so a record with nobody behind it is not
    # evidence of anything. The operator is named in the audit row either way.
    actor = principal.client_user_id
    if actor is None:
        raise ProblemError.business_rule(
            "autodialer_notice_is_the_senders_own_act",
            "This has to be recorded by somebody at your own business.",
            remediation=(
                "Sign in to your own account and record it there. Nobody at Calevate can "
                "give this notice or record it for you, because it is a letter between "
                "your business and your access provider."
            ),
        )
    row_id = await record_autodialer_notice(
        session,
        tenant_id=principal.tenant_id,
        access_provider=body.access_provider,
        objective=body.objective,
        notified_on=body.notified_on,
        notice_reference=body.notice_reference,
        recorded_by=actor,
        withdraw=body.withdraw,
    )
    # IN THE SAME TRANSACTION as the row it describes (`write_audit`'s contract), so no
    # notice can exist without the entry saying who filed it and from where. This is the
    # declaration that opens every outbound dial for the account: `recorded_by` names a
    # client user, and only this row names the operator when the act came through a
    # view-as session. The objective is not copied — it is the client's own prose, adds
    # nothing an auditor needs, and the audit log is read cross-tenant.
    await write_audit(
        session,
        action="autodialer_notice.withdrawn" if body.withdraw else "autodialer_notice.recorded",
        actor=principal,
        tenant_id=principal.tenant_id,
        object_type="autodialer_notice",
        object_id=str(row_id),
        ip=client_request_ip(request),
        summary={
            "access_provider": body.access_provider,
            "notified_on": body.notified_on.isoformat(),
            # Whether one was given, not what it says: the same predicate the service
            # stores by, so a blank string does not read as a reference on file.
            "notice_reference_given": bool((body.notice_reference or "").strip()),
        },
    )
    return _out(await read_autodialer_notice(session, tenant_id=principal.tenant_id))


__all__ = ["AutodialerNoticeIn", "AutodialerNoticeOut", "router"]
